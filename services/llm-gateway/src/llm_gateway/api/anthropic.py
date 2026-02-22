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


def _anthropic_messages_to_openai(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert Anthropic message format to OpenAI chat format.

    Anthropic uses content blocks (list of dicts with type/text) while OpenAI
    uses plain strings or content arrays. This handles the common cases.
    """
    converted = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content")

        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        parts.append(block.get("text", ""))
                    elif block.get("type") == "image":
                        parts.append({"type": "image_url", "image_url": block.get("source", {})})
                elif isinstance(block, str):
                    parts.append(block)
            content = "\n".join(parts) if all(isinstance(p, str) for p in parts) else parts

        converted.append({"role": role, "content": content})

    return converted


async def _handle_anthropic_messages(
    body: AnthropicMessagesRequest,
    user: RateLimitedUser,
    product: str = "llm_gateway",
) -> dict[str, Any] | StreamingResponse:
    hosted = resolve_hosted_model(body.model)
    if hosted:
        litellm_model, api_base = hosted
        openai_messages = _anthropic_messages_to_openai(body.messages)
        data = {
            "model": litellm_model,
            "messages": openai_messages,
            "max_tokens": body.max_tokens,
            "stream": body.stream or False,
            "api_base": api_base,
        }
        extra = body.model_dump(exclude_none=True, exclude={"model", "messages", "max_tokens", "stream"})
        data.update(extra)

        return await handle_llm_request(
            request_data=data,
            user=user,
            model=body.model,
            is_streaming=body.stream or False,
            provider_config=HOSTED_VLLM_CONFIG,
            llm_call=litellm.acompletion,
            product=product,
        )

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
