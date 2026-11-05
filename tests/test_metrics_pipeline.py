from pathlib import Path

import pytest

from jev_reviews import io
from jev_reviews.cli import summarize
from jev_reviews.metrics import brier, ece, evaluate, macro_f1, reliability_bins
from jev_reviews.pipeline import benchmark, run
from jev_reviews.schema import Decision, Review

DATA = Path(__file__).resolve().parents[1] / "data" / "sample_reviews.csv"


def test_ece_perfectly_calibrated_is_zero():
    confs = [0.75] * 4
    assert ece(confs, [True, True, True, False]) == pytest.approx(0.0)


def test_ece_overconfident():
    assert ece([1.0, 1.0], [True, False]) == pytest.approx(0.5)


def test_brier():
    assert brier([1.0, 0.0], [True, False]) == 0.0
    assert brier([0.5], [True]) == pytest.approx(0.25)


def test_reliability_bins_include_one():
    bins = reliability_bins([1.0, 0.05], [True, False])
    assert bins[-1]["count"] == 1 and bins[0]["count"] == 1


def test_macro_f1():
    assert macro_f1(["a", "b"], ["a", "b"]) == 1.0
    assert macro_f1(["a", "a"], ["b", "b"]) == 0.0


def test_sample_dataset_loads_with_labels():
    reviews = io.read_csv(DATA)
    assert len(reviews) >= 40 and all(r.has_labels for r in reviews)


class OracleClassifier:
    """Copies gold labels; wrong (and confident) on every 4th review's topic."""
    name = "oracle"

    def classify(self, r: Review) -> Decision:
        wrong = int(r.review_id[1:]) % 4 == 0
        return Decision(r.review_id, "other" if wrong and r.topic != "other" else r.topic, r.sentiment,
                        r.defect, r.refund_request,
                        {"topic": 0.95, "sentiment": 0.9, "defect": 0.9, "refund_request": 0.9},
                        model="oracle", latency_ms=10, input_tokens=100, cost_usd=0.001)


class Broken:
    name = "broken"

    def classify(self, r):
        raise RuntimeError("boom")


def test_evaluate_and_benchmark(tmp_path):
    reviews = io.read_csv(DATA)
    report = benchmark([OracleClassifier()], reviews, tmp_path, threshold=0.8, workers=4)
    m = report["models"]["oracle"]["metrics"]
    assert m["n"] == len(reviews)
    assert m["per_field"]["sentiment"]["accuracy"] == 1.0
    assert m["per_field"]["topic"]["accuracy"] < 1.0
    assert m["cost"]["per_1k_reviews_usd"] == pytest.approx(1.0)
    assert (tmp_path / "benchmark.json").exists() and (tmp_path / "decisions_oracle.csv").exists()
    assert "all-fields accuracy" in summarize(report)


def test_run_collects_errors():
    decisions, errors = run(Broken(), [Review("R1", "x")], progress=False)
    assert decisions == [] and errors[0]["review_id"] == "R1"


def test_needs_review_flag():
    d = Decision("R1", "other", "neutral", False, False,
                 {"topic": 0.6, "sentiment": 0.99, "defect": 0.99, "refund_request": 0.99}, "m")
    row = d.to_row(0.8)
    assert row["needs_review"] is True and row["min_confidence"] == 0.6
