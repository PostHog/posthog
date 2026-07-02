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

# CF has no native litellm provider; we route through its OpenAI-compatible endpoint.
_CF_LITELLM_PREFIX = "openai/"

# CF Workers AI model ids are namespaced under `@cf/` (e.g. `@cf/zai-org/glm-5.2`). The id alone is
# what marks a request for CF routing across every gateway path — chat/completions, responses, and
# anthropic-messages all branch on this, independent of the provider header.
_CF_MODEL_PREFIX = "@cf/"


def is_cloudflare_model(model: str) -> bool:
    """Whether `model` is a Cloudflare Workers AI model id (`@cf/...`)."""
    return model.startswith(_CF_MODEL_PREFIX)


def cloudflare_litellm_model(model: str) -> str:
    """The litellm model id CF requests route under (its OpenAI-compatible prefix)."""
    return f"{_CF_LITELLM_PREFIX}{model}"


# Restrict `@cf/...` routing to models we've priced in COST_ALIASES. Unpriced models fall through
# to `default_fallback_cost_usd`, so the gateway would eat the real CF bill while charging the user
# a flat fallback. Derived from COST_ALIASES so the two can't drift — registering an alias auto-allows
# it, and you can't route a model without pricing it first.
CLOUDFLARE_ALLOWED_MODELS: frozenset[str] = frozenset(
    alias.removeprefix(_CF_LITELLM_PREFIX) for alias in COST_ALIASES if alias.startswith(f"{_CF_LITELLM_PREFIX}@cf/")
)


def cloudflare_api_base(account_id: str) -> str:
    return f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1"


def is_cloudflare_configured(settings: Settings) -> bool:
    """Whether both Cloudflare credentials (API key + account id) are present."""
    return bool(settings.cloudflare_api_key and settings.cloudflare_account_id)


def ensure_cloudflare_configured(settings: Settings) -> tuple[str, str]:
    """Validate Cloudflare credentials and return (api_base, api_key)."""
    if not is_cloudflare_configured(settings):
        raise HTTPException(
            status_code=503,
            detail={"error": {"message": "Cloudflare Workers AI not configured", "type": "configuration_error"}},
        )
    # Narrowed by is_cloudflare_configured above; assert restates it for the type checker.
    assert settings.cloudflare_api_key is not None and settings.cloudflare_account_id is not None
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
    kwargs["model"] = cloudflare_litellm_model(kwargs["model"])
    # CF Workers AI is reached through litellm's OpenAI-compatible surface, which rejects
    # provider-specific params a caller's runtime sends (e.g. Anthropic's reasoning_effort /
    # context_management). Drop the unsupported ones instead of failing the request.
    kwargs.setdefault("drop_params", True)


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


def make_cloudflare_responses_call(api_base: str, api_key: str) -> Callable[..., Awaitable[Any]]:
    """Build an llm_call that routes OpenAI Responses API requests to Cloudflare.

    CF's OpenAI-compatible endpoint only serves chat/completions, not the Responses API,
    so we force litellm's Responses->chat/completions bridge (`use_chat_completions_api`)
    and route the bridged completion through CF's endpoint. Without this, `litellm.aresponses`
    would hit CF's non-existent `/responses` route. This is the codex/Responses analogue of
    `make_cloudflare_completion_call` (chat/completions) and `make_cloudflare_anthropic_call`
    (Anthropic Messages).
    """

    async def llm_call(**kwargs: Any) -> Any:
        _inject_cloudflare_params(kwargs, api_base, api_key)
        # Assign into kwargs rather than passing as an explicit keyword: `ResponsesRequest` allows
        # extra fields, so a caller could smuggle `use_chat_completions_api` in the request body —
        # passing it both ways would raise `TypeError: got multiple values for keyword argument`,
        # and this also stops a caller flipping it to False to escape the bridge onto CF's missing
        # /responses route.
        kwargs["use_chat_completions_api"] = True
        return await litellm.aresponses(**kwargs)

    return llm_call
