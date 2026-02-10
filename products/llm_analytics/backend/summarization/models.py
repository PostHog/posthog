"""Type definitions for LLM analytics summarization."""

from enum import StrEnum


class OpenAIModel(StrEnum):
    """Supported OpenAI models for summarization."""

    GPT_4_1_NANO = "gpt-4.1-nano"
    GPT_4_1_MINI = "gpt-4.1-mini"
    GPT_4O_MINI = "gpt-4o-mini"
    GPT_4O = "gpt-4o"
    GPT_5_MINI = "gpt-5-mini"


class SummarizationMode(StrEnum):
    """Summary detail levels."""

    MINIMAL = "minimal"
    DETAILED = "detailed"
