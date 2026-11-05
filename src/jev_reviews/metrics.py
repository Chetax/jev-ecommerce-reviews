"""Accuracy, calibration, and cost metrics (pure Python, no numpy needed)."""

from __future__ import annotations

from statistics import mean

from .schema import DECISION_FIELDS, Decision, Review


def macro_f1(gold: list, pred: list) -> float:
    labels = sorted(set(gold) | set(pred), key=str)
    f1s = []
    for lab in labels:
        tp = sum(g == lab and p == lab for g, p in zip(gold, pred))
        fp = sum(g != lab and p == lab for g, p in zip(gold, pred))
        fn = sum(g == lab and p != lab for g, p in zip(gold, pred))
        if tp + fp + fn == 0:
            continue
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        f1s.append(2 * prec * rec / (prec + rec) if prec + rec else 0.0)
    return mean(f1s) if f1s else 0.0


def reliability_bins(confs: list[float], correct: list[bool], n_bins: int = 10) -> list[dict]:
    bins = []
    for b in range(n_bins):
        lo, hi = b / n_bins, (b + 1) / n_bins
        idx = [i for i, c in enumerate(confs) if (lo <= c < hi) or (b == n_bins - 1 and c == 1.0)]
        if not idx:
            bins.append({"lo": lo, "hi": hi, "count": 0, "avg_confidence": None, "accuracy": None})
            continue
        bins.append({
            "lo": lo,
            "hi": hi,
            "count": len(idx),
            "avg_confidence": mean(confs[i] for i in idx),
            "accuracy": mean(1.0 if correct[i] else 0.0 for i in idx),
        })
    return bins


def ece(confs: list[float], correct: list[bool], n_bins: int = 10) -> float:
    """Expected Calibration Error: weighted |accuracy - confidence| over bins."""
    n = len(confs)
    if n == 0:
        return 0.0
    return sum(
        b["count"] / n * abs(b["accuracy"] - b["avg_confidence"])
        for b in reliability_bins(confs, correct, n_bins)
        if b["count"]
    )


def brier(confs: list[float], correct: list[bool]) -> float:
    if not confs:
        return 0.0
    return mean((c - (1.0 if ok else 0.0)) ** 2 for c, ok in zip(confs, correct))


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def selective(decisions: list[Decision], gold: dict[str, Review], threshold: float) -> dict:
    """Auto-accept decisions whose min confidence >= threshold; report coverage and accuracy."""
    accepted = [d for d in decisions if d.min_confidence() >= threshold]
    if not decisions:
        return {"threshold": threshold, "coverage": 0.0, "all_fields_accuracy": None}
    acc = None
    if accepted:
        acc = mean(
            1.0 if all(getattr(d, f) == getattr(gold[d.review_id], f) for f in DECISION_FIELDS) else 0.0
            for d in accepted
        )
    return {"threshold": threshold, "coverage": len(accepted) / len(decisions), "all_fields_accuracy": acc}


def evaluate(decisions: list[Decision], reviews: list[Review], thresholds=(0.5, 0.7, 0.8, 0.9, 0.95)) -> dict:
    gold = {r.review_id: r for r in reviews}
    decisions = [d for d in decisions if d.review_id in gold and gold[d.review_id].has_labels]
    n = len(decisions)
    per_field = {}
    all_confs, all_correct = [], []
    for f in DECISION_FIELDS:
        g = [getattr(gold[d.review_id], f) for d in decisions]
        p = [getattr(d, f) for d in decisions]
        correct = [a == b for a, b in zip(g, p)]
        confs = [d.confidence.get(f, 0.0) for d in decisions]
        all_confs += confs
        all_correct += correct
        per_field[f] = {
            "accuracy": mean(1.0 if c else 0.0 for c in correct) if n else 0.0,
            "macro_f1": macro_f1(g, p),
            "ece": ece(confs, correct),
            "brier": brier(confs, correct),
            "mean_confidence": mean(confs) if confs else 0.0,
            "reliability": reliability_bins(confs, correct),
        }
    latencies = [d.latency_ms for d in decisions]
    total_cost = sum(d.cost_usd for d in decisions)
    return {
        "n": n,
        "all_fields_accuracy": mean(
            1.0 if all(getattr(d, f) == getattr(gold[d.review_id], f) for f in DECISION_FIELDS) else 0.0
            for d in decisions
        ) if n else 0.0,
        "per_field": per_field,
        "overall_ece": ece(all_confs, all_correct),
        "overall_brier": brier(all_confs, all_correct),
        "overall_reliability": reliability_bins(all_confs, all_correct),
        "selective": [selective(decisions, gold, t) for t in thresholds],
        "latency_ms": {
            "p50": percentile(latencies, 0.5),
            "p95": percentile(latencies, 0.95),
            "mean": mean(latencies) if latencies else 0.0,
        },
        "cost": {
            "total_usd": total_cost,
            "per_1k_reviews_usd": total_cost / n * 1000 if n else 0.0,
            "input_tokens": sum(d.input_tokens for d in decisions),
            "output_tokens": sum(d.output_tokens for d in decisions),
        },
    }
