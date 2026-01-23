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


def _get_configured_providers() -> frozenset[str]:
    """Return the set of providers that have API keys configured."""
    settings = get_settings()
    configured = set()
    for provider, (settings_attr, env_var) in _PROVIDER_TO_API_KEY.items():
        if getattr(settings, settings_attr, None) or os.environ.get(env_var):
            configured.add(provider)
    return frozenset(configured)


def _is_chat_model(cost_data: ModelCost) -> bool:
    """Check if a model is a chat model (not embedding, image generation, etc)."""
    mode = cost_data.get("mode", "")
    return mode in ("chat", "completion", "")


def _model_matches_allowlist(model_id: str, allowed_models: frozenset[str]) -> bool:
    """Check if model matches allowlist using prefix matching (consistent with check_product_access)."""
    model_lower = model_id.lower()
    return any(model_lower.startswith(allowed) for allowed in allowed_models)


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

    def get_available_models(self, product: str) -> list[ModelInfo]:
        """Get models available to a product, filtered by configured providers."""
        config = get_product_config(product)
        configured_providers = _get_configured_providers()
        allowed_models = config.allowed_models if config else None

        # Fetch all chat models from LiteLLM, filtered by configured providers
        all_litellm_models = ModelCostService.get_instance().get_all_models()
        models = []
        for model_id, cost_data in all_litellm_models.items():
            provider = cost_data.get("litellm_provider", "")
            if provider not in configured_providers:
                continue
            if not _is_chat_model(cost_data):
                continue
            if allowed_models is not None and not _model_matches_allowlist(model_id, allowed_models):
                continue
            model = self.get_model(model_id)
            if model is not None:
                models.append(model)
        return models

    def is_model_available(self, model_id: str, product: str) -> bool:
        """Check if a model is available for a product."""
        config = get_product_config(product)

        # If product has explicit allowed_models, check against those
        if config is not None and config.allowed_models is not None:
            if not _model_matches_allowlist(model_id, config.allowed_models):
                return False

        model = self.get_model(model_id)
        if model is None:
            return False
        return model.provider in _get_configured_providers()


def get_available_models(product: str) -> list[ModelInfo]:
    return ModelRegistryService.get_instance().get_available_models(product)


def is_model_available(model_id: str, product: str) -> bool:
    return ModelRegistryService.get_instance().is_model_available(model_id, product)
