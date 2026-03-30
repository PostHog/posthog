from typing import TypedDict

from products.llm_analytics.backend.llm.client import Client
from products.llm_analytics.backend.llm.errors import LLMError, ProviderMismatchError, UnsupportedProviderError
from products.llm_analytics.backend.llm.providers.anthropic import AnthropicConfig
from products.llm_analytics.backend.llm.providers.gemini import GeminiConfig
from products.llm_analytics.backend.llm.providers.openai import OpenAIConfig
from products.llm_analytics.backend.llm.types import CompletionRequest, CompletionResponse, StreamChunk, Usage

SUPPORTED_MODELS_WITH_THINKING = (
    AnthropicConfig.SUPPORTED_MODELS_WITH_THINKING + OpenAIConfig.SUPPORTED_MODELS_WITH_THINKING
)


class ModelInfo(TypedDict):
    id: str
    name: str
    provider: str
    description: str
    is_recommended: bool


def get_default_models() -> list[ModelInfo]:
    """Returns the default static list of models for all providers."""
    models: list[ModelInfo] = []
    models.extend(
        [
            {"id": m, "name": m, "provider": "OpenAI", "description": "", "is_recommended": True}
            for m in OpenAIConfig.SUPPORTED_MODELS
        ]
    )
    models.extend(
        [
            {"id": m, "name": m, "provider": "Anthropic", "description": "", "is_recommended": True}
            for m in AnthropicConfig.SUPPORTED_MODELS
        ]
    )
    models.extend(
        [
            {"id": m, "name": m, "provider": "Gemini", "description": "", "is_recommended": True}
            for m in GeminiConfig.SUPPORTED_MODELS
        ]
    )
    return models


def get_trial_models() -> list[ModelInfo]:
    """Returns the models available to trial users (PostHog pays).

    This is a curated subset excluding expensive models like pro/opus tiers
    while including one flagship per provider for quality evaluation.
    """
    models: list[ModelInfo] = []
    models.extend(
        [
            {"id": m, "name": m, "provider": "OpenAI", "description": "", "is_recommended": True}
            for m in OpenAIConfig.TRIAL_MODELS
        ]
    )
    models.extend(
        [
            {"id": m, "name": m, "provider": "Anthropic", "description": "", "is_recommended": True}
            for m in AnthropicConfig.TRIAL_MODELS
        ]
    )
    models.extend(
        [
            {"id": m, "name": m, "provider": "Gemini", "description": "", "is_recommended": True}
            for m in GeminiConfig.TRIAL_MODELS
        ]
    )
    return models


TRIAL_MODEL_IDS: frozenset[str] = frozenset(
    OpenAIConfig.TRIAL_MODELS + AnthropicConfig.TRIAL_MODELS + GeminiConfig.TRIAL_MODELS
)

# Provider-keyed lookup for code that needs per-provider trial lists
TRIAL_MODELS_BY_PROVIDER: dict[str, list[str]] = {
    "openai": OpenAIConfig.TRIAL_MODELS,
    "anthropic": AnthropicConfig.TRIAL_MODELS,
    "gemini": GeminiConfig.TRIAL_MODELS,
}


__all__ = [
    "Client",
    "CompletionRequest",
    "CompletionResponse",
    "StreamChunk",
    "Usage",
    "LLMError",
    "ModelInfo",
    "ProviderMismatchError",
    "UnsupportedProviderError",
    "SUPPORTED_MODELS_WITH_THINKING",
    "TRIAL_MODEL_IDS",
    "TRIAL_MODELS_BY_PROVIDER",
    "get_default_models",
    "get_trial_models",
    "OpenAIConfig",
    "AnthropicConfig",
    "GeminiConfig",
]
