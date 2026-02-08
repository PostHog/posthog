"""Configuration constants for LLM analytics summarization."""

from .models import OpenAIModel, SummarizationMode

# Default configuration
DEFAULT_MODEL_OPENAI = OpenAIModel.GPT_4_1_MINI
DEFAULT_MODE = SummarizationMode.MINIMAL

# Timeout configuration (seconds)
SUMMARIZATION_TIMEOUT = 120

# Evaluation summary limits
EVALUATION_SUMMARY_MAX_RUNS = 250
