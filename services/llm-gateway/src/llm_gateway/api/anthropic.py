from typing import Any

import litellm
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from llm_gateway.api.handler import ANTHROPIC_CONFIG, handle_llm_request
from llm_gateway.dependencies import RateLimitedUser
from llm_gateway.models.anthropic import AnthropicMessagesRequest
from llm_gateway.products.config import validate_product
from llm_gateway.request_context import set_wizard_flags, set_wizard_metadata

anthropic_router = APIRouter()

WIZARD_META_PREFIX = "x-wizard-meta-"
WIZARD_FLAG_PREFIX = "x-wizard-flag-"


def extract_wizard_meta_from_headers(request: Request) -> dict[str, str]:
    """Extract X-WIZARD-META-* headers; key = part after X- lowercased, value = header value."""
    meta: dict[str, str] = {}
    for name, value in request.headers.items():
        if name.lower().startswith(WIZARD_META_PREFIX):
            key = name[len("x-") :].lower()
            meta[key] = value
    return meta


def extract_wizard_flags_from_headers(request: Request) -> dict[str, str]:
    """Extract X-WIZARD-FLAG-* headers; key = flag name (part after prefix) lowercased, value = flag value."""
    flags: dict[str, str] = {}
    for name, value in request.headers.items():
        if name.lower().startswith(WIZARD_FLAG_PREFIX):
            key = name[len(WIZARD_FLAG_PREFIX) :].lower()
            flags[key] = value
    return flags


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
    meta = extract_wizard_meta_from_headers(request)
    if meta:
        set_wizard_metadata(meta)
    flags = extract_wizard_flags_from_headers(request)
    if flags:
        set_wizard_flags(flags)
    return await _handle_anthropic_messages(body, user)


@anthropic_router.post("/{product}/v1/messages", response_model=None)
async def anthropic_messages_with_product(
    body: AnthropicMessagesRequest,
    user: RateLimitedUser,
    product: str,
    request: Request,
) -> dict[str, Any] | StreamingResponse:
    validate_product(product)
    meta = extract_wizard_meta_from_headers(request)
    if meta:
        set_wizard_metadata(meta)
    flags = extract_wizard_flags_from_headers(request)
    if flags:
        set_wizard_flags(flags)
    return await _handle_anthropic_messages(body, user, product=product)
