from types import SimpleNamespace

import pytest

from jev_reviews.bedrock_client import BedrockClassifier, ReviewDecision
from jev_reviews.classifiers import make_classifier
from jev_reviews.config import Settings
from jev_reviews.schema import Review

SETTINGS = Settings(bedrock_model_id="anthropic.claude-opus-5-5", bedrock_input_price_per_m=4.0, bedrock_output_price_per_m=20.0, typesafe_api_key="")
REVIEW = Review("R1", "Headphones crackle out of the box, sending them back.")

PARSED = ReviewDecision.model_validate({
    "topic": "product_quality", "sentiment": "negative", "defect": True, "refund_request": True,
    "confidence": {"topic": 0.9, "sentiment": 1.3, "defect": 0.85, "refund_request": 0.8},
})


class FakeMessages:
    def __init__(self, response):
        self.response, self.kwargs = response, None

    def parse(self, **kwargs):
        self.kwargs = kwargs
        return self.response


def fake_client(stop_reason="end_turn", parsed=PARSED):
    usage = SimpleNamespace(input_tokens=500, output_tokens=100,
                            cache_read_input_tokens=0, cache_creation_input_tokens=None)
    resp = SimpleNamespace(stop_reason=stop_reason, stop_details=None, parsed_output=parsed,
                           usage=usage, model="anthropic.claude-opus-5-5")
    msgs = FakeMessages(resp)
    return SimpleNamespace(beta=SimpleNamespace(messages=msgs)), msgs


def test_bedrock_classify_request_and_decision():
    client, msgs = fake_client()
    d = BedrockClassifier(SETTINGS, client=client).classify(REVIEW)
    assert msgs.kwargs["model"] == SETTINGS.bedrock_model_id
    assert msgs.kwargs["output_format"] is ReviewDecision
    assert msgs.kwargs["output_config"] == {"effort": "low"}
    assert REVIEW.text in msgs.kwargs["messages"][0]["content"]
    assert (d.topic, d.sentiment, d.defect, d.refund_request) == ("product_quality", "negative", True, True)
    assert d.confidence["sentiment"] == 1.0  # clamped
    assert d.cost_usd == pytest.approx(500 / 1e6 * 4 + 100 / 1e6 * 20)


@pytest.mark.parametrize("stop,parsed", [("refusal", None), ("max_tokens", None), ("end_turn", None)])
def test_bedrock_errors_without_output(stop, parsed):
    client, _ = fake_client(stop, parsed)
    with pytest.raises(RuntimeError):
        BedrockClassifier(SETTINGS, client=client).classify(REVIEW)


def test_schema_rejects_invalid_topic():
    with pytest.raises(Exception):
        ReviewDecision.model_validate({**PARSED.model_dump(), "topic": "shipping"})


def test_model_specs():
    client, _ = fake_client()
    assert make_classifier("bedrock", SETTINGS, client=client).model_id == "anthropic.claude-opus-5-5"
    haiku = make_classifier("bedrock:anthropic.claude-haiku-5-5", SETTINGS, client=client)
    assert haiku.model_id == "anthropic.claude-haiku-5-5" and haiku.name == "claude-haiku-5-5"
    with pytest.raises(RuntimeError):
        make_classifier("jev", SETTINGS)
    with pytest.raises(ValueError):
        make_classifier("gpt", SETTINGS)


def test_real_client_constructs_with_bedrock_api_key(monkeypatch):
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "dummy")
    clf = BedrockClassifier(Settings(aws_region="us-east-1"))
    assert "bedrock-mantle.us-east-1" in str(clf.client.base_url)


# ---- Amazon Nova via the Converse API ----
from jev_reviews.nova_client import TOOL_SCHEMA, ConverseClassifier, short_name  # noqa: E402

NOVA_OUT = {"topic": "product_quality", "sentiment": "negative", "defect": True, "refund_request": True,
            "confidence": {"topic": 0.9, "sentiment": 0.95, "defect": 0.9, "refund_request": 1.2}}


class FakeConverse:
    def __init__(self, tool_input=NOVA_OUT):
        self.tool_input, self.calls = tool_input, []

    def converse(self, **kw):
        self.calls.append(kw)
        content = [{"toolUse": {"toolUseId": "1", "name": "record_decision", "input": self.tool_input}}] \
            if self.tool_input is not None else [{"text": "sorry"}]
        return {"output": {"message": {"content": content}}, "stopReason": "tool_use",
                "usage": {"inputTokens": 1000, "outputTokens": 100}}


def test_nova_classifies_via_forced_tool():
    fake = FakeConverse()
    clf = make_classifier("bedrock:us.amazon.nova-2-lite-v1:0", SETTINGS, client=fake)
    assert isinstance(clf, ConverseClassifier) and clf.name == "nova-2-lite"
    d = clf.classify(REVIEW)
    assert (d.topic, d.sentiment, d.defect, d.refund_request) == ("product_quality", "negative", True, True)
    assert d.confidence["refund_request"] == 1.0  # clamped
    assert d.cost_usd == pytest.approx(1000 / 1e6 * 0.30 + 100 / 1e6 * 2.50)
    call = fake.calls[0]
    assert call["toolConfig"]["toolChoice"] == {"tool": {"name": "record_decision"}}
    assert "<review>" in call["messages"][0]["content"][0]["text"]


def test_nova_rejects_missing_or_invalid_output():
    with pytest.raises(RuntimeError):
        ConverseClassifier(SETTINGS, "us.amazon.nova-lite-v1:0", client=FakeConverse(None)).classify(REVIEW)
    with pytest.raises(Exception):
        ConverseClassifier(SETTINGS, "us.amazon.nova-lite-v1:0",
                           client=FakeConverse({**NOVA_OUT, "topic": "shipping"})).classify(REVIEW)


def test_nova_tool_schema_has_no_refs():
    assert "$ref" not in str(TOOL_SCHEMA) and "$defs" not in TOOL_SCHEMA
    assert TOOL_SCHEMA["properties"]["confidence"]["properties"]["topic"]["type"] == "number"


def test_short_names():
    assert short_name("us.amazon.nova-pro-v1:0") == "nova-pro"
    assert short_name("anthropic.claude-opus-5-5") == "claude-opus-5-5"
