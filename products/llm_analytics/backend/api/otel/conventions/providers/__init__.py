"""
Provider-specific OTEL transformers.

Each provider (Mastra, Langchain, LlamaIndex, etc.) handles their
specific OTEL format quirks and normalizes to PostHog format.
"""

from .base import ProviderTransformer
from .mastra import MastraTransformer

# Registry of all available provider transformers
# Add new providers here as they're implemented
PROVIDER_TRANSFORMERS: list[type[ProviderTransformer]] = [
    MastraTransformer,
    # Future: LangchainTransformer, LlamaIndexTransformer, etc.
]

__all__ = [
    "ProviderTransformer",
    "MastraTransformer",
    "PROVIDER_TRANSFORMERS",
]
