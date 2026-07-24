"""Configuration constants for survey summarization."""

from .models import AnthropicModel

DEFAULT_MODEL = AnthropicModel.CLAUDE_HAIKU_4_5

# Timeout configuration (seconds)
SUMMARIZATION_TIMEOUT = 60
