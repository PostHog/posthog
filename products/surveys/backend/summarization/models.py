"""Type definitions for survey summarization."""

from enum import StrEnum


class SummarizationModel(StrEnum):
    """Supported models for survey summarization, routed via the LLM gateway.

    Must stay a subset of the `survey_summary` product's `allowed_models` in
    services/llm-gateway/src/llm_gateway/products/config.py; the gateway rejects
    anything outside that allowlist.
    """

    CLAUDE_HAIKU_4_5 = "claude-haiku-4-5"
