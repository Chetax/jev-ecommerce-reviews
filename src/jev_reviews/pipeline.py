"""Run a classifier over reviews concurrently, collecting decisions and errors."""

from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Protocol

from .metrics import evaluate
from .schema import Decision, Review
from .tracing import classify_traced, setup_tracing


class Classifier(Protocol):
    name: str

    def classify(self, review: Review) -> Decision: ...


def run(classifier: Classifier, reviews: list[Review], workers: int = 8, progress: bool = True,
        on_result: Callable[[Review, Decision | None, str | None], None] | None = None,
        session_id: str | None = None, threshold: float | None = None,
        ) -> tuple[list[Decision], list[dict]]:
    setup_tracing()
    decisions: list[Decision] = []
    errors: list[dict] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(classify_traced, classifier, r, session_id, threshold): r for r in reviews}
        for i, fut in enumerate(as_completed(futures), start=1):
            r = futures[fut]
            try:
                d = fut.result()
                decisions.append(d)
                if on_result:
                    on_result(r, d, None)
            except Exception as e:  # keep going; report at the end
                msg = f"{type(e).__name__}: {e}"
                errors.append({"review_id": r.review_id, "error": msg})
                if on_result:
                    on_result(r, None, msg)
            if progress:
                print(f"\r[{classifier.name}] {i}/{len(reviews)}", end="", file=sys.stderr)
    if progress:
        print(file=sys.stderr)
    order = {r.review_id: i for i, r in enumerate(reviews)}
    decisions.sort(key=lambda d: order.get(d.review_id, 0))
    return decisions, errors


def benchmark_report(classifiers: list[Classifier], reviews: list[Review], threshold: float,
                     workers: int = 8, on_progress: Callable[[str, int, int], None] | None = None,
                     session_id: str | None = None,
                     ) -> tuple[dict, dict[str, list[Decision]]]:
    """Run each classifier over the labeled reviews and return (report, decisions by classifier)."""
    labeled = [r for r in reviews if r.has_labels]
    if not labeled:
        raise ValueError("Benchmark needs labeled reviews (topic, sentiment, defect, refund_request columns).")
    generated_at = datetime.now(timezone.utc).isoformat()
    session_id = session_id or f"benchmark {generated_at[:19]}"
    report = {
        "generated_at": generated_at,
        "n_reviews": len(labeled),
        "threshold": threshold,
        "models": {},
    }
    all_decisions: dict[str, list[Decision]] = {}
    for clf in classifiers:
        count = {"n": 0}

        def tick(_r, _d, _e, name=clf.name):
            count["n"] += 1
            if on_progress:
                on_progress(name, count["n"], len(labeled))

        decisions, errors = run(clf, labeled, workers=workers, progress=on_progress is None, on_result=tick,
                                session_id=f"{session_id} · {clf.name}", threshold=threshold)
        model_id = decisions[0].model if decisions else getattr(clf, "model_id", clf.name)
        report["models"][clf.name] = {"model": model_id, "errors": errors, "metrics": evaluate(decisions, labeled)}
        all_decisions[clf.name] = decisions
    return report, all_decisions


def benchmark(classifiers: list[Classifier], reviews: list[Review], out_dir: str | Path,
              threshold: float, workers: int = 8) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    report, all_decisions = benchmark_report(classifiers, reviews, threshold, workers=workers)
    for name, decisions in all_decisions.items():
        _write_rows(out / f"decisions_{name}.csv", [d.to_row(threshold) for d in decisions])
    (out / "benchmark.json").write_text(json.dumps(report, indent=2))
    return report


def _write_rows(path: Path, rows: list[dict]) -> None:
    from .io import write_csv

    write_csv(path, rows)
