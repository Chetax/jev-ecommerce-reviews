"""Client for TypeSafe's Jev decision model (POST {TYPESAFE_BASE_URL}/systemone).

Jev is a paid hosted API (not open weights, not on Bedrock). The request/response
shapes here follow public write-ups; check `Decision.raw` on your first real call.
"""

from __future__ import annotations

import json

from .config import Settings
from .http import post_json
from .schema import QUESTIONS, SENTIMENTS, TOPICS, Decision, Review


def estimate_tokens(text: str) -> int:
    """Rough token estimate (~4 chars/token) used when the API reports no usage."""
    return max(1, round(len(text) / 4))


def _choice(ans: dict) -> tuple[str, float]:
    value = ans["choice"]
    probs = ans.get("probabilities") or {}
    conf = ans.get("confidence")
    if conf is None:
        conf = probs.get(value, 0.0)
    return value, float(conf)


def _score_to_label(ans: dict, labels: list[str]) -> tuple[str, float]:
    """Map a Jev `score` answer onto one of our ordered labels.

    Prefers per-label probabilities (argmax); otherwise uses the legend to find the
    label nearest the fractional score; otherwise assumes the score spans 0..1.
    """
    lower = {l.lower(): l for l in labels}
    probs = ans.get("probabilities") or {}
    legend = ans.get("legend") or {}

    # probabilities keyed by label name
    named = {k.lower(): float(v) for k, v in probs.items() if str(k).lower() in lower}
    if named:
        best = max(named, key=named.get)
        conf = ans.get("confidence", named[best])
        return best, float(conf)

    score = float(ans["score"])
    if legend:
        points = {float(k): str(v).lower() for k, v in legend.items()}
        nearest = min(points, key=lambda p: abs(p - score))
        label = points[nearest]
        if probs:  # probabilities keyed by legend value
            p = {float(k): float(v) for k, v in probs.items()}
            conf = ans.get("confidence", p.get(nearest, 0.0))
        else:
            conf = ans.get("confidence", 0.0)
        return label, float(conf)

    idx = min(len(labels) - 1, max(0, round(score * (len(labels) - 1))))
    return labels[idx].lower(), float(ans.get("confidence", 0.0))


def _noul(ans: dict) -> tuple[bool, float]:
    p = float(ans["noul"])
    value = p >= 0.5
    return value, (p if value else 1 - p)


def parse_answers(review_id: str, answers: dict, model: str) -> Decision:
    topic, topic_c = _choice(answers["topic"])
    if topic not in TOPICS:
        raise ValueError(f"Jev returned unknown topic {topic!r}")
    sentiment, sent_c = _score_to_label(answers["sentiment"], QUESTIONS["sentiment"]["criteria"])
    if sentiment not in SENTIMENTS:
        raise ValueError(f"Could not map sentiment answer {answers['sentiment']!r}")
    defect, defect_c = _noul(answers["defect"])
    refund, refund_c = _noul(answers["refund_request"])
    return Decision(
        review_id=review_id,
        topic=topic,
        sentiment=sentiment,
        defect=defect,
        refund_request=refund,
        confidence={"topic": topic_c, "sentiment": sent_c, "defect": defect_c, "refund_request": refund_c},
        model=model,
        raw=answers,
    )


class JevClassifier:
    name = "jev"

    def __init__(self, settings: Settings, session=None):
        self.settings = settings
        self.session = session

    def build_payload(self, review: Review) -> dict:
        return {"model": self.settings.jev_model, "state": review.text, "questions": QUESTIONS}

    def classify(self, review: Review) -> Decision:
        payload = self.build_payload(review)
        data, latency_ms = post_json(
            f"{self.settings.typesafe_base_url}/systemone",
            self.settings.require_typesafe_key(),
            payload,
            session=self.session,
        )
        decision = parse_answers(review.review_id, data["answers"], self.settings.jev_model)
        usage = data.get("usage") or {}
        in_tok = usage.get("input_tokens") or usage.get("prompt_tokens") or estimate_tokens(
            review.text + json.dumps(QUESTIONS)
        )
        decision.latency_ms = latency_ms
        decision.input_tokens = int(in_tok)
        decision.output_tokens = 0  # Jev output is not billed
        decision.cost_usd = in_tok / 1e6 * self.settings.jev_input_price_per_m
        return decision
