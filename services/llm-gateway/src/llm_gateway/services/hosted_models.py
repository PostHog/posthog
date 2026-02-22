"""
Routing for self-hosted models deployed on Modal via vLLM.

Maps user-facing model names (e.g. "glm-5") to litellm's hosted_vllm/ prefix
and the correct regional api_base URL.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import ClassVar, Final

import structlog

from llm_gateway.config import get_settings

logger = structlog.get_logger(__name__)

HOSTED_VLLM_PROVIDER: Final[str] = "hosted_vllm"


@dataclass(frozen=True)
class HostedModel:
    user_facing_id: str
    litellm_model_id: str
    api_base_url_us: str | None = None
    api_base_url_eu: str | None = None
    context_window: int = 200_000
    supports_vision: bool = False

    def api_base_for_region(self, region: str) -> str | None:
        if region == "eu" and self.api_base_url_eu:
            return self.api_base_url_eu
        if self.api_base_url_us:
            return self.api_base_url_us
        return self.api_base_url_eu


@dataclass
class HostedModelRegistry:
    _models: dict[str, HostedModel] = field(default_factory=dict)
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
        us = settings.glm5_api_base_url_us
        eu = settings.glm5_api_base_url_eu
        if us or eu:
            self._models["glm-5"] = HostedModel(
                user_facing_id="glm-5",
                litellm_model_id="hosted_vllm/glm-5",
                api_base_url_us=us,
                api_base_url_eu=eu,
            )
            logger.info("hosted_model_registered", model="glm-5", us=bool(us), eu=bool(eu))

    def is_hosted(self, model_id: str) -> bool:
        return model_id in self._models

    def get_all(self) -> list[HostedModel]:
        return list(self._models.values())


def resolve_hosted_model(model_id: str) -> tuple[str, str] | None:
    """Return (litellm_model_id, api_base_url) if model_id is hosted, else None."""
    registry = HostedModelRegistry.get_instance()
    model = registry._models.get(model_id)
    if model is None:
        return None

    region = os.environ.get("POSTHOG_REGION", os.environ.get("LLM_GATEWAY_REGION", "us")).lower()
    api_base = model.api_base_for_region(region)
    if api_base is None:
        logger.warning("hosted_model_no_endpoint", model=model_id, region=region)
        return None

    return model.litellm_model_id, api_base
