from __future__ import annotations

import os
from dataclasses import dataclass
from typing import ClassVar, Final

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
}


def _has_config_value(value: object) -> bool:
    return isinstance(value, str) and value != ""


def _is_bedrock_configured(settings: object) -> bool:
    return (
        _has_config_value(getattr(settings, "bedrock_region_name", None))
        or _has_config_value(os.environ.get("AWS_REGION"))
        or _has_config_value(os.environ.get("AWS_DEFAULT_REGION"))
    )


def _get_configured_providers() -> frozenset[str]:
    """Return the set of providers that have required configuration."""
    settings = get_settings()
    configured = set()
    for provider, (settings_attr, env_var) in _PROVIDER_TO_API_KEY.items():
        settings_value = getattr(settings, settings_attr, None)
        env_value = os.environ.get(env_var)
        if _has_config_value(settings_value) or _has_config_value(env_value):
            configured.add(provider)
    if _is_bedrock_configured(settings):
        configured.add("bedrock")
    return frozenset(configured)


def _is_chat_model(cost_data: ModelCost) -> bool:
    """Check if a model is a chat model (not embedding, image generation, etc)."""
    mode = cost_data.get("mode", "")
    return mode in ("chat", "completion", "")


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
            provider=cost_data.get("litellm_provider", "unknown"),
            context_window=cost_data.get("max_input_tokens") or 0,
            supports_vision=bool(cost_data.get("supports_vision", False)),
            supports_streaming=True,
        )

    def get_available_models(self, product: str, provider_filter: str | None = None) -> list[ModelInfo]:
        """Get raw provider models available to a product, optionally filtered by provider."""
        config = get_product_config(product)
        configured_providers = _get_configured_providers()
        if provider_filter is not None:
            if provider_filter not in configured_providers:
                return []
            configured_providers = frozenset({provider_filter})
        allowed_models = config.allowed_models if config else None
        all_litellm_models = ModelCostService.get_instance().get_all_models()
        models_by_id: dict[str, ModelInfo] = {}
        for raw_model_id in sorted(all_litellm_models.keys()):
            cost_data = all_litellm_models[raw_model_id]
            provider = cost_data.get("litellm_provider", "")
            if provider not in configured_providers:
                continue
            if not _is_chat_model(cost_data):
                continue
            if allowed_models is not None and raw_model_id not in allowed_models:
                continue
            existing = models_by_id.get(raw_model_id)
            candidate = ModelInfo(
                id=raw_model_id,
                provider=provider,
                context_window=cost_data.get("max_input_tokens") or 0,
                supports_vision=bool(cost_data.get("supports_vision", False)),
                supports_streaming=True,
            )
            if existing is None:
                models_by_id[raw_model_id] = candidate
        return list(models_by_id.values())

    def is_model_available(self, model_id: str, product: str) -> bool:
        """Check if a model is available for a product."""
        config = get_product_config(product)

        # If product has explicit allowed_models, check against those
        if config is not None and config.allowed_models is not None:
            if model_id not in config.allowed_models:
                return False

        configured_providers = _get_configured_providers()
        cost_data = ModelCostService.get_instance().get_costs(model_id)
        if cost_data is None:
            return False
        provider = cost_data.get("litellm_provider", "")
        return provider in configured_providers and _is_chat_model(cost_data)


def get_available_models(product: str, provider_filter: str | None = None) -> list[ModelInfo]:
    return ModelRegistryService.get_instance().get_available_models(product, provider_filter)


def is_model_available(model_id: str, product: str) -> bool:
    return ModelRegistryService.get_instance().is_model_available(model_id, product)
