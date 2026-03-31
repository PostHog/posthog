from __future__ import annotations

import os
from dataclasses import dataclass
from typing import ClassVar, Final

from llm_gateway.bedrock import BEDROCK_ANTHROPIC_MODEL_PREFIXES, is_bedrock_configured
from llm_gateway.config import get_settings
from llm_gateway.products.config import get_product_config
from llm_gateway.rate_limiting.model_cost_service import ModelCost, ModelCostService


@dataclass(frozen=True)
class ModelInfo:
    id: str
    provider: str
    context_window: int
    supports_streaming: bool = True
    supports_vision: bool = False


# Map LiteLLM provider names to (settings_attr, env_var) tuples
# Settings use LLM_GATEWAY_ prefix, but litellm also checks unprefixed env vars
_PROVIDER_TO_API_KEY: Final[dict[str, tuple[str, str]]] = {
    "openai": ("openai_api_key", "OPENAI_API_KEY"),
    "anthropic": ("anthropic_api_key", "ANTHROPIC_API_KEY"),
    "vertex_ai": ("gemini_api_key", "GEMINI_API_KEY"),
    "vertex_ai-language-models": ("gemini_api_key", "GEMINI_API_KEY"),
    "gemini": ("gemini_api_key", "GEMINI_API_KEY"),
    "openrouter": ("openrouter_api_key", "OPENROUTER_API_KEY"),
    "fireworks_ai": ("fireworks_api_key", "FIREWORKS_API_KEY"),
}


def _model_matches_allowlist(model_id: str, allowed_models: frozenset[str]) -> bool:
    """Check if model matches allowlist using exact matching for /models endpoint listing."""
    return model_id.lower() in allowed_models


def _get_configured_providers() -> frozenset[str]:
    """Return the set of providers that have required configuration."""
    settings = get_settings()
    configured = set()
    for provider, (settings_attr, env_var) in _PROVIDER_TO_API_KEY.items():
        if getattr(settings, settings_attr, None) or os.environ.get(env_var):
            configured.add(provider)
    if is_bedrock_configured(settings):
        configured.add("bedrock")
        # Use bedrock_converse for model lookups in LiteLLM until they support bedrock provider lookups
        configured.add("bedrock_converse")
    return frozenset(configured)


def _is_text_generation_model(cost_data: ModelCost) -> bool:
    """Check if a model supports text generation (chat/completions/responses)."""
    mode = cost_data.get("mode", "")
    return mode in ("chat", "completion", "responses", "")


def _normalize_provider(provider: str) -> str:
    """Present LiteLLM's Bedrock variants as a single provider."""
    return "bedrock" if provider == "bedrock_converse" else provider


def _is_configured_provider(provider: str, configured_providers: frozenset[str]) -> bool:
    normalized_provider = _normalize_provider(provider)
    return provider in configured_providers or normalized_provider in configured_providers


# DISCLAIMER: We only support Anthropic models on Bedrock right now
def _supports_bedrock_messages_endpoint(model_id: str, provider: str) -> bool:
    normalized_provider = _normalize_provider(provider)
    if normalized_provider != "bedrock":
        return True
    return model_id.startswith(BEDROCK_ANTHROPIC_MODEL_PREFIXES)


class ModelRegistryService:
    """Singleton service for model discovery using LiteLLM data."""

    _instance: ClassVar[ModelRegistryService | None] = None

    @classmethod
    def get_instance(cls) -> ModelRegistryService:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """For testing."""
        cls._instance = None

    def get_model(self, model_id: str) -> ModelInfo | None:
        """Get model info from LiteLLM's cost data."""
        cost_data = ModelCostService.get_instance().get_costs(model_id)
        if cost_data is None:
            return None
        return ModelInfo(
            id=model_id,
            provider=_normalize_provider(cost_data.get("litellm_provider", "unknown")),
            context_window=cost_data.get("max_input_tokens") or 0,
            supports_vision=bool(cost_data.get("supports_vision", False)),
            supports_streaming=True,
        )

    def get_available_models(self, product: str) -> list[ModelInfo]:
        """Get raw provider models available for a given product."""
        config = get_product_config(product)
        configured_providers = _get_configured_providers()
        allowed_models = config.allowed_models if config else None

        all_litellm_models = ModelCostService.get_instance().get_all_models()
        models_by_id: dict[str, ModelInfo] = {}

        # Iterate over all LiteLLM models and filter out models that don't meet the criteria
        for raw_model_id in sorted(all_litellm_models.keys()):
            model_cost_data = all_litellm_models[raw_model_id]
            model_provider = model_cost_data.get("litellm_provider", "")

            # Filter out models where provider is not configured
            if not _is_configured_provider(model_provider, configured_providers):
                continue
            if not _is_text_generation_model(model_cost_data):
                continue
            # Filter out Bedrock models that don't support the messages endpoint
            if not _supports_bedrock_messages_endpoint(raw_model_id, model_provider):
                continue
            # Filter out models that are not in the allowed models list
            if allowed_models is not None and not _model_matches_allowlist(raw_model_id, allowed_models):
                continue

            if models_by_id.get(raw_model_id) is None:
                # Add the model to the dictionary if it doesn't exist
                models_by_id[raw_model_id] = ModelInfo(
                    id=raw_model_id,
                    provider=_normalize_provider(model_provider),
                    context_window=model_cost_data.get("max_input_tokens") or 0,
                    supports_vision=bool(model_cost_data.get("supports_vision", False)),
                    supports_streaming=True,
                )
        return list(models_by_id.values())

    def is_model_available(self, model_id: str, product: str) -> bool:
        """Check if a model is available for a product."""
        config = get_product_config(product)

        # If product has explicit allowed_models, check against those
        if config is not None and config.allowed_models is not None:
            if not _model_matches_allowlist(model_id, config.allowed_models):
                return False

        configured_providers = _get_configured_providers()
        cost_data = ModelCostService.get_instance().get_costs(model_id)
        if cost_data is None:
            return False
        provider = cost_data.get("litellm_provider", "")

        if not _supports_bedrock_messages_endpoint(model_id, provider):
            return False

        return _is_configured_provider(provider, configured_providers) and _is_text_generation_model(cost_data)


def get_available_models(product: str) -> list[ModelInfo]:
    return ModelRegistryService.get_instance().get_available_models(product)


def is_model_available(model_id: str, product: str) -> bool:
    return ModelRegistryService.get_instance().is_model_available(model_id, product)
