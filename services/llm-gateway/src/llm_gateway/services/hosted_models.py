"""
Routing and configuration for self-hosted models deployed on Modal via vLLM.

Self-hosted models are exposed through vLLM's OpenAI-compatible API and routed
via litellm's hosted_vllm/ prefix. The gateway maps user-facing model names
(e.g. "glm-5") to their internal litellm identifiers and injects the correct
api_base URL depending on deployment region.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import ClassVar, Final

import structlog

from llm_gateway.config import get_settings

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class HostedModelConfig:
    user_facing_id: str
    litellm_model_id: str
    api_base_url_us: str | None = None
    api_base_url_eu: str | None = None
    context_window: int = 200_000
    max_output_tokens: int = 128_000
    input_cost_per_token: float = 0.0
    output_cost_per_token: float = 0.0
    supports_vision: bool = False


@dataclass
class HostedModelRegistry:
    _models: dict[str, HostedModelConfig] = field(default_factory=dict)

    _instance: ClassVar[HostedModelRegistry | None] = None

    @classmethod
    def get_instance(cls) -> HostedModelRegistry:
        if cls._instance is None:
            cls._instance = cls()
            cls._instance._load_from_settings()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        cls._instance = None

    def _load_from_settings(self) -> None:
        settings = get_settings()

        glm5_us = settings.glm5_api_base_url_us
        glm5_eu = settings.glm5_api_base_url_eu

        if glm5_us or glm5_eu:
            self.register(
                HostedModelConfig(
                    user_facing_id="glm-5",
                    litellm_model_id="hosted_vllm/zai-org/GLM-5-FP8",
                    api_base_url_us=glm5_us,
                    api_base_url_eu=glm5_eu,
                    context_window=200_000,
                    max_output_tokens=128_000,
                    input_cost_per_token=1.0 / 1_000_000,
                    output_cost_per_token=3.2 / 1_000_000,
                )
            )
            logger.info("hosted_model_registered", model="glm-5", us=bool(glm5_us), eu=bool(glm5_eu))

    def register(self, config: HostedModelConfig) -> None:
        self._models[config.user_facing_id] = config

    def resolve(self, model_id: str) -> HostedModelConfig | None:
        return self._models.get(model_id)

    def is_hosted(self, model_id: str) -> bool:
        return model_id in self._models

    def get_all(self) -> list[HostedModelConfig]:
        return list(self._models.values())

    def get_api_base(self, model_id: str, region: str | None = None) -> str | None:
        config = self._models.get(model_id)
        if config is None:
            return None

        if region == "eu" and config.api_base_url_eu:
            return config.api_base_url_eu
        if config.api_base_url_us:
            return config.api_base_url_us
        return config.api_base_url_eu


HOSTED_VLLM_PROVIDER: Final[str] = "hosted_vllm"


def resolve_hosted_model(model_id: str) -> tuple[str, str] | None:
    """
    If model_id is a hosted model, return (litellm_model_id, api_base_url).
    Returns None if not a hosted model or not configured.
    """
    registry = HostedModelRegistry.get_instance()
    config = registry.resolve(model_id)
    if config is None:
        return None

    region = _detect_region()
    api_base = registry.get_api_base(model_id, region)
    if api_base is None:
        logger.warning("hosted_model_no_endpoint", model=model_id, region=region)
        return None

    return config.litellm_model_id, api_base


def _detect_region() -> str:
    return os.environ.get("POSTHOG_REGION", os.environ.get("LLM_GATEWAY_REGION", "us")).lower()
