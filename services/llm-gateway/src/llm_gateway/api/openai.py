from typing import Any

import litellm
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from llm_gateway.api.handler import OPENAI_CONFIG, OPENAI_RESPONSES_CONFIG, handle_llm_request
from llm_gateway.api.products import validate_product
from llm_gateway.dependencies import RateLimitedUser
from llm_gateway.models.openai import ChatCompletionRequest, ResponsesRequest

openai_router = APIRouter()


def _normalize_model_name(model: str) -> str:
    """Ensure model name has openai/ prefix for litellm routing."""
    if model.startswith("openai/"):
        return model
    return f"openai/{model}"


async def _handle_chat_completions(
    body: ChatCompletionRequest,
    user: RateLimitedUser,
    product: str = "llm_gateway",
) -> dict[str, Any] | StreamingResponse:
    data = body.model_dump(exclude_none=True)

    return await handle_llm_request(
        request_data=data,
        user=user,
        model=body.model,
        is_streaming=body.stream or False,
        provider_config=OPENAI_CONFIG,
        llm_call=litellm.acompletion,
        product=product,
    )


async def _handle_responses(
    body: ResponsesRequest,
    user: RateLimitedUser,
    product: str = "llm_gateway",
) -> dict[str, Any] | StreamingResponse:
    """Handle OpenAI Responses API request.

    The Responses API is used by Codex and other agentic applications.
    It supports multimodal inputs, reasoning models, and persistent conversations.
    """
    data = body.model_dump(exclude_none=True)

    original_model = body.model
    normalized_model = _normalize_model_name(original_model)
    data["model"] = normalized_model

    try:
        result = await handle_llm_request(
            request_data=data,
            user=user,
            model=normalized_model,
            is_streaming=body.stream or False,
            provider_config=OPENAI_RESPONSES_CONFIG,
            llm_call=litellm.aresponses,
            product=product,
        )
        return result
    except Exception:
        raise


@openai_router.post("/v1/chat/completions", response_model=None)
async def chat_completions(
    body: ChatCompletionRequest,
    user: RateLimitedUser,
) -> dict[str, Any] | StreamingResponse:
    return await _handle_chat_completions(body, user)


@openai_router.post("/{product}/v1/chat/completions", response_model=None)
async def chat_completions_with_product(
    body: ChatCompletionRequest,
    user: RateLimitedUser,
    product: str,
) -> dict[str, Any] | StreamingResponse:
    validate_product(product)
    return await _handle_chat_completions(body, user, product=product)


@openai_router.post("/v1/responses", response_model=None)
async def responses_v1(
    body: ResponsesRequest,
    user: RateLimitedUser,
) -> dict[str, Any] | StreamingResponse:
    return await _handle_responses(body, user)


@openai_router.post("/{product}/v1/responses", response_model=None)
async def responses_v1_with_product(
    body: ResponsesRequest,
    user: RateLimitedUser,
    product: str,
) -> dict[str, Any] | StreamingResponse:
    validate_product(product)
    return await _handle_responses(body, user, product=product)


@openai_router.post("/responses", response_model=None)
async def responses(
    body: ResponsesRequest,
    user: RateLimitedUser,
) -> dict[str, Any] | StreamingResponse:
    return await _handle_responses(body, user)


@openai_router.post("/{product}/responses", response_model=None)
async def responses_with_product(
    body: ResponsesRequest,
    user: RateLimitedUser,
    product: str,
) -> dict[str, Any] | StreamingResponse:
    validate_product(product)
    return await _handle_responses(body, user, product=product)
