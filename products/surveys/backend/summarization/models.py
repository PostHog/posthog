"""Type definitions for survey summarization."""

from enum import StrEnum


class GeminiModel(StrEnum):
    """Supported Gemini models for survey summarization."""

    GEMINI_3_FLASH_PREVIEW = "gemini-3-flash-preview"
    GEMINI_2_5_FLASH = "gemini-2.5-flash"
    GEMINI_2_0_FLASH = "gemini-2.0-flash"
