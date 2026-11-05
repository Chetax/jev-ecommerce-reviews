"""Optional tracing of every classification to Arize Phoenix (or any OpenTelemetry backend).

Enable it by setting PHOENIX_COLLECTOR_ENDPOINT (e.g. http://localhost:6006) and installing
the `observe` extra. Each review becomes one span with:
  - input: the review text; output: the typed decision (JSON)
  - model, token counts, cost, latency, per-field confidence
  - session = the run, so a whole run groups together in Phoenix
  - when gold labels exist (benchmarks / evals): which fields were wrong, tagged `incorrect`
The Claude SDK's own HTTP span nests under it, so retries and API errors show up too.

With no endpoint set this is a no-op: OpenTelemetry's default tracer records nothing.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from typing import TYPE_CHECKING

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from .schema import DECISION_FIELDS, Decision, Review

if TYPE_CHECKING:
    from .pipeline import Classifier

log = logging.getLogger(__name__)
tracer = trace.get_tracer("jev_reviews")  # proxy: picks up the provider once one is registered

_lock = threading.Lock()
_state: dict[str, bool] = {}


def setup_tracing() -> bool:
    """Register the Phoenix exporter once per process. Returns whether tracing is on."""
    with _lock:
        if "enabled" in _state:
            return _state["enabled"]
        enabled = False
        if os.getenv("PHOENIX_COLLECTOR_ENDPOINT"):
            try:
                from phoenix.otel import register
            except ImportError:
                log.warning("PHOENIX_COLLECTOR_ENDPOINT is set but tracing packages are missing; "
                            "run: pip install -e '.[observe]'")
            else:
                register(project_name=os.getenv("PHOENIX_PROJECT_NAME", "jev-reviews"),
                         batch=True, verbose=False)
                enabled = True
        _state["enabled"] = enabled
        return enabled


def wrong_fields(decision: Decision, review: Review) -> list[str]:
    """Fields where the decision disagrees with the review's gold labels (empty if unlabeled)."""
    if not review.has_labels:
        return []
    return [f for f in DECISION_FIELDS if getattr(decision, f) != getattr(review, f)]


def classify_traced(classifier: "Classifier", review: Review, session_id: str | None = None,
                    threshold: float | None = None) -> Decision:
    with tracer.start_as_current_span(
        "classify_review",
        attributes={
            "openinference.span.kind": "LLM",
            "input.value": review.text,
            "input.mime_type": "text/plain",
            "classifier": classifier.name,
            **({"session.id": session_id} if session_id else {}),
        },
    ) as span:
        try:
            d = classifier.classify(review)
        except Exception as e:
            span.record_exception(e)
            span.set_status(Status(StatusCode.ERROR, f"{type(e).__name__}: {e}"))
            span.set_attribute("tag.tags", ["error"])
            raise
        if span.is_recording():
            span.set_attributes(_decision_attributes(d, review, threshold))
        return d


def _decision_attributes(d: Decision, review: Review, threshold: float | None) -> dict:
    output = {f: getattr(d, f) for f in DECISION_FIELDS}
    meta: dict = {"review_id": review.review_id, "confidence": d.confidence,
                  "min_confidence": round(d.min_confidence(), 4), "latency_ms": round(d.latency_ms)}
    tags: list[str] = []
    if threshold is not None:
        meta["needs_review"] = d.needs_review(threshold)
        if meta["needs_review"]:
            tags.append("needs_review")
    if review.has_labels:
        wrong = wrong_fields(d, review)
        meta["gold"] = {f: getattr(review, f) for f in DECISION_FIELDS}
        meta["wrong_fields"] = wrong
        meta["all_correct"] = not wrong
        tags.append("incorrect" if wrong else "correct")
    attrs = {
        "output.value": json.dumps(output),
        "output.mime_type": "application/json",
        "llm.model_name": d.model,
        "llm.token_count.prompt": d.input_tokens,
        "llm.token_count.completion": d.output_tokens,
        "llm.token_count.total": d.input_tokens + d.output_tokens,
        "llm.cost.total": d.cost_usd,
        "metadata": json.dumps(meta),
    }
    if tags:
        attrs["tag.tags"] = tags
    return attrs
