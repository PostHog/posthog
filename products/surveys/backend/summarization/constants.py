"""Configuration constants for survey summarization."""

from .models import AnthropicModel

# Default model for survey summarization. A cheap Anthropic model routed through the ai-gateway.
DEFAULT_MODEL = AnthropicModel.CLAUDE_HAIKU_4_5

# Timeout configuration (seconds)
SUMMARIZATION_TIMEOUT = 60
