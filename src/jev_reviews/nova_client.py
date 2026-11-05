"""Amazon Nova (and other non-Claude Bedrock models) via the Bedrock Converse API.

Typed output comes from a forced tool call whose input schema is ReviewDecision, so the
answer is validated by the same Pydantic model the Claude path uses. Auth is the normal
boto3 chain (aws configure / AWS_PROFILE / roles) or AWS_BEARER_TOKEN_BEDROCK.
"""

from __future__ import annotations

import time

from .bedrock_client import SYSTEM_PROMPT, ReviewDecision, to_decision
from .config import Settings
from .schema import Decision, Review

TOOL_NAME = "record_decision"

# On-demand USD per 1M tokens (input, output), us-east-1. Check https://aws.amazon.com/bedrock/pricing/
NOVA_PRICES: dict[str, tuple[float, float]] = {
    "nova-micro": (0.035, 0.14),
    "nova-lite": (0.06, 0.24),
    "nova-pro": (0.80, 3.20),
    "nova-2-lite": (0.30, 2.50),
}


def is_claude(model_id: str) -> bool:
    return "anthropic." in model_id


def short_name(model_id: str) -> str:
    """us.amazon.nova-2-lite-v1:0 -> nova-2-lite; anthropic.claude-opus-5-5 -> claude-opus-5-5."""
    name = model_id.split("anthropic.")[-1].split("amazon.")[-1]
    return name.removesuffix(":0").removesuffix("-v1")


def price_for(model_id: str, s: Settings) -> tuple[float, float]:
    for key in sorted(NOVA_PRICES, key=len, reverse=True):  # "nova-2-lite" before "nova-lite"
        if key in model_id:
            return NOVA_PRICES[key]
    return s.bedrock_input_price_per_m, s.bedrock_output_price_per_m


def _inline_refs(schema: dict) -> dict:
    """Converse tool schemas can't rely on $ref/$defs; inline them."""
    defs = schema.get("$defs", {})

    def walk(node):
        if isinstance(node, dict):
            if "$ref" in node:
                return walk(defs[node["$ref"].split("/")[-1]])
            return {k: walk(v) for k, v in node.items() if k not in ("$defs", "title")}
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    return walk(schema)


TOOL_SCHEMA = _inline_refs(ReviewDecision.model_json_schema())


def make_runtime_client(s: Settings):
    import boto3
    from botocore.config import Config

    return boto3.client("bedrock-runtime", region_name=s.aws_region,
                        config=Config(retries={"max_attempts": 6, "mode": "adaptive"}, read_timeout=120))


class ConverseClassifier:
    def __init__(self, settings: Settings, model_id: str | None = None, client=None, name: str | None = None):
        self.settings = settings
        self.model_id = model_id or settings.bedrock_model_id
        self.client = client or make_runtime_client(settings)
        self.name = name or short_name(self.model_id)
        self.input_price, self.output_price = price_for(self.model_id, settings)

    def classify(self, review: Review) -> Decision:
        start = time.perf_counter()
        response = self.client.converse(
            modelId=self.model_id,
            system=[{"text": SYSTEM_PROMPT + f"\nAlways answer by calling the {TOOL_NAME} tool."}],
            messages=[{"role": "user", "content": [{"text": f"<review>\n{review.text}\n</review>"}]}],
            toolConfig={
                "tools": [{"toolSpec": {
                    "name": TOOL_NAME,
                    "description": "Record the typed decision and per-field confidence for this review.",
                    "inputSchema": {"json": TOOL_SCHEMA},
                }}],
                "toolChoice": {"tool": {"name": TOOL_NAME}},
            },
            inferenceConfig={"maxTokens": 1024, "temperature": 0},
        )
        latency_ms = (time.perf_counter() - start) * 1000
        blocks = response.get("output", {}).get("message", {}).get("content", [])
        tool_input = next((b["toolUse"]["input"] for b in blocks if "toolUse" in b), None)
        if tool_input is None:
            raise RuntimeError(f"No structured output for review {review.review_id} "
                               f"(stop={response.get('stopReason')})")
        parsed = ReviewDecision.model_validate(tool_input)  # raises if labels are invalid

        decision = to_decision(review.review_id, parsed, self.model_id)
        usage = response.get("usage", {})
        decision.latency_ms = latency_ms
        decision.input_tokens = usage.get("inputTokens", 0)
        decision.output_tokens = usage.get("outputTokens", 0)
        decision.cost_usd = (decision.input_tokens / 1e6 * self.input_price
                             + decision.output_tokens / 1e6 * self.output_price)
        return decision
