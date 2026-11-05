import json
from pathlib import Path

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from jev_reviews import tracing
from jev_reviews.evals import DEFAULT_GATES, format_report, load_dataset, load_gates, run_eval
from jev_reviews.pipeline import run
from jev_reviews.schema import Decision, Review

ROOT = Path(__file__).resolve().parents[1]
DATASETS = [str(ROOT / "data" / "sample_reviews.csv"), str(ROOT / "data" / "eval_edge_cases.csv")]
HIGH = {"topic": 0.97, "sentiment": 0.97, "defect": 0.97, "refund_request": 0.97}


class Oracle:
    """Answers with the gold labels, except for overrides {review_id: (field, value, confidence)}."""

    name = "oracle"

    def __init__(self, gold: dict[str, Review], overrides=None, fail=()):
        self.gold, self.overrides, self.fail = gold, overrides or {}, set(fail)

    def classify(self, review: Review) -> Decision:
        if review.review_id in self.fail:
            raise RuntimeError("boom")
        g = self.gold[review.review_id]
        d = Decision(review.review_id, g.topic, g.sentiment, g.defect, g.refund_request, dict(HIGH),
                     model="oracle", latency_ms=100, input_tokens=200, output_tokens=50, cost_usd=0.001)
        if review.review_id in self.overrides:
            field, value, conf = self.overrides[review.review_id]
            setattr(d, field, value)
            d.confidence[field] = conf
        return d


@pytest.fixture(scope="module")
def data():
    return load_dataset(DATASETS)


def oracle(data, **kw):
    return Oracle({r.review_id: r for r in data.reviews}, **kw)


def test_datasets_load_with_labels_and_must_pass(data):
    assert len(data.reviews) == 64
    assert "E001" in data.must_pass and "E010" not in data.must_pass
    assert all(r.has_labels for r in data.reviews)


def test_perfect_classifier_passes(data):
    result = run_eval(oracle(data), data, 0.8, load_gates(None), progress=False)
    assert result["passed"], format_report(result)
    assert result["failures"] == [] and result["must_pass_failed"] == []


def test_confident_wrong_on_must_pass_fails(data):
    # the injection worked: sentiment flipped to positive, and the model is sure of it
    clf = oracle(data, overrides={"E001": ("sentiment", "positive", 0.99)})
    result = run_eval(clf, data, 0.8, load_gates(None), progress=False)
    assert not result["passed"]
    assert result["must_pass_failed"] == ["E001"]
    report = format_report(result)
    assert "E001 CONFIDENT [must-pass]" in report and "RESULT: FAIL" in report


def test_wrong_but_flagged_must_pass_is_acceptable(data):
    clf = oracle(data, overrides={"E001": ("sentiment", "positive", 0.4)})
    result = run_eval(clf, data, 0.8, load_gates(None), progress=False)
    assert result["must_pass_failed"] == []
    assert {c["name"]: c["ok"] for c in result["checks"]}["must-pass failures"]


def test_api_errors_fail_the_gate(data):
    result = run_eval(oracle(data, fail={"R001"}), data, 0.8, load_gates(None), progress=False)
    checks = {c["name"]: c["ok"] for c in result["checks"]}
    assert not result["passed"] and not checks["error rate"]


def test_gates_file_overrides_defaults(tmp_path):
    f = tmp_path / "g.json"
    f.write_text(json.dumps({"_comment": "x", "max_ece": 0.5, "min_field_accuracy": {"topic": 0.5}}))
    g = load_gates(f)
    assert g["max_ece"] == 0.5 and g["min_field_accuracy"]["topic"] == 0.5
    assert g["min_field_accuracy"]["sentiment"] == DEFAULT_GATES["min_field_accuracy"]["sentiment"]


def test_repo_gates_file_is_valid():
    g = load_gates(ROOT / "evals" / "gates.json")
    assert set(g) == set(DEFAULT_GATES)


def test_spans_record_decision_and_correctness(data, monkeypatch):
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(tracing, "tracer", provider.get_tracer("test"))

    reviews = [r for r in data.reviews if r.review_id in {"R001", "E001", "E003"}]
    clf = oracle(data, overrides={"E001": ("sentiment", "positive", 0.99)}, fail={"E003"})
    run(clf, reviews, workers=2, progress=False, session_id="test-run", threshold=0.8)

    spans = {json.loads(s.attributes.get("metadata", "{}")).get("review_id", "error"): s
             for s in exporter.get_finished_spans()}
    ok, bad = spans["R001"], spans["E001"]
    assert ok.attributes["openinference.span.kind"] == "LLM"
    assert ok.attributes["session.id"] == "test-run"
    assert json.loads(ok.attributes["output.value"])["topic"] == "product_quality"
    assert ok.attributes["llm.token_count.total"] == 250
    assert "correct" in ok.attributes["tag.tags"]
    assert json.loads(bad.attributes["metadata"])["wrong_fields"] == ["sentiment"]
    assert "incorrect" in bad.attributes["tag.tags"]
    err = spans["error"]
    assert err.status.status_code.name == "ERROR" and "error" in err.attributes["tag.tags"]
