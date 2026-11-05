"""SQLite persistence for runs, decisions (with human corrections) and benchmarks."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .schema import DECISION_FIELDS, Decision

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    name TEXT NOT NULL,
    source TEXT NOT NULL,
    model TEXT NOT NULL,
    threshold REAL NOT NULL,
    status TEXT NOT NULL,            -- queued | running | done | failed
    total INTEGER NOT NULL DEFAULT 0,
    done INTEGER NOT NULL DEFAULT 0,
    failed INTEGER NOT NULL DEFAULT 0,
    error TEXT
);
CREATE TABLE IF NOT EXISTS decisions (
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    review_id TEXT NOT NULL,
    position INTEGER NOT NULL,
    text TEXT NOT NULL,
    topic TEXT, sentiment TEXT, defect INTEGER, refund_request INTEGER,
    confidence TEXT,                  -- json {field: prob}
    min_confidence REAL,
    model TEXT,
    latency_ms REAL, input_tokens INTEGER, output_tokens INTEGER, cost_usd REAL,
    error TEXT,
    reviewed INTEGER NOT NULL DEFAULT 0,
    corrected INTEGER NOT NULL DEFAULT 0,
    original TEXT,                    -- json of the model's original labels
    updated_at TEXT,
    PRIMARY KEY (run_id, review_id)
);
CREATE TABLE IF NOT EXISTS benchmarks (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL,
    models TEXT NOT NULL,
    progress TEXT,
    report TEXT,
    error TEXT
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: str | Path | None = None):
        self.path = str(path or os.getenv("DB_PATH", "reports/app.db"))
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.executescript(SCHEMA)

    @contextmanager
    def tx(self):
        with self._lock:
            try:
                yield self._conn
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    def q(self, sql: str, args=()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, args).fetchall()]

    # ---- runs ----
    def create_run(self, *, name: str, source: str, model: str, threshold: float, reviews) -> str:
        run_id = uuid.uuid4().hex[:12]
        with self.tx() as c:
            c.execute(
                "INSERT INTO runs (id, created_at, name, source, model, threshold, status, total) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (run_id, now(), name, source, model, threshold, "queued", len(reviews)),
            )
            c.executemany(
                "INSERT INTO decisions (run_id, review_id, position, text) VALUES (?,?,?,?)",
                [(run_id, r.review_id, i, r.text) for i, r in enumerate(reviews)],
            )
        return run_id

    def set_run(self, run_id: str, **fields) -> None:
        cols = ", ".join(f"{k} = ?" for k in fields)
        with self.tx() as c:
            c.execute(f"UPDATE runs SET {cols} WHERE id = ?", (*fields.values(), run_id))

    def save_decision(self, run_id: str, d: Decision) -> None:
        labels = {f: getattr(d, f) for f in DECISION_FIELDS}
        with self.tx() as c:
            c.execute(
                """UPDATE decisions SET topic=?, sentiment=?, defect=?, refund_request=?, confidence=?,
                   min_confidence=?, model=?, latency_ms=?, input_tokens=?, output_tokens=?, cost_usd=?,
                   error=NULL, original=?, updated_at=? WHERE run_id=? AND review_id=?""",
                (d.topic, d.sentiment, int(d.defect), int(d.refund_request), json.dumps(d.confidence),
                 d.min_confidence(), d.model, d.latency_ms, d.input_tokens, d.output_tokens, d.cost_usd,
                 json.dumps(labels), now(), run_id, d.review_id),
            )
            c.execute("UPDATE runs SET done = done + 1 WHERE id = ?", (run_id,))

    def save_error(self, run_id: str, review_id: str, error: str) -> None:
        with self.tx() as c:
            c.execute("UPDATE decisions SET error=?, updated_at=? WHERE run_id=? AND review_id=?",
                      (error, now(), run_id, review_id))
            c.execute("UPDATE runs SET failed = failed + 1 WHERE id = ?", (run_id,))

    def list_runs(self) -> list[dict]:
        return [self._run_row(r) for r in self.q("SELECT * FROM runs ORDER BY created_at DESC")]

    def get_run(self, run_id: str) -> dict | None:
        rows = self.q("SELECT * FROM runs WHERE id = ?", (run_id,))
        return self._run_row(rows[0]) if rows else None

    def _run_row(self, r: dict) -> dict:
        stats = self.q(
            """SELECT COUNT(*) n, SUM(cost_usd) cost, SUM(reviewed) reviewed,
                      SUM(CASE WHEN topic IS NOT NULL AND min_confidence < ? AND reviewed = 0 THEN 1 ELSE 0 END) pending
               FROM decisions WHERE run_id = ?""",
            (r["threshold"], r["id"]),
        )[0]
        return {**r, "cost_usd": stats["cost"] or 0.0, "reviewed": stats["reviewed"] or 0,
                "pending_review": stats["pending"] or 0}

    def delete_run(self, run_id: str) -> None:
        with self.tx() as c:
            c.execute("DELETE FROM runs WHERE id = ?", (run_id,))

    def decisions(self, run_id: str) -> list[dict]:
        run = self.get_run(run_id)
        threshold = run["threshold"] if run else 0.8
        out = []
        for r in self.q("SELECT * FROM decisions WHERE run_id = ? ORDER BY position", (run_id,)):
            r["defect"] = None if r["defect"] is None else bool(r["defect"])
            r["refund_request"] = None if r["refund_request"] is None else bool(r["refund_request"])
            r["reviewed"] = bool(r["reviewed"])
            r["corrected"] = bool(r["corrected"])
            r["confidence"] = json.loads(r["confidence"]) if r["confidence"] else {}
            r["original"] = json.loads(r["original"]) if r["original"] else None
            r["needs_review"] = r["topic"] is not None and (r["min_confidence"] or 0) < threshold
            out.append(r)
        return out

    def update_decision(self, run_id: str, review_id: str, changes: dict) -> dict | None:
        rows = self.decisions(run_id)
        cur = next((r for r in rows if r["review_id"] == review_id), None)
        if cur is None:
            return None
        labels = {f: changes.get(f, cur[f]) for f in DECISION_FIELDS}
        corrected = cur["original"] is not None and any(labels[f] != cur["original"][f] for f in DECISION_FIELDS)
        reviewed = bool(changes.get("reviewed", True))
        with self.tx() as c:
            c.execute(
                """UPDATE decisions SET topic=?, sentiment=?, defect=?, refund_request=?, reviewed=?, corrected=?,
                   updated_at=? WHERE run_id=? AND review_id=?""",
                (labels["topic"], labels["sentiment"], int(bool(labels["defect"])),
                 int(bool(labels["refund_request"])), int(reviewed), int(corrected), now(), run_id, review_id),
            )
        return next(r for r in self.decisions(run_id) if r["review_id"] == review_id)

    # ---- benchmarks ----
    def create_benchmark(self, models: list[str]) -> str:
        bid = uuid.uuid4().hex[:12]
        with self.tx() as c:
            c.execute("INSERT INTO benchmarks (id, created_at, status, models, progress) VALUES (?,?,?,?,?)",
                      (bid, now(), "queued", json.dumps(models), json.dumps({})))
        return bid

    def set_benchmark(self, bid: str, **fields) -> None:
        for k in ("report", "progress", "models"):
            if k in fields and not isinstance(fields[k], str):
                fields[k] = json.dumps(fields[k])
        cols = ", ".join(f"{k} = ?" for k in fields)
        with self.tx() as c:
            c.execute(f"UPDATE benchmarks SET {cols} WHERE id = ?", (*fields.values(), bid))

    def list_benchmarks(self) -> list[dict]:
        rows = self.q("SELECT * FROM benchmarks ORDER BY created_at DESC")
        for r in rows:
            for k in ("models", "progress", "report"):
                r[k] = json.loads(r[k]) if r[k] else None
        return rows

    def get_benchmark(self, bid: str) -> dict | None:
        return next((b for b in self.list_benchmarks() if b["id"] == bid), None)
