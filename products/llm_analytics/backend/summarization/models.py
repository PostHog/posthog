"""Type definitions for LLM analytics summarization."""

from enum import StrEnum


class AnalysisLevel(StrEnum):
    """Level at which to analyze LLM data.

    - TRACE: Analyze entire traces (aggregates all events in a trace)
    - GENERATION: Analyze individual $ai_generation events
    """

    TRACE = "trace"
    GENERATION = "generation"


class SummarizationProvider(StrEnum):
    """Supported LLM providers for summarization."""

    OPENAI = "openai"
    GEMINI = "gemini"


class OpenAIModel(StrEnum):
    """Supported OpenAI models for summarization."""

    GPT_4_1_MINI = "gpt-4.1-mini"
    GPT_4O_MINI = "gpt-4o-mini"
    GPT_4O = "gpt-4o"


class GeminiModel(StrEnum):
    """Supported Gemini models for summarization."""

    GEMINI_3_FLASH_PREVIEW = "gemini-3-flash-preview"
    GEMINI_2_5_FLASH = "gemini-2.5-flash"
    GEMINI_2_0_FLASH = "gemini-2.0-flash"


class SummarizationMode(StrEnum):
    """Summary detail levels."""

    MINIMAL = "minimal"
    DETAILED = "detailed"
