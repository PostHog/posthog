import time
from typing import Any

import litellm
import structlog
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from llm_gateway.api.bedrock import count_tokens_with_bedrock, ensure_bedrock_configured, map_anthropic_model_to_bedrock
from llm_gateway.api.handler import BEDROCK_CONFIG, handle_llm_request
from llm_gateway.config import get_settings
from llm_gateway.dependencies import RateLimitedUser
from llm_gateway.metrics.prometheus import REQUEST_COUNT, REQUEST_LATENCY
from llm_gateway.models.anthropic import AnthropicCountTokensRequest, AnthropicMessagesRequest
from llm_gateway.products.config import validate_product
from llm_gateway.request_context import set_posthog_flags, set_posthog_properties

logger = structlog.get_logger(__name__)

bedrock_router = APIRouter()

POSTHOG_PROPERTY_PREFIX = "x-posthog-property-"
POSTHOG_FLAG_PREFIX = "x-posthog-flag-"
COUNT_TOKENS_ENDPOINT_NAME = "bedrock_count_tokens"


def _extract_headers_with_prefix(request: Request, prefix: str) -> dict[str, str]:
    result: dict[str, str] = {}
    prefix_lower = prefix.lower()
    for name, value in request.headers.items():
        if name.lower().startswith(prefix_lower):
            key = name[len(prefix) :].lower()
            result[key] = value
    return result


def _extract_posthog_properties_from_headers(request: Request) -> dict[str, str]:
    return _extract_headers_with_prefix(request, POSTHOG_PROPERTY_PREFIX)


def _extract_posthog_flags_from_headers(request: Request) -> dict[str, str]:
    return _extract_headers_with_prefix(request, POSTHOG_FLAG_PREFIX)


async def _handle_bedrock_messages(
    body: AnthropicMessagesRequest,
    user: RateLimitedUser,
    product: str = "llm_gateway",
) -> dict[str, Any] | StreamingResponse:
    settings = get_settings()
    ensure_bedrock_configured(settings)

    data = body.model_dump(exclude_none=True)
    data["model"] = map_anthropic_model_to_bedrock(body.model)
    data["aws_region_name"] = settings.bedrock_region_name

    return await handle_llm_request(
        request_data=data,
        user=user,
        model=data["model"],
        is_streaming=body.stream or False,
        provider_config=BEDROCK_CONFIG,
        llm_call=litellm.anthropic_messages,
        product=product,
    )


async def _handle_count_tokens(
    body: AnthropicCountTokensRequest,
    user: RateLimitedUser,
    product: str = "llm_gateway",
) -> dict[str, Any]:
    settings = get_settings()
    ensure_bedrock_configured(settings)

    start_time = time.monotonic()
    status_code = "200"
    data = body.model_dump(exclude_none=True)
    mapped_model = map_anthropic_model_to_bedrock(body.model)

    try:
        input_tokens = count_tokens_with_bedrock(data["messages"], body.model, settings.bedrock_region_name)
        return {"input_tokens": input_tokens}
    except HTTPException as e:
        status_code = str(e.status_code)
        raise
    except Exception as e:
        status_code = "502"
        logger.exception(f"Error proxying bedrock count_tokens request: {e}")
        raise HTTPException(
            status_code=502,
            detail={"error": {"message": "Failed to count tokens via Bedrock", "type": "proxy_error"}},
        ) from e
    finally:
        REQUEST_COUNT.labels(
            endpoint=COUNT_TOKENS_ENDPOINT_NAME,
            provider="bedrock",
            model=mapped_model,
            status_code=status_code,
            auth_method=user.auth_method,
            product=product,
        ).inc()
        REQUEST_LATENCY.labels(
            endpoint=COUNT_TOKENS_ENDPOINT_NAME,
            provider="bedrock",
            streaming="false",
            product=product,
        ).observe(time.monotonic() - start_time)


@bedrock_router.post("/bedrock/v1/messages/count_tokens", response_model=None)
async def bedrock_count_tokens(
    body: AnthropicCountTokensRequest,
    user: RateLimitedUser,
) -> dict[str, Any]:
    return await _handle_count_tokens(body, user)


@bedrock_router.post("/{product}/bedrock/v1/messages/count_tokens", response_model=None)
async def bedrock_count_tokens_with_product(
    body: AnthropicCountTokensRequest,
    user: RateLimitedUser,
    product: str,
) -> dict[str, Any]:
    validate_product(product)
    return await _handle_count_tokens(body, user, product=product)


@bedrock_router.post("/bedrock/v1/messages", response_model=None)
async def bedrock_messages(
    body: AnthropicMessagesRequest,
    user: RateLimitedUser,
    request: Request,
) -> dict[str, Any] | StreamingResponse:
    properties = _extract_posthog_properties_from_headers(request)
    if properties:
        set_posthog_properties(properties)
    flags = _extract_posthog_flags_from_headers(request)
    if flags:
        set_posthog_flags(flags)
    return await _handle_bedrock_messages(body, user)


@bedrock_router.post("/{product}/bedrock/v1/messages", response_model=None)
async def bedrock_messages_with_product(
    body: AnthropicMessagesRequest,
    user: RateLimitedUser,
    product: str,
    request: Request,
) -> dict[str, Any] | StreamingResponse:
    validate_product(product)
    properties = _extract_posthog_properties_from_headers(request)
    if properties:
        set_posthog_properties(properties)
    flags = _extract_posthog_flags_from_headers(request)
    if flags:
        set_posthog_flags(flags)
    return await _handle_bedrock_messages(body, user, product=product)
