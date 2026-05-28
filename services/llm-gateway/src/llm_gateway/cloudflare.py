from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import litellm
from fastapi import HTTPException
from litellm.llms.anthropic.experimental_pass_through.adapters.handler import (
    LiteLLMMessagesToCompletionTransformationHandler,
)

from llm_gateway.config import Settings


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
