from typing import Any, TypedDict

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


# Single registry of providers. Add new providers here and everything else
# (model lists, trial models, ID sets) derives from it automatically.
PROVIDERS: list[tuple[str, Any]] = [
    ("OpenAI", OpenAIConfig),
    ("Anthropic", AnthropicConfig),
    ("Gemini", GeminiConfig),
]


def _build_model_infos(provider: str, models: list[str]) -> list[ModelInfo]:
    return [{"id": m, "name": m, "provider": provider, "description": "", "is_recommended": True} for m in models]


def get_default_models() -> list[ModelInfo]:
    """Returns the full list of supported models across all providers."""
    result: list[ModelInfo] = []
    for display_name, config in PROVIDERS:
        result.extend(_build_model_infos(display_name, config.SUPPORTED_MODELS))
    return result


def get_trial_models() -> list[ModelInfo]:
    """Returns the models available to trial users (PostHog pays).

    This is a curated subset excluding expensive models like pro/opus tiers
    while including one flagship per provider for quality evaluation.
    """
    result: list[ModelInfo] = []
    for display_name, config in PROVIDERS:
        result.extend(_build_model_infos(display_name, config.TRIAL_MODELS))
    return result


TRIAL_MODEL_IDS: frozenset[str] = frozenset(model for _, config in PROVIDERS for model in config.TRIAL_MODELS)

# Provider-keyed lookup (lowercase keys matching DB provider values)
TRIAL_MODELS_BY_PROVIDER: dict[str, list[str]] = {
    display_name.lower(): config.TRIAL_MODELS for display_name, config in PROVIDERS
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
    "PROVIDERS",
    "SUPPORTED_MODELS_WITH_THINKING",
    "TRIAL_MODEL_IDS",
    "TRIAL_MODELS_BY_PROVIDER",
    "get_default_models",
    "get_trial_models",
    "OpenAIConfig",
    "AnthropicConfig",
    "GeminiConfig",
]
