"""Type definitions for LLM analytics summarization."""

from enum import StrEnum


class SummarizationProvider(StrEnum):
    """Supported LLM providers for summarization."""

    OPENAI = "openai"
    GEMINI = "gemini"  # Deprecated: kept for backwards compatibility until temporal code is updated


class OpenAIModel(StrEnum):
    """Supported OpenAI models for summarization."""

    GPT_4_1_NANO = "gpt-4.1-nano"
    GPT_4_1_MINI = "gpt-4.1-mini"


class GeminiModel(StrEnum):
    """Deprecated: kept for backwards compatibility until temporal code is updated."""

    GEMINI_3_FLASH_PREVIEW = "gemini-3-flash-preview"
    GEMINI_2_5_FLASH = "gemini-2.5-flash"
    GEMINI_2_0_FLASH = "gemini-2.0-flash"


class SummarizationMode(StrEnum):
    """Summary detail levels."""

    MINIMAL = "minimal"
    DETAILED = "detailed"
