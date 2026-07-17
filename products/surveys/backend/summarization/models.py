"""Type definitions for survey summarization."""

from enum import StrEnum


class AnthropicModel(StrEnum):
    """Supported Anthropic models for survey summarization, routed through the ai-gateway."""

    CLAUDE_HAIKU_4_5 = "claude-haiku-4-5"
