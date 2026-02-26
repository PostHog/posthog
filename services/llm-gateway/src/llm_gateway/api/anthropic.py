from typing import Any

import litellm
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from llm_gateway.api.handler import ANTHROPIC_CONFIG, handle_llm_request
from llm_gateway.dependencies import RateLimitedUser
from llm_gateway.models.anthropic import AnthropicMessagesRequest
from llm_gateway.products.config import validate_product
from llm_gateway.request_context import set_posthog_flags, set_posthog_properties

anthropic_router = APIRouter()

POSTHOG_PROPERTY_PREFIX = "x-posthog-property-"
POSTHOG_FLAG_PREFIX = "x-posthog-flag-"


def _extract_headers_with_prefix(request: Request, prefix: str) -> dict[str, str]:
    """Extract headers whose name (lowercased) starts with prefix; key = remainder after prefix, lowercased."""
    result: dict[str, str] = {}
    prefix_lower = prefix.lower()
    for name, value in request.headers.items():
        if name.lower().startswith(prefix_lower):
            key = name[len(prefix) :].lower()
            result[key] = value
    return result


def extract_posthog_properties_from_headers(request: Request) -> dict[str, str]:
    return _extract_headers_with_prefix(request, POSTHOG_PROPERTY_PREFIX)


def extract_posthog_flags_from_headers(request: Request) -> dict[str, str]:
    return _extract_headers_with_prefix(request, POSTHOG_FLAG_PREFIX)


async def _handle_anthropic_messages(
    body: AnthropicMessagesRequest,
    user: RateLimitedUser,
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
    )


@anthropic_router.post("/v1/messages", response_model=None)
async def anthropic_messages(
    body: AnthropicMessagesRequest,
    user: RateLimitedUser,
    request: Request,
) -> dict[str, Any] | StreamingResponse:
    properties = extract_posthog_properties_from_headers(request)
    if properties:
        set_posthog_properties(properties)
    flags = extract_posthog_flags_from_headers(request)
    if flags:
        set_posthog_flags(flags)
    return await _handle_anthropic_messages(body, user)


@anthropic_router.post("/{product}/v1/messages", response_model=None)
async def anthropic_messages_with_product(
    body: AnthropicMessagesRequest,
    user: RateLimitedUser,
    product: str,
    request: Request,
) -> dict[str, Any] | StreamingResponse:
    validate_product(product)
    properties = extract_posthog_properties_from_headers(request)
    if properties:
        set_posthog_properties(properties)
    flags = extract_posthog_flags_from_headers(request)
    if flags:
        set_posthog_flags(flags)
    return await _handle_anthropic_messages(body, user, product=product)
