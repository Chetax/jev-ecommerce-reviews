from __future__ import annotations

import os
from dataclasses import dataclass, field

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

# An empty Bedrock key (e.g. `AWS_BEARER_TOKEN_BEDROCK=` left blank in .env) would make the
# SDK use API-key auth with a blank key. Drop it so the default AWS credential chain
# (aws configure / AWS_PROFILE / SSO / instance role) is used instead.
for _var in ("AWS_BEARER_TOKEN_BEDROCK", "ANTHROPIC_AWS_API_KEY"):
    if os.environ.get(_var, None) == "":
        del os.environ[_var]


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default)


def _f(name: str, default: float) -> float:
    v = os.getenv(name)
    return float(v) if v not in (None, "") else default


@dataclass(frozen=True)
class Settings:
    # Amazon Bedrock (Claude). Auth: AWS_BEARER_TOKEN_BEDROCK (Bedrock API key)
    # or standard AWS credentials (env vars / AWS_PROFILE).
    aws_region: str = field(default_factory=lambda: _env("AWS_REGION", "us-east-1"))
    bedrock_model_id: str = field(default_factory=lambda: _env("BEDROCK_MODEL_ID", "anthropic.claude-opus-5-5"))
    bedrock_fallback_model_id: str = field(
        default_factory=lambda: _env("BEDROCK_FALLBACK_MODEL_ID", "anthropic.claude-opus-4-8"))
    bedrock_effort: str = field(default_factory=lambda: _env("BEDROCK_EFFORT", "low"))
    bedrock_input_price_per_m: float = field(default_factory=lambda: _f("BEDROCK_INPUT_PRICE_PER_M", 4.00))
    bedrock_output_price_per_m: float = field(default_factory=lambda: _f("BEDROCK_OUTPUT_PRICE_PER_M", 20.00))

    # TypeSafe Jev (optional - only needed to run/benchmark Jev)
    typesafe_api_key: str = field(default_factory=lambda: _env("TYPESAFE_API_KEY"))
    typesafe_base_url: str = field(
        default_factory=lambda: _env("TYPESAFE_BASE_URL", "https://api.typesafe.ai/v1").rstrip("/"))
    jev_model: str = field(default_factory=lambda: _env("JEV_MODEL", "jev-1.13.0"))
    jev_input_price_per_m: float = field(default_factory=lambda: _f("JEV_INPUT_PRICE_PER_M", 0.042))

    # Google Sheets
    service_account_file: str = field(
        default_factory=lambda: _env("GOOGLE_SERVICE_ACCOUNT_FILE", "service_account.json"))
    sheet_id: str = field(default_factory=lambda: _env("SHEET_ID"))
    sheet_input_tab: str = field(default_factory=lambda: _env("SHEET_INPUT_TAB", "reviews"))
    sheet_output_tab: str = field(default_factory=lambda: _env("SHEET_OUTPUT_TAB", "decisions"))

    confidence_threshold: float = field(default_factory=lambda: _f("CONFIDENCE_THRESHOLD", 0.8))

    @property
    def jev_enabled(self) -> bool:
        return bool(self.typesafe_api_key)

    def require_typesafe_key(self) -> str:
        if not self.typesafe_api_key:
            raise RuntimeError("TYPESAFE_API_KEY is not set. Jev is a paid TypeSafe API; get a key at typesafe.ai.")
        return self.typesafe_api_key


def get_settings() -> Settings:
    return Settings()
