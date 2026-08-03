from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import litellm
from fastapi import HTTPException
from litellm.llms.anthropic.experimental_pass_through.adapters.handler import (
    LiteLLMMessagesToCompletionTransformationHandler,
)

from llm_gateway.anthropic_stream import observe_anthropic_stream
from llm_gateway.config import Settings

BASETEN_PUBLIC_MODEL = "@cf/zai-org/glm-5.2"
BASETEN_GLM_MODEL = "zai-org/GLM-5.2"
BASETEN_METRIC_MODEL = "baseten/zai-org/glm-5.2"
_BASETEN_LITELLM_MODEL = f"openai/{BASETEN_GLM_MODEL}"


def is_baseten_configured(settings: Settings) -> bool:
    return bool(settings.baseten_api_base and settings.baseten_api_key)


def ensure_baseten_configured(settings: Settings) -> tuple[str, str]:
    if not is_baseten_configured(settings):
        raise HTTPException(
            status_code=503,
            detail={"error": {"message": "Baseten inference not configured", "type": "configuration_error"}},
        )
    assert settings.baseten_api_base is not None and settings.baseten_api_key is not None
    return settings.baseten_api_base, settings.baseten_api_key


def _inject_baseten_params(kwargs: dict[str, Any], api_base: str, api_key: str) -> None:
    kwargs["api_base"] = api_base
    kwargs["api_key"] = api_key
    kwargs.pop("headers", None)
    kwargs["extra_headers"] = {"Authorization": f"Api-Key {api_key}"}
    kwargs["model"] = _BASETEN_LITELLM_MODEL
    kwargs.setdefault("drop_params", True)
    if kwargs.get("stream"):
        stream_options = dict(kwargs.get("stream_options") or {})
        stream_options.update(include_usage=True, continuous_usage_stats=True)
        kwargs["stream_options"] = stream_options


def make_baseten_anthropic_call(api_base: str, api_key: str) -> Callable[..., Awaitable[Any]]:
    async def llm_call(**kwargs: Any) -> Any:
        _inject_baseten_params(kwargs, api_base, api_key)
        response = await LiteLLMMessagesToCompletionTransformationHandler.async_anthropic_messages_handler(**kwargs)
        if isinstance(response, AsyncIterator):
            return observe_anthropic_stream(response, "baseten")
        return response

    return llm_call


def make_baseten_completion_call(api_base: str, api_key: str) -> Callable[..., Awaitable[Any]]:
    async def llm_call(**kwargs: Any) -> Any:
        _inject_baseten_params(kwargs, api_base, api_key)
        return await litellm.acompletion(**kwargs)

    return llm_call


def make_baseten_responses_call(api_base: str, api_key: str) -> Callable[..., Awaitable[Any]]:
    async def llm_call(**kwargs: Any) -> Any:
        _inject_baseten_params(kwargs, api_base, api_key)
        kwargs["use_chat_completions_api"] = True
        return await litellm.aresponses(**kwargs)

    return llm_call
