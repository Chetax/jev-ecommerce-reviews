"""FastAPI backend for the web UI.

Run: jev-reviews serve   (serves the API and, if built, the React app from web/dist)
"""

from __future__ import annotations

import csv
import os
import io as stdio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import io
from .classifiers import make_classifier, model_options
from .config import Settings, get_settings
from .pipeline import benchmark_report, run
from .schema import DECISION_FIELDS, SENTIMENTS, TOPICS, Review
from .store import Store
from .tracing import setup_tracing

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "data" / "sample_reviews.csv"
WEB_DIST = ROOT / "web" / "dist"
MAX_ROWS = 5000


class RunCreate(BaseModel):
    source: Literal["sample", "csv", "sheet"]
    model: str = "bedrock"
    name: str | None = None
    csv_text: str | None = None
    threshold: float | None = Field(default=None, ge=0, le=1)


class DecisionPatch(BaseModel):
    topic: str | None = None
    sentiment: str | None = None
    defect: bool | None = None
    refund_request: bool | None = None
    reviewed: bool = True


class BenchmarkCreate(BaseModel):
    models: list[str] = Field(min_length=1)
    csv_text: str | None = None


def parse_csv_text(text: str) -> list[Review]:
    reader = csv.DictReader(stdio.StringIO(text.lstrip("﻿")))
    fields = {f.strip().lower() for f in (reader.fieldnames or [])}
    if not fields & {"text", "review"}:
        raise HTTPException(422, "CSV needs a 'text' (or 'review') column.")
    try:
        reviews = io._rows_to_reviews(reader)
    except ValueError as e:
        raise HTTPException(422, f"Invalid CSV: {e}") from e
    if not reviews:
        raise HTTPException(422, "CSV has no reviews.")
    if len(reviews) > MAX_ROWS:
        raise HTTPException(422, f"CSV has {len(reviews)} rows; the limit is {MAX_ROWS}.")
    ids = [r.review_id for r in reviews]
    if len(set(ids)) != len(ids):
        raise HTTPException(422, "review_id values must be unique.")
    return reviews


def explain_error(err: str) -> str:
    """Turn a raw API error into a short, actionable message for the UI."""
    if "bedrock-mantle:CreateInference" in err:
        user = err.split("User: ")[1].split(" ")[0] if "User: " in err else "Your AWS identity"
        return (f"AWS denied access: {user} is missing the bedrock-mantle:CreateInference permission. "
                "Add it in IAM, or set AWS_BEARER_TOKEN_BEDROCK in .env, then restart the server.")
    if "401" in err or "403" in err:
        return ("Bedrock rejected the credentials. Check AWS_BEARER_TOKEN_BEDROCK / AWS_REGION and that model "
                "access is enabled in the Bedrock console. Run `jev-reviews doctor` for details.")
    return err[:300]


def create_app(store: Store | None = None, settings: Settings | None = None,
               classifier_factory: Callable | None = None, workers: int = 8) -> FastAPI:
    settings = settings or get_settings()
    tracing_on = setup_tracing()
    store = store or Store()
    factory = classifier_factory or (lambda spec: make_classifier(spec, settings))
    jobs = ThreadPoolExecutor(max_workers=2, thread_name_prefix="job")

    app = FastAPI(title="Review Decisions API")
    app.state.store = store
    app.state.jobs = jobs

    # ---- meta ----
    @app.get("/api/config")
    def config():
        return {
            "bedrock_model": settings.bedrock_model_id,
            "aws_region": settings.aws_region,
            "effort": settings.bedrock_effort,
            "jev_enabled": settings.jev_enabled,
            "sheets_enabled": bool(settings.sheet_id),
            "threshold": settings.confidence_threshold,
            "models": model_options(settings),
            "topics": list(TOPICS),
            "topic_descriptions": TOPICS,
            "sentiments": SENTIMENTS,
            "tracing_url": os.getenv("PHOENIX_COLLECTOR_ENDPOINT") if tracing_on else None,
        }

    # ---- runs ----
    def execute_run(run_id: str, spec: str, reviews: list[Review], threshold: float, name: str):
        try:
            clf = factory(spec)
            store.set_run(run_id, status="running")
            first_error: list[str] = []

            def on_result(r, d, err):
                if d:
                    store.save_decision(run_id, d)
                else:
                    first_error[:1] = first_error[:1] or [err]
                    store.save_error(run_id, r.review_id, err)

            run(clf, reviews, workers=workers, progress=False, session_id=f"{name} · {run_id}", threshold=threshold,
                on_result=on_result)
            r = store.get_run(run_id)
            status = "failed" if r and r["failed"] == r["total"] else "done"
            store.set_run(run_id, status=status, error=f"All reviews failed. {explain_error(first_error[0])}"
                          if status == "failed" and first_error else None)
        except Exception as e:
            store.set_run(run_id, status="failed", error=f"{type(e).__name__}: {e}")

    @app.post("/api/runs", status_code=201)
    def create_run(body: RunCreate):
        if body.source == "sample":
            reviews, default_name = io.read_csv(SAMPLE), "Sample reviews"
        elif body.source == "csv":
            if not body.csv_text:
                raise HTTPException(422, "csv_text is required for source 'csv'.")
            reviews, default_name = parse_csv_text(body.csv_text), "Uploaded CSV"
        else:
            if not settings.sheet_id:
                raise HTTPException(422, "Google Sheets is not configured (SHEET_ID).")
            try:
                reviews = io.read_sheet(settings)
            except Exception as e:
                raise HTTPException(502, f"Could not read Google Sheet: {e}") from e
            default_name = f"Sheet · {settings.sheet_input_tab}"
        try:
            factory(body.model)  # validate spec / keys up front
        except (ValueError, RuntimeError) as e:
            raise HTTPException(422, str(e)) from e
        threshold = body.threshold if body.threshold is not None else settings.confidence_threshold
        name = body.name or default_name
        run_id = store.create_run(name=name, source=body.source, model=body.model,
                                  threshold=threshold, reviews=reviews)
        jobs.submit(execute_run, run_id, body.model, reviews, threshold, name)
        return store.get_run(run_id)

    @app.get("/api/runs")
    def list_runs():
        return store.list_runs()

    def _run_or_404(run_id: str) -> dict:
        r = store.get_run(run_id)
        if not r:
            raise HTTPException(404, "Run not found")
        return r

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str):
        return _run_or_404(run_id)

    @app.delete("/api/runs/{run_id}", status_code=204)
    def delete_run(run_id: str):
        r = _run_or_404(run_id)
        if r["status"] in ("queued", "running"):
            raise HTTPException(409, "Run is still in progress.")
        store.delete_run(run_id)

    @app.get("/api/runs/{run_id}/decisions")
    def decisions(run_id: str):
        _run_or_404(run_id)
        return store.decisions(run_id)

    @app.patch("/api/runs/{run_id}/decisions/{review_id}")
    def patch_decision(run_id: str, review_id: str, body: DecisionPatch):
        _run_or_404(run_id)
        changes = body.model_dump(exclude_none=True)
        if "topic" in changes and changes["topic"] not in TOPICS:
            raise HTTPException(422, f"Unknown topic {changes['topic']!r}")
        if "sentiment" in changes and changes["sentiment"] not in SENTIMENTS:
            raise HTTPException(422, f"Unknown sentiment {changes['sentiment']!r}")
        row = store.update_decision(run_id, review_id, changes)
        if row is None:
            raise HTTPException(404, "Review not found")
        if row["topic"] is None:
            raise HTTPException(409, "This review has no decision yet.")
        return row

    def export_rows(run_id: str) -> list[dict]:
        rows = []
        for d in store.decisions(run_id):
            row = {"review_id": d["review_id"], "text": d["text"]}
            row.update({f: d[f] for f in DECISION_FIELDS})
            row.update({f"{f}_confidence": round(d["confidence"].get(f, 0.0), 4) for f in DECISION_FIELDS})
            row.update({"min_confidence": d["min_confidence"], "needs_review": d["needs_review"],
                        "reviewed": d["reviewed"], "corrected": d["corrected"], "model": d["model"],
                        "error": d["error"]})
            rows.append(row)
        return rows

    @app.get("/api/runs/{run_id}/export.csv")
    def export_csv(run_id: str):
        r = _run_or_404(run_id)
        rows = export_rows(run_id)
        buf = stdio.StringIO()
        if rows:
            w = csv.DictWriter(buf, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        fname = f"decisions-{r['id']}.csv"
        return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                                 headers={"Content-Disposition": f'attachment; filename="{fname}"'})

    @app.post("/api/runs/{run_id}/sheet")
    def push_to_sheet(run_id: str):
        _run_or_404(run_id)
        if not settings.sheet_id:
            raise HTTPException(422, "Google Sheets is not configured (SHEET_ID).")
        try:
            io.write_sheet(settings, export_rows(run_id))
        except Exception as e:
            raise HTTPException(502, f"Could not write Google Sheet: {e}") from e
        return {"ok": True, "tab": settings.sheet_output_tab}

    # ---- benchmarks ----
    def execute_benchmark(bid: str, specs: list[str], reviews: list[Review]):
        try:
            store.set_benchmark(bid, status="running")
            clfs = [factory(s) for s in specs]
            progress: dict = {c.name: {"done": 0, "total": len(reviews)} for c in clfs}

            def on_progress(name, done, total):
                progress[name] = {"done": done, "total": total}
                if done % 4 == 0 or done == total:
                    store.set_benchmark(bid, progress=progress)

            report, _ = benchmark_report(clfs, reviews, settings.confidence_threshold, workers=workers,
                                         on_progress=on_progress, session_id=f"benchmark · {bid}")
            store.set_benchmark(bid, status="done", report=report, progress=progress)
        except Exception as e:
            store.set_benchmark(bid, status="failed", error=f"{type(e).__name__}: {e}")

    @app.post("/api/benchmarks", status_code=201)
    def create_benchmark(body: BenchmarkCreate):
        reviews = parse_csv_text(body.csv_text) if body.csv_text else io.read_csv(SAMPLE)
        labeled = [r for r in reviews if r.has_labels]
        if not labeled:
            raise HTTPException(422, "Benchmark needs labeled reviews (topic, sentiment, defect, refund_request).")
        for spec in body.models:
            try:
                factory(spec)
            except (ValueError, RuntimeError) as e:
                raise HTTPException(422, str(e)) from e
        bid = store.create_benchmark(body.models)
        jobs.submit(execute_benchmark, bid, body.models, labeled)
        return store.get_benchmark(bid)

    @app.get("/api/benchmarks")
    def list_benchmarks():
        return store.list_benchmarks()

    @app.get("/api/benchmarks/{bid}")
    def get_benchmark(bid: str):
        b = store.get_benchmark(bid)
        if not b:
            raise HTTPException(404, "Benchmark not found")
        return b

    # ---- static SPA ----
    if WEB_DIST.exists():
        app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path.startswith("api/"):
                raise HTTPException(404)
            f = WEB_DIST / path
            return FileResponse(f if path and f.is_file() else WEB_DIST / "index.html")

    return app


app = None


def get_app() -> FastAPI:
    global app
    if app is None:
        app = create_app()
    return app
