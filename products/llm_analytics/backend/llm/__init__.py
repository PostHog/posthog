from products.llm_analytics.backend.llm.client import Client
from products.llm_analytics.backend.llm.errors import LLMError, ProviderMismatchError, UnsupportedProviderError
from products.llm_analytics.backend.llm.providers.anthropic import AnthropicConfig
from products.llm_analytics.backend.llm.providers.gemini import GeminiConfig
from products.llm_analytics.backend.llm.providers.openai import OpenAIConfig
from products.llm_analytics.backend.llm.types import CompletionRequest, CompletionResponse, StreamChunk, Usage

SUPPORTED_MODELS_WITH_THINKING = (
    AnthropicConfig.SUPPORTED_MODELS_WITH_THINKING + OpenAIConfig.SUPPORTED_MODELS_WITH_THINKING
)


def get_default_models() -> list[dict[str, str]]:
    """Returns the default static list of models for all providers."""
    models: list[dict[str, str]] = []
    models.extend(
        [{"id": m, "name": m, "provider": "OpenAI", "description": ""} for m in OpenAIConfig.SUPPORTED_MODELS]
    )
    models.extend(
        [{"id": m, "name": m, "provider": "Anthropic", "description": ""} for m in AnthropicConfig.SUPPORTED_MODELS]
    )
    models.extend(
        [{"id": m, "name": m, "provider": "Gemini", "description": ""} for m in GeminiConfig.SUPPORTED_MODELS]
    )
    return models


__all__ = [
    "Client",
    "CompletionRequest",
    "CompletionResponse",
    "StreamChunk",
    "Usage",
    "LLMError",
    "ProviderMismatchError",
    "UnsupportedProviderError",
    "SUPPORTED_MODELS_WITH_THINKING",
    "get_default_models",
    "OpenAIConfig",
    "AnthropicConfig",
    "GeminiConfig",
]
