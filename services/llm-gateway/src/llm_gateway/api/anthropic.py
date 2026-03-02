import time
from typing import Any

import httpx
import litellm
import structlog
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from llm_gateway.api.handler import ANTHROPIC_CONFIG, handle_llm_request
from llm_gateway.config import get_settings
from llm_gateway.dependencies import RateLimitedUser
from llm_gateway.metrics.prometheus import REQUEST_COUNT, REQUEST_LATENCY
from llm_gateway.models.anthropic import AnthropicCountTokensRequest, AnthropicMessagesRequest
from llm_gateway.products.config import validate_product

logger = structlog.get_logger(__name__)

anthropic_router = APIRouter()

ANTHROPIC_COUNT_TOKENS_URL = "https://api.anthropic.com/v1/messages/count_tokens"
ANTHROPIC_API_VERSION = "2023-06-01"
COUNT_TOKENS_ENDPOINT_NAME = "anthropic_count_tokens"


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


async def _handle_count_tokens(
    body: AnthropicCountTokensRequest,
    user: RateLimitedUser,
    product: str = "llm_gateway",
) -> dict[str, Any]:
    settings = get_settings()
    start_time = time.monotonic()
    status_code = "200"

    api_key = settings.anthropic_api_key
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail={"error": {"message": "Anthropic API key not configured", "type": "configuration_error"}},
        )

    data = body.model_dump(exclude_none=True)

    headers = {
        "x-api-key": api_key,
        "anthropic-version": ANTHROPIC_API_VERSION,
        "content-type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=settings.request_timeout) as client:
            response = await client.post(
                ANTHROPIC_COUNT_TOKENS_URL,
                json=data,
                headers=headers,
            )

        if response.status_code != 200:
            status_code = str(response.status_code)
            try:
                error_body = response.json()
            except Exception:
                error_body = {"error": {"message": response.text, "type": "api_error"}}
            raise HTTPException(status_code=response.status_code, detail=error_body)

        return response.json()

    except HTTPException:
        raise
    except Exception as e:
        status_code = "502"
        logger.exception(f"Error proxying count_tokens request: {e}")
        raise HTTPException(
            status_code=502,
            detail={"error": {"message": "Failed to proxy request to Anthropic", "type": "proxy_error"}},
        ) from e
    finally:
        REQUEST_COUNT.labels(
            endpoint=COUNT_TOKENS_ENDPOINT_NAME,
            provider="anthropic",
            model=body.model,
            status_code=status_code,
            auth_method=user.auth_method,
            product=product,
        ).inc()
        REQUEST_LATENCY.labels(
            endpoint=COUNT_TOKENS_ENDPOINT_NAME,
            provider="anthropic",
            streaming="false",
            product=product,
        ).observe(time.monotonic() - start_time)


@anthropic_router.post("/v1/messages/count_tokens", response_model=None)
async def anthropic_count_tokens(
    body: AnthropicCountTokensRequest,
    user: RateLimitedUser,
) -> dict[str, Any]:
    return await _handle_count_tokens(body, user)


@anthropic_router.post("/{product}/v1/messages/count_tokens", response_model=None)
async def anthropic_count_tokens_with_product(
    body: AnthropicCountTokensRequest,
    user: RateLimitedUser,
    product: str,
) -> dict[str, Any]:
    validate_product(product)
    return await _handle_count_tokens(body, user, product=product)


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
