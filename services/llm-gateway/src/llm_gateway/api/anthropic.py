from typing import Any

import litellm
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from llm_gateway.api.handler import ANTHROPIC_CONFIG, HOSTED_VLLM_CONFIG, handle_llm_request
from llm_gateway.dependencies import RateLimitedUser
from llm_gateway.models.anthropic import AnthropicMessagesRequest
from llm_gateway.products.config import validate_product
from llm_gateway.services.hosted_models import resolve_hosted_model

anthropic_router = APIRouter()


async def _handle_anthropic_messages(
    body: AnthropicMessagesRequest,
    user: RateLimitedUser,
    product: str = "llm_gateway",
) -> dict[str, Any] | StreamingResponse:
    hosted = resolve_hosted_model(body.model)
    if hosted:
        litellm_model, api_base = hosted
        return await _handle_hosted_via_openai(body, litellm_model, api_base, user, product)

    data = body.model_dump(exclude_none=True)
    return await handle_llm_request(
        request_data=data,
        user=user,
        model=body.model,
        is_streaming=body.stream or False,
        provider_config=ANTHROPIC_CONFIG,
        llm_call=litellm.anthropic_messages,
        product=product,
    )


async def _handle_hosted_via_openai(
    body: AnthropicMessagesRequest,
    litellm_model: str,
    api_base: str,
    user: RateLimitedUser,
    product: str,
) -> dict[str, Any] | StreamingResponse:
    """Route an Anthropic-format request to a hosted vLLM endpoint via acompletion.

    Anthropic and OpenAI share the same messages array shape (role + content),
    so messages pass through directly. The only structural difference is
    Anthropic's top-level `system` field, which we prepend as a system message.
    """
    extras = body.model_dump(exclude_none=True, exclude={"model", "messages", "max_tokens", "stream"})
    system_text = extras.pop("system", None)

    messages: list[dict[str, Any]] = list(body.messages)
    if system_text:
        messages.insert(0, {"role": "system", "content": system_text})

    data: dict[str, Any] = {
        "model": litellm_model,
        "messages": messages,
        "max_tokens": body.max_tokens,
        "stream": body.stream or False,
        "api_base": api_base,
    }
    for key in ("temperature", "top_p", "stop"):
        if key in extras:
            data[key] = extras[key]

    return await handle_llm_request(
        request_data=data,
        user=user,
        model=body.model,
        is_streaming=body.stream or False,
        provider_config=HOSTED_VLLM_CONFIG,
        llm_call=litellm.acompletion,
        product=product,
    )


@anthropic_router.post("/v1/messages", response_model=None)
async def anthropic_messages(
    body: AnthropicMessagesRequest,
    user: RateLimitedUser,
) -> dict[str, Any] | StreamingResponse:
    return await _handle_anthropic_messages(body, user)


@anthropic_router.post("/{product}/v1/messages", response_model=None)
async def anthropic_messages_with_product(
    body: AnthropicMessagesRequest,
    user: RateLimitedUser,
    product: str,
) -> dict[str, Any] | StreamingResponse:
    validate_product(product)
    return await _handle_anthropic_messages(body, user, product=product)
