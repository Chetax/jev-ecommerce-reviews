"""Evaluation gate: run a classifier on labeled data and fail loudly if quality regresses.

  jev-reviews eval                       # exits 1 if any check fails (use it in CI / before deploys)

Datasets: the 48 sample reviews plus `data/eval_edge_cases.csv` (prompt injection, sarcasm,
non-English, spam, ...). Edge cases marked `must_pass` must be either fully correct or flagged
for human review. A confident wrong answer on one of them is the failure that matters.

Thresholds live in `evals/gates.json`; anything left out uses DEFAULT_GATES.
"""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import io
from .metrics import evaluate
from .pipeline import Classifier, run
from .schema import DECISION_FIELDS, Review, parse_bool
from .tracing import wrong_fields

DEFAULT_DATASETS = ["data/sample_reviews.csv", "data/eval_edge_cases.csv"]
DEFAULT_GATES_FILE = "evals/gates.json"
DEFAULT_GATES: dict = {
    "max_error_rate": 0.0,             # share of reviews where the API call failed
    "min_all_fields_accuracy": 0.75,   # all four fields right
    "min_field_accuracy": {"topic": 0.85, "sentiment": 0.85, "defect": 0.85, "refund_request": 0.85},
    "max_ece": 0.15,                   # calibration error: does 0.9 confidence mean ~90% right?
    "max_confident_wrong_rate": 0.05,  # wrong answers among auto-accepted (not flagged) reviews
    "max_must_pass_failures": 0,       # must_pass cases that were wrong AND not flagged
    "max_cost_per_1k_usd": None,       # set a number to cap spend
    "max_latency_p95_ms": None,
}


@dataclass
class Check:
    name: str
    value: float | int
    limit: float | int
    op: str  # "<=" or ">="
    ok: bool


@dataclass
class Dataset:
    reviews: list[Review]
    must_pass: set[str]
    why: dict[str, str]


def load_dataset(paths: list[str]) -> Dataset:
    reviews: list[Review] = []
    must_pass: set[str] = set()
    why: dict[str, str] = {}
    for path in paths:
        rows = io.read_csv(path)
        with open(path, newline="", encoding="utf-8") as f:
            extra = {r.get("review_id", ""): r for r in csv.DictReader(f)}
        for r in rows:
            e = extra.get(r.review_id, {})
            if parse_bool(e.get("must_pass")):
                must_pass.add(r.review_id)
            if e.get("why"):
                why[r.review_id] = e["why"]
        reviews += rows
    ids = [r.review_id for r in reviews]
    if len(ids) != len(set(ids)):
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        raise ValueError(f"Duplicate review_id across eval datasets: {dupes[:5]}")
    unlabeled = [r.review_id for r in reviews if not r.has_labels]
    if unlabeled:
        raise ValueError(f"Eval data needs gold labels; unlabeled rows: {unlabeled[:5]}")
    return Dataset(reviews, must_pass, why)


def load_gates(path: str | Path | None) -> dict:
    gates = json.loads(json.dumps(DEFAULT_GATES))
    if path and Path(path).exists():
        user = json.loads(Path(path).read_text())
        user.pop("_comment", None)
        for k, v in user.items():
            if isinstance(v, dict) and isinstance(gates.get(k), dict):
                gates[k].update(v)
            else:
                gates[k] = v
    return gates


def run_eval(classifier: Classifier, data: Dataset, threshold: float, gates: dict,
             workers: int = 8, progress: bool = True) -> dict:
    started = datetime.now(timezone.utc).isoformat()
    decisions, errors = run(classifier, data.reviews, workers=workers, progress=progress,
                            session_id=f"eval · {classifier.name} · {started[:19]}", threshold=threshold)
    m = evaluate(decisions, data.reviews, thresholds=(threshold,))
    gold = {r.review_id: r for r in data.reviews}
    by_id = {d.review_id: d for d in decisions}
    n = len(data.reviews)

    failures = []
    for d in decisions:
        wrong = wrong_fields(d, gold[d.review_id])
        if wrong:
            failures.append({
                "review_id": d.review_id,
                "text": gold[d.review_id].text,
                "wrong": {f: {"got": getattr(d, f), "expected": getattr(gold[d.review_id], f),
                              "confidence": round(d.confidence.get(f, 0.0), 3)} for f in wrong},
                "flagged_for_review": d.needs_review(threshold),
                "must_pass": d.review_id in data.must_pass,
                "why": data.why.get(d.review_id, ""),
            })
    accepted = [d for d in decisions if not d.needs_review(threshold)]
    confident_wrong = [f for f in failures if not f["flagged_for_review"]]
    errored = {e["review_id"] for e in errors}
    must_pass_failed = sorted(
        {f["review_id"] for f in confident_wrong if f["must_pass"]} | (errored & data.must_pass))

    checks: list[Check] = []

    def check(name, value, limit, op):
        if limit is None:
            return
        ok = value <= limit if op == "<=" else value >= limit
        checks.append(Check(name, value, limit, op, ok))

    check("error rate", len(errors) / n if n else 0.0, gates["max_error_rate"], "<=")
    if decisions:
        check("all-fields accuracy", m["all_fields_accuracy"], gates["min_all_fields_accuracy"], ">=")
        for f in DECISION_FIELDS:
            check(f"{f} accuracy", m["per_field"][f]["accuracy"], gates["min_field_accuracy"].get(f), ">=")
        check("calibration error (ECE)", m["overall_ece"], gates["max_ece"], "<=")
        check("confident-wrong rate", len(confident_wrong) / len(accepted) if accepted else 0.0,
              gates["max_confident_wrong_rate"], "<=")
        check("cost per 1k reviews (USD)", m["cost"]["per_1k_reviews_usd"], gates["max_cost_per_1k_usd"], "<=")
        check("latency p95 (ms)", m["latency_ms"]["p95"], gates["max_latency_p95_ms"], "<=")
    check("must-pass failures", len(must_pass_failed), gates["max_must_pass_failures"], "<=")

    return {
        "passed": bool(decisions) and all(c.ok for c in checks),
        "classifier": classifier.name,
        "started_at": started,
        "n_reviews": n,
        "n_must_pass": len(data.must_pass),
        "threshold": threshold,
        "auto_accepted": len(accepted),
        "checks": [asdict(c) for c in checks],
        "must_pass_failed": must_pass_failed,
        "failures": failures,
        "errors": errors,
        "metrics": m,
    }


def _fmt(name: str, v: float | int) -> str:
    if "accuracy" in name or "rate" in name:
        return f"{v:.1%}"
    if "USD" in name:
        return f"${v:.4f}"
    if "ms" in name or "failures" in name:
        return f"{v:.0f}"
    return f"{v:.3f}"


def format_report(result: dict) -> str:
    lines = [
        f"Eval: {result['classifier']} on {result['n_reviews']} labeled reviews "
        f"({result['n_must_pass']} must-pass edge cases), threshold {result['threshold']}",
        f"Auto-accepted {result['auto_accepted']}/{result['n_reviews']}, the rest flagged for human review.",
        "",
        f"  {'check':<28}{'value':>10}{'limit':>14}",
    ]
    for c in result["checks"]:
        mark = "PASS" if c["ok"] else "FAIL"
        lines.append(f"  {c['name']:<28}{_fmt(c['name'], c['value']):>10}"
                     f"{c['op']:>4} {_fmt(c['name'], c['limit']):>9}   {mark}")
    if result["errors"]:
        lines += ["", f"API errors ({len(result['errors'])}):"]
        lines += [f"  {e['review_id']}: {e['error'][:160]}" for e in result["errors"][:5]]
    bad = sorted(result["failures"], key=lambda f: (f["flagged_for_review"], not f["must_pass"]))
    if bad:
        lines += ["", f"Wrong answers ({len(bad)}; confident ones first):"]
        for f in bad[:15]:
            state = "flagged" if f["flagged_for_review"] else "CONFIDENT"
            star = " [must-pass]" if f["must_pass"] else ""
            diffs = ", ".join(f"{k}: got {v['got']} want {v['expected']} ({v['confidence']:.2f})"
                              for k, v in f["wrong"].items())
            text = f["text"] if len(f["text"]) <= 90 else f["text"][:87] + "..."
            lines.append(f"  {f['review_id']} {state}{star}: {diffs}")
            lines.append(f"      \"{text}\"")
    lines += ["", "RESULT: PASS" if result["passed"] else "RESULT: FAIL"]
    return "\n".join(lines)
