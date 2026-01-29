"""Type definitions for LLM analytics summarization."""

from enum import StrEnum


class OpenAIModel(StrEnum):
    """Supported OpenAI models for summarization."""

    GPT_4_1_NANO = "gpt-4.1-nano"
    GPT_4_1_MINI = "gpt-4.1-mini"


class SummarizationMode(StrEnum):
    """Summary detail levels."""

    MINIMAL = "minimal"
    DETAILED = "detailed"
