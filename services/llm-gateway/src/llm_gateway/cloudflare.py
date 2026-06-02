from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import litellm
from fastapi import HTTPException

# Experimental litellm path — `tests/test_cloudflare.py` has a contract test that fails fast on a rename.
from litellm.llms.anthropic.experimental_pass_through.adapters.handler import (
    LiteLLMMessagesToCompletionTransformationHandler,
)

from llm_gateway.config import Settings
from llm_gateway.rate_limiting.cost_refresh import COST_ALIASES

# Restrict `@cf/...` routing to models we've priced in COST_ALIASES. Unpriced models fall through
# to `default_fallback_cost_usd`, so the gateway would eat the real CF bill while charging the user
# a flat fallback. Derived from COST_ALIASES so the two can't drift — registering an alias auto-allows
# it, and you can't route a model without pricing it first.
CLOUDFLARE_ALLOWED_MODELS: frozenset[str] = frozenset(
    alias.removeprefix("openai/") for alias in COST_ALIASES if alias.startswith("openai/@cf/")
)


def cloudflare_api_base(account_id: str) -> str:
    return f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1"


def ensure_cloudflare_configured(settings: Settings) -> tuple[str, str]:
    """Validate Cloudflare credentials and return (api_base, api_key)."""
    if not settings.cloudflare_api_key or not settings.cloudflare_account_id:
        raise HTTPException(
            status_code=503,
            detail={"error": {"message": "Cloudflare Workers AI not configured", "type": "configuration_error"}},
        )
    return cloudflare_api_base(settings.cloudflare_account_id), settings.cloudflare_api_key


def ensure_cloudflare_model_allowed(model: str) -> None:
    """Reject CF models we haven't explicitly priced — see CLOUDFLARE_ALLOWED_MODELS."""
    if model not in CLOUDFLARE_ALLOWED_MODELS:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "message": f"Model '{model}' is not supported on the cloudflare provider",
                    "type": "invalid_request_error",
                }
            },
        )


def _inject_cloudflare_params(kwargs: dict[str, Any], api_base: str, api_key: str) -> None:
    kwargs["api_base"] = api_base
    kwargs["api_key"] = api_key
    kwargs["model"] = f"openai/{kwargs['model']}"


def make_cloudflare_anthropic_call(api_base: str, api_key: str) -> Callable[..., Awaitable[Any]]:
    """Build an llm_call that adapts Anthropic Messages format to Cloudflare Workers AI.

    Uses litellm's built-in adapter to translate Anthropic <-> OpenAI chat/completions
    format, routing through CF's OpenAI-compatible endpoint.
    """

    async def llm_call(**kwargs: Any) -> Any:
        _inject_cloudflare_params(kwargs, api_base, api_key)
        return await LiteLLMMessagesToCompletionTransformationHandler.async_anthropic_messages_handler(**kwargs)

    return llm_call


def make_cloudflare_completion_call(api_base: str, api_key: str) -> Callable[..., Awaitable[Any]]:
    """Build an llm_call that routes OpenAI chat/completions requests to Cloudflare."""

    async def llm_call(**kwargs: Any) -> Any:
        _inject_cloudflare_params(kwargs, api_base, api_key)
        return await litellm.acompletion(**kwargs)

    return llm_call
