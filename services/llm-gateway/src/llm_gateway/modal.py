from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable
from typing import Any, Final

import litellm
from fastapi import HTTPException

# Experimental litellm path — `tests/test_cloudflare.py` has a contract test that fails fast on a rename.
from litellm.llms.anthropic.experimental_pass_through.adapters.handler import (
    LiteLLMMessagesToCompletionTransformationHandler,
)

from llm_gateway.config import Settings, _normalize_cost_key

# Modal endpoints are OpenAI-compatible vLLM servers; no native litellm provider.
_MODAL_LITELLM_PREFIX = "openai/"

# Modal auth rides in the Modal-Key/Modal-Secret headers, but litellm's OpenAI client
# requires a non-empty api_key.
_MODAL_PLACEHOLDER_API_KEY = "modal-proxy-token-auth"

# Public gateway model id -> the model name Modal's endpoint serves. The public id keeps its
# `@cf/` form so clients need no changes; every served name must be priced in COST_ALIASES
# under `openai/<served>` (tests/test_modal.py enforces the pairing).
MODAL_MODEL_MAP: Final[dict[str, str]] = {
    "@cf/zai-org/glm-5.2": "zai-org/GLM-5.2-FP8",
}

MODAL_ALLOWED_MODELS: Final[frozenset[str]] = frozenset(MODAL_MODEL_MAP)

# Salted so the ramp bucket is independent of other user-hash rollouts.
_TRAFFIC_BUCKET_SALT = "glm-modal-routing"


def is_modal_served_model(model: str) -> bool:
    return model in MODAL_MODEL_MAP


def modal_litellm_model(model: str) -> str:
    return f"{_MODAL_LITELLM_PREFIX}{MODAL_MODEL_MAP[model]}"


def is_modal_configured(settings: Settings) -> bool:
    return bool(settings.modal_api_base and settings.modal_key and settings.modal_secret)


def ensure_modal_configured(settings: Settings) -> tuple[str, str, str]:
    if not is_modal_configured(settings):
        raise HTTPException(
            status_code=503,
            detail={"error": {"message": "Modal inference not configured", "type": "configuration_error"}},
        )
    assert settings.modal_api_base is not None and settings.modal_key is not None and settings.modal_secret is not None
    return settings.modal_api_base, settings.modal_key, settings.modal_secret


def ensure_modal_model_allowed(model: str) -> None:
    if model not in MODAL_ALLOWED_MODELS:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "message": f"Model '{model}' is not supported on the modal provider",
                    "type": "invalid_request_error",
                }
            },
        )


def _traffic_bucket(user_key: str) -> float:
    digest = hashlib.sha256(f"{_TRAFFIC_BUCKET_SALT}:{user_key}".encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2**64


def modal_traffic_fraction(product: str, settings: Settings) -> float:
    # Legacy product aliases (twig/array) must read their canonical product's fraction.
    product = _normalize_cost_key(product)
    return settings.glm_modal_product_traffic_fractions.get(product, settings.glm_modal_traffic_fraction)


def should_route_glm_to_modal(model: str, *, product: str, user_key: str, settings: Settings) -> bool:
    """Env-fraction opt-in; bucketing is per user so a session sticks to one backend."""
    if not is_modal_served_model(model) or not is_modal_configured(settings):
        return False
    fraction = modal_traffic_fraction(product, settings)
    if fraction <= 0.0:
        return False
    if fraction >= 1.0:
        return True
    return _traffic_bucket(user_key) < fraction


def _inject_modal_params(kwargs: dict[str, Any], api_base: str, modal_key: str, modal_secret: str) -> None:
    kwargs["api_base"] = api_base
    kwargs["api_key"] = _MODAL_PLACEHOLDER_API_KEY
    # Never forward caller-supplied headers/extra_headers: both arrive as extra-allowed request
    # body fields and litellm merges caller `headers` with `extra_headers` into the outbound
    # request, so e.g. a caller Host header would steer this authenticated request (and the
    # proxy-token pair) to an attacker-controlled endpoint.
    kwargs.pop("headers", None)
    kwargs["extra_headers"] = {"Modal-Key": modal_key, "Modal-Secret": modal_secret}
    kwargs["model"] = modal_litellm_model(kwargs["model"])
    # The OpenAI-compatible surface rejects provider-specific params (see cloudflare.py).
    kwargs.setdefault("drop_params", True)


def make_modal_anthropic_call(api_base: str, modal_key: str, modal_secret: str) -> Callable[..., Awaitable[Any]]:
    async def llm_call(**kwargs: Any) -> Any:
        _inject_modal_params(kwargs, api_base, modal_key, modal_secret)
        return await LiteLLMMessagesToCompletionTransformationHandler.async_anthropic_messages_handler(**kwargs)

    return llm_call


def make_modal_completion_call(api_base: str, modal_key: str, modal_secret: str) -> Callable[..., Awaitable[Any]]:
    async def llm_call(**kwargs: Any) -> Any:
        _inject_modal_params(kwargs, api_base, modal_key, modal_secret)
        return await litellm.acompletion(**kwargs)

    return llm_call


def make_modal_responses_call(api_base: str, modal_key: str, modal_secret: str) -> Callable[..., Awaitable[Any]]:
    """vLLM has no /responses route — force litellm's bridge, same as make_cloudflare_responses_call."""

    async def llm_call(**kwargs: Any) -> Any:
        _inject_modal_params(kwargs, api_base, modal_key, modal_secret)
        kwargs["use_chat_completions_api"] = True
        return await litellm.aresponses(**kwargs)

    return llm_call
