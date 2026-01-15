from typing import Any

import litellm
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from llm_gateway.api.handler import ANTHROPIC_CONFIG, handle_llm_request
from llm_gateway.api.products import validate_product
from llm_gateway.dependencies import RateLimitedUser
from llm_gateway.models.anthropic import AnthropicMessagesRequest

anthropic_router = APIRouter()


async def _handle_anthropic_messages(
    body: AnthropicMessagesRequest,
    user: RateLimitedUser,
    http_request: Request,
    product: str = "llm_gateway",
) -> dict[str, Any] | StreamingResponse:
    data = body.model_dump(exclude_none=True)

    return await handle_llm_request(
        request_data=data,
        user=user,
        model=body.model,
        is_streaming=body.stream or False,
        provider_config=ANTHROPIC_CONFIG,
        llm_call=litellm.anthropic_messages,
        product=product,
        http_request=http_request,
    )


@anthropic_router.post("/v1/messages", response_model=None)
async def anthropic_messages(
    body: AnthropicMessagesRequest,
    user: RateLimitedUser,
    request: Request,
) -> dict[str, Any] | StreamingResponse:
    return await _handle_anthropic_messages(body, user, request)


@anthropic_router.post("/{product}/v1/messages", response_model=None)
async def anthropic_messages_with_product(
    body: AnthropicMessagesRequest,
    user: RateLimitedUser,
    request: Request,
    product: str,
) -> dict[str, Any] | StreamingResponse:
    validate_product(product)
    return await _handle_anthropic_messages(body, user, request, product=product)
