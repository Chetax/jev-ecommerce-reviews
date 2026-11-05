"""Build classifiers from model specs: "bedrock", "bedrock:<model id>", or "jev".

Claude model IDs (anthropic.*) use the Claude SDK on Bedrock; anything else (e.g. Amazon Nova)
uses the Bedrock Converse API.
"""

from __future__ import annotations

from .bedrock_client import BedrockClassifier
from .config import Settings
from .jev_client import JevClassifier
from .nova_client import ConverseClassifier, is_claude, short_name

NOVA_MODELS = ["us.amazon.nova-2-lite-v1:0", "us.amazon.nova-pro-v1:0",
               "us.amazon.nova-lite-v1:0", "us.amazon.nova-micro-v1:0"]


def _bedrock(s: Settings, model_id: str, client=None):
    if is_claude(model_id):
        return BedrockClassifier(s, model_id=model_id, client=client)
    return ConverseClassifier(s, model_id=model_id, client=client)


def make_classifier(spec: str, s: Settings, client=None):
    spec = spec.strip()
    if spec == "jev":
        s.require_typesafe_key()
        return JevClassifier(s)
    if spec == "bedrock":
        return _bedrock(s, s.bedrock_model_id, client)
    if spec.startswith("bedrock:"):
        return _bedrock(s, spec.split(":", 1)[1], client)
    raise ValueError(f"Unknown model spec {spec!r}. Use 'bedrock', 'bedrock:<model id>', or 'jev'.")


def default_models(s: Settings) -> str:
    return "bedrock,jev" if s.jev_enabled else "bedrock"


def model_options(s: Settings) -> list[dict]:
    opts = [{"spec": "bedrock", "label": short_name(s.bedrock_model_id), "provider": "Amazon Bedrock"}]
    others = NOVA_MODELS if not is_claude(s.bedrock_model_id) else ["anthropic.claude-haiku-5-5"]
    for m in others:
        if m != s.bedrock_model_id:
            opts.append({"spec": f"bedrock:{m}", "label": short_name(m), "provider": "Amazon Bedrock"})
    opts.append({"spec": "jev", "label": s.jev_model, "provider": "TypeSafe", "disabled": not s.jev_enabled})
    return opts
