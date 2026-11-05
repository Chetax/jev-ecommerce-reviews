"""The typed decisions we ask about every review, and the result containers."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

TOPICS: dict[str, str] = {
    "product_quality": "The product itself: build quality, durability, performance, or it being broken/faulty.",
    "sizing_fit": "Size, fit, or dimensions not matching expectations or the size chart.",
    "shipping_delivery": "Shipping speed, delays, tracking, courier problems, or lost parcels.",
    "packaging": "Packaging condition or quality, e.g. crushed box, poor protection.",
    "wrong_item": "Received a different item, colour, variant, or missing parts versus what was ordered.",
    "customer_service": "Interactions with support, returns process, or seller responsiveness.",
    "price_value": "Price, value for money, discounts, or being overcharged.",
    "other": "None of the above, or a general comment with no specific topic.",
}

SENTIMENTS: list[str] = ["negative", "neutral", "positive"]

QUESTIONS: dict[str, dict] = {
    "topic": {
        "type": "choice",
        "instructions": "What is the primary topic of this customer review?",
        "criteria": TOPICS,
    },
    "sentiment": {
        "type": "score",
        "instructions": "What is the overall sentiment of this customer review?",
        "criteria": ["Negative", "Neutral", "Positive"],
    },
    "defect": {
        "type": "noul",
        "instructions": "Does the review report a product defect, malfunction, or damage on arrival?",
    },
    "refund_request": {
        "type": "noul",
        "instructions": "Is the customer asking for, or saying they will seek, a refund, return, or replacement?",
    },
}

DECISION_FIELDS = ["topic", "sentiment", "defect", "refund_request"]


@dataclass
class Review:
    review_id: str
    text: str
    # Optional gold labels (used for benchmarking)
    topic: str | None = None
    sentiment: str | None = None
    defect: bool | None = None
    refund_request: bool | None = None

    @property
    def has_labels(self) -> bool:
        return all(getattr(self, f) is not None for f in DECISION_FIELDS)


@dataclass
class Decision:
    """A classifier's typed decision for one review.

    `confidence` holds, per field, the probability the model assigns to the
    value it chose (so it is directly comparable across models for calibration).
    """

    review_id: str
    topic: str
    sentiment: str
    defect: bool
    refund_request: bool
    confidence: dict[str, float]
    model: str
    latency_ms: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    raw: dict = field(default_factory=dict, repr=False)

    def min_confidence(self) -> float:
        return min(self.confidence.values()) if self.confidence else 0.0

    def needs_review(self, threshold: float) -> bool:
        return self.min_confidence() < threshold

    def to_row(self, threshold: float) -> dict:
        d = asdict(self)
        d.pop("raw")
        conf = d.pop("confidence")
        for k in DECISION_FIELDS:
            d[f"{k}_confidence"] = round(conf.get(k, 0.0), 4)
        d["min_confidence"] = round(self.min_confidence(), 4)
        d["needs_review"] = self.needs_review(threshold)
        return d


def parse_bool(value) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    s = str(value).strip().lower()
    if s in {"true", "yes", "y", "1"}:
        return True
    if s in {"false", "no", "n", "0"}:
        return False
    raise ValueError(f"Not a boolean: {value!r}")
