"""
Routing for self-hosted models deployed on Modal via vLLM.

Maps user-facing model names (e.g. "glm-5") to litellm's hosted_vllm/ prefix
and the correct regional api_base URL. Registers cost data into litellm so
rate limiting works for self-hosted models.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import ClassVar, Final
from urllib.parse import urlparse

import litellm
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
    api_key: str | None = None
    context_window: int = 200_000
    supports_vision: bool = False
    input_cost_per_token: float = 0.0
    output_cost_per_token: float = 0.0

    def api_base_for_region(self, region: str) -> str | None:
        if region == "eu" and self.api_base_url_eu:
            return self.api_base_url_eu
        if self.api_base_url_us:
            return self.api_base_url_us
        return self.api_base_url_eu


def _validate_url(url: str, label: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("https", "http"):
        raise ValueError(f"{label}: must be an HTTP(S) URL, got {url!r}")
    if not parsed.netloc:
        raise ValueError(f"{label}: missing host in URL {url!r}")
    if not parsed.path.rstrip("/").endswith("/v1"):
        logger.warning(
            "hosted_model_url_missing_v1_suffix",
            label=label,
            url=url,
            hint="litellm's hosted_vllm/ provider appends /chat/completions to api_base, so the URL should end with /v1",
        )


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
        api_key = settings.glm5_api_key

        if not us and not eu:
            return

        if us:
            _validate_url(us, "LLM_GATEWAY_GLM5_API_BASE_URL_US")
        if eu:
            _validate_url(eu, "LLM_GATEWAY_GLM5_API_BASE_URL_EU")

        model = HostedModel(
            user_facing_id="glm-5",
            litellm_model_id="hosted_vllm/glm-5",
            api_base_url_us=us,
            api_base_url_eu=eu,
            api_key=api_key,
            context_window=200_000,
            input_cost_per_token=1.0 / 1_000_000,
            output_cost_per_token=3.2 / 1_000_000,
        )
        self._models["glm-5"] = model
        _register_litellm_cost(model)
        logger.info("hosted_model_registered", model="glm-5", us=bool(us), eu=bool(eu), auth=bool(api_key))

    def is_hosted(self, model_id: str) -> bool:
        return model_id in self._models

    def get_all(self) -> list[HostedModel]:
        return list(self._models.values())


def _register_litellm_cost(model: HostedModel) -> None:
    """Register cost data in litellm.model_cost so rate limiting and cost
    tracking work for self-hosted models instead of falling back to the
    default $0.01/request."""
    litellm.model_cost[model.litellm_model_id] = {
        "input_cost_per_token": model.input_cost_per_token,
        "output_cost_per_token": model.output_cost_per_token,
        "max_input_tokens": model.context_window,
        "max_output_tokens": 128_000,
        "litellm_provider": HOSTED_VLLM_PROVIDER,
        "mode": "chat",
    }


def resolve_hosted_model(model_id: str) -> tuple[str, str, str | None] | None:
    """Return (litellm_model_id, api_base_url, api_key) if model_id is hosted, else None."""
    registry = HostedModelRegistry.get_instance()
    model = registry._models.get(model_id)
    if model is None:
        return None

    region = os.environ.get("POSTHOG_REGION", os.environ.get("LLM_GATEWAY_REGION", "us")).lower()
    api_base = model.api_base_for_region(region)
    if api_base is None:
        logger.warning("hosted_model_no_endpoint", model=model_id, region=region)
        return None

    return model.litellm_model_id, api_base, model.api_key
