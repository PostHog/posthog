from typing import Any

import litellm
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from llm_gateway.api.handler import OPENAI_CONFIG, OPENAI_RESPONSES_CONFIG, handle_llm_request
from llm_gateway.dependencies import RateLimitedUser
from llm_gateway.models.openai import ChatCompletionRequest, ResponsesRequest

openai_router = APIRouter()


@openai_router.post("/v1/chat/completions", response_model=None)
async def chat_completions(
    request: ChatCompletionRequest,
    user: RateLimitedUser,
) -> dict[str, Any] | StreamingResponse:
    data = request.model_dump(exclude_none=True)

    return await handle_llm_request(
        request_data=data,
        user=user,
        model=request.model,
        is_streaming=request.stream or False,
        provider_config=OPENAI_CONFIG,
        llm_call=litellm.acompletion,
    )


def _normalize_model_name(model: str) -> str:
    """Ensure model name has openai/ prefix for litellm routing."""
    if model.startswith("openai/"):
        return model
    return f"openai/{model}"


async def _handle_responses(
    request: ResponsesRequest,
    user: RateLimitedUser,
) -> dict[str, Any] | StreamingResponse:
    """Handle OpenAI Responses API request.

    The Responses API is used by Codex and other agentic applications.
    It supports multimodal inputs, reasoning models, and persistent conversations.
    """
    data = request.model_dump(exclude_none=True)

    # Normalize model name for litellm routing
    original_model = request.model
    normalized_model = _normalize_model_name(original_model)
    data["model"] = normalized_model

    try:
        result = await handle_llm_request(
            request_data=data,
            user=user,
            model=normalized_model,
            is_streaming=request.stream or False,
            provider_config=OPENAI_RESPONSES_CONFIG,
            llm_call=litellm.aresponses,
        )
        return result
    except Exception:
        raise


# Support both /v1/responses and /responses paths
# The Codex SDK may call either depending on how OPENAI_BASE_URL is configured
@openai_router.post("/v1/responses", response_model=None)
async def responses_v1(
    request: ResponsesRequest,
    user: RateLimitedUser,
) -> dict[str, Any] | StreamingResponse:
    return await _handle_responses(request, user)


@openai_router.post("/responses", response_model=None)
async def responses(
    request: ResponsesRequest,
    user: RateLimitedUser,
) -> dict[str, Any] | StreamingResponse:
    return await _handle_responses(request, user)
