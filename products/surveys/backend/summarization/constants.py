"""Configuration constants for survey summarization."""

from .models import GeminiModel

# Default model for survey summarization
DEFAULT_MODEL = GeminiModel.GEMINI_3_FLASH_PREVIEW

# Timeout configuration (seconds)
SUMMARIZATION_TIMEOUT = 60
