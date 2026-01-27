"""Configuration constants for LLM analytics summarization."""

from .models import GeminiModel, OpenAIModel, SummarizationMode, SummarizationProvider

# Default configuration
DEFAULT_PROVIDER = SummarizationProvider.OPENAI
DEFAULT_MODEL_OPENAI = OpenAIModel.GPT_4_1_MINI
DEFAULT_MODEL_GEMINI = GeminiModel.GEMINI_3_FLASH_PREVIEW
DEFAULT_MODE = SummarizationMode.MINIMAL

# Timeout configuration (seconds)
SUMMARIZATION_TIMEOUT = 120
