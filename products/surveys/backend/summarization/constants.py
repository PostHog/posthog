"""Configuration constants for survey summarization."""

from posthog.llm.gateway_client import Product

from .models import SummarizationModel

# Gateway product route; owns the `ai_product` tag and the billing bucket.
SUMMARY_GATEWAY_PRODUCT: Product = "survey_summary"

# Default model for survey summarization
DEFAULT_MODEL = SummarizationModel.CLAUDE_HAIKU_4_5

# Timeout configuration (seconds)
SUMMARIZATION_TIMEOUT = 60
