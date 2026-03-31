import functools
import json
import time
from typing import Any

import boto3
import httpx
import litellm
import structlog
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from llm_gateway.api.handler import ANTHROPIC_CONFIG, BEDROCK_CONFIG, handle_llm_request
from llm_gateway.config import get_settings
from llm_gateway.dependencies import RateLimitedUser
from llm_gateway.metrics.prometheus import (
    BEDROCK_FALLBACK_FAILURE,
    BEDROCK_FALLBACK_SUCCESS,
    BEDROCK_FALLBACK_TRIGGERED,
    REQUEST_COUNT,
    REQUEST_LATENCY,
)
from llm_gateway.models.anthropic import GATEWAY_ONLY_FIELDS, AnthropicCountTokensRequest, AnthropicMessagesRequest
from llm_gateway.products.config import validate_product
from llm_gateway.request_context import apply_posthog_context_from_headers

logger = structlog.get_logger(__name__)

anthropic_router = APIRouter()

ANTHROPIC_COUNT_TOKENS_URL = "https://api.anthropic.com/v1/messages/count_tokens"
ANTHROPIC_API_VERSION = "2023-06-01"
COUNT_TOKENS_ENDPOINT_NAME = "anthropic_count_tokens"
BEDROCK_COUNT_TOKENS_ENDPOINT_NAME = "bedrock_count_tokens"

# Mapping from Anthropic model names to Bedrock model IDs.
# Keys can be either the short name or the dated variant.
ANTHROPIC_TO_BEDROCK_MODEL_MAP: dict[str, str] = {
    "claude-opus-4-5": "us.anthropic.claude-opus-4-5-20251101-v1:0",
    "claude-opus-4-5-20251101": "us.anthropic.claude-opus-4-5-20251101-v1:0",
    "claude-opus-4-6": "us.anthropic.claude-opus-4-6",
    "claude-sonnet-4-5": "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
    "claude-sonnet-4-5-20250929": "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
    "claude-sonnet-4-6": "us.anthropic.claude-sonnet-4-6",
    "claude-haiku-4-5": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
    "claude-haiku-4-5-20251001": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
}


def map_to_bedrock_model(model: str) -> str:
    """Map an Anthropic model name to a Bedrock model ID.

    If the model is already a Bedrock model ID (contains 'anthropic.'), returns it as-is.
    """
    if "anthropic." in model:
        return model
    mapped = ANTHROPIC_TO_BEDROCK_MODEL_MAP.get(model)
    if mapped is None:
        raise HTTPException(
            status_code=400,
            detail={"error": {"message": f"No Bedrock mapping for model '{model}'", "type": "invalid_request_error"}},
        )
    return mapped


def ensure_bedrock_configured(settings: Any) -> None:
    if settings.bedrock_region_name:
        return
    logger.warning("Bedrock region not configured")
    raise HTTPException(
        status_code=503,
        detail={"error": {"message": "Bedrock region not configured", "type": "configuration_error"}},
    )


@functools.lru_cache
def _get_bedrock_runtime_client(region_name: str):
    return boto3.client("bedrock-runtime", region_name=region_name)


# The Bedrock CountTokens API requires a max_tokens field, but it's ignored in the calculation—tokens are counted from the input only.
def count_tokens_with_bedrock(
    messages: list[dict[str, Any]], model: str, aws_region_name: str, max_tokens: int = 4096
) -> int:
    bedrock_runtime_client = _get_bedrock_runtime_client(aws_region_name)

    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": max_tokens,
        "messages": messages,
    }
    # CountTokens API does not support regional model prefixes ("us.anthropic.", "eu.anthropic.")
    model = model.replace("us.anthropic.", "anthropic.").replace("eu.anthropic.", "anthropic.")

    response = bedrock_runtime_client.count_tokens(
        modelId=model,
        input={"invokeModel": {"body": json.dumps(body).encode("utf-8")}},
    )
    return int(response["inputTokens"])


async def _send_bedrock_messages(
    request_data: dict[str, Any],
    user: RateLimitedUser,
    request: Request,
    is_streaming: bool,
    product: str,
) -> dict[str, Any] | StreamingResponse:
    settings = get_settings()
    ensure_bedrock_configured(settings)

    data = dict(request_data)
    data["model"] = map_to_bedrock_model(data["model"])

    anthropic_beta = request.headers.get("anthropic-beta")
    if anthropic_beta:
        data["anthropic_beta"] = [h.strip() for h in anthropic_beta.split(",") if h.strip()]

    return await handle_llm_request(
        request_data=data,
        user=user,
        model=data["model"],
        is_streaming=is_streaming,
        provider_config=BEDROCK_CONFIG,
        llm_call=litellm.anthropic_messages,
        product=product,
    )


async def _handle_anthropic_messages(
    body: AnthropicMessagesRequest,
    user: RateLimitedUser,
    request: Request,
    product: str = "llm_gateway",
) -> dict[str, Any] | StreamingResponse:
    data = body.model_dump(exclude_none=True, exclude=GATEWAY_ONLY_FIELDS)
    provider = body.provider or "anthropic"

    if provider == "bedrock":
        return await _send_bedrock_messages(data, user, request, body.stream or False, product)

    # Anthropic path
    try:
        return await handle_llm_request(
            request_data=data,
            user=user,
            model=body.model,
            is_streaming=body.stream or False,
            provider_config=ANTHROPIC_CONFIG,
            llm_call=litellm.anthropic_messages,
            product=product,
        )
    except HTTPException as exc:
        if not body.use_bedrock_fallback or exc.status_code < 500:
            raise

        error_type = exc.detail.get("error", {}).get("type", "unknown") if isinstance(exc.detail, dict) else "unknown"
        logger.warning(
            "Anthropic request failed, attempting Bedrock fallback",
            model=body.model,
            product=product,
            original_status=exc.status_code,
            original_error_type=error_type,
        )
        BEDROCK_FALLBACK_TRIGGERED.labels(model=body.model, product=product, original_error_type=error_type).inc()

        try:
            result = await _send_bedrock_messages(data, user, request, body.stream or False, product)
            BEDROCK_FALLBACK_SUCCESS.labels(model=body.model, product=product).inc()
            return result
        except Exception:
            BEDROCK_FALLBACK_FAILURE.labels(model=body.model, product=product).inc()
            logger.exception("Bedrock fallback also failed", model=body.model, product=product)
            raise exc from None


async def _handle_count_tokens(
    body: AnthropicCountTokensRequest,
    user: RateLimitedUser,
    product: str = "llm_gateway",
) -> dict[str, Any]:
    data = body.model_dump(exclude_none=True, exclude=GATEWAY_ONLY_FIELDS)
    provider = body.provider or "anthropic"

    if provider == "bedrock":
        return await _bedrock_count_tokens_impl(data, body.model, user, product)

    # Anthropic path
    try:
        return await _anthropic_count_tokens_impl(data, body.model, user, product)
    except HTTPException as exc:
        if not body.use_bedrock_fallback or exc.status_code < 500:
            raise

        error_type = exc.detail.get("error", {}).get("type", "unknown") if isinstance(exc.detail, dict) else "unknown"
        logger.warning(
            "Anthropic count_tokens failed, attempting Bedrock fallback",
            model=body.model,
            product=product,
            original_status=exc.status_code,
            original_error_type=error_type,
        )
        BEDROCK_FALLBACK_TRIGGERED.labels(model=body.model, product=product, original_error_type=error_type).inc()

        try:
            result = await _bedrock_count_tokens_impl(data, body.model, user, product)
            BEDROCK_FALLBACK_SUCCESS.labels(model=body.model, product=product).inc()
            return result
        except Exception:
            BEDROCK_FALLBACK_FAILURE.labels(model=body.model, product=product).inc()
            logger.exception("Bedrock count_tokens fallback also failed", model=body.model, product=product)
            raise exc from None


async def _anthropic_count_tokens_impl(
    data: dict[str, Any],
    model: str,
    user: RateLimitedUser,
    product: str,
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
            model=model,
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


async def _bedrock_count_tokens_impl(
    data: dict[str, Any],
    model: str,
    user: RateLimitedUser,
    product: str,
) -> dict[str, Any]:
    settings = get_settings()
    ensure_bedrock_configured(settings)

    bedrock_model = map_to_bedrock_model(model)
    start_time = time.monotonic()
    status_code = "200"

    try:
        input_tokens = count_tokens_with_bedrock(
            data["messages"], bedrock_model, settings.bedrock_region_name, max_tokens=data.get("max_tokens", 4096)
        )
        return {"input_tokens": input_tokens}
    except HTTPException as e:
        status_code = str(e.status_code)
        raise
    except Exception as e:
        status_code = "502"
        logger.exception(
            "Error proxying bedrock count_tokens request", model=bedrock_model, max_tokens=data.get("max_tokens", 4096)
        )
        raise HTTPException(
            status_code=502,
            detail={"error": {"message": "Failed to count tokens via Bedrock", "type": "proxy_error"}},
        ) from e
    finally:
        REQUEST_COUNT.labels(
            endpoint=BEDROCK_COUNT_TOKENS_ENDPOINT_NAME,
            provider="bedrock",
            model=bedrock_model,
            status_code=status_code,
            auth_method=user.auth_method,
            product=product,
        ).inc()
        REQUEST_LATENCY.labels(
            endpoint=BEDROCK_COUNT_TOKENS_ENDPOINT_NAME,
            provider="bedrock",
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
    request: Request,
) -> dict[str, Any] | StreamingResponse:
    apply_posthog_context_from_headers(request)
    return await _handle_anthropic_messages(body, user, request)


@anthropic_router.post("/{product}/v1/messages", response_model=None)
async def anthropic_messages_with_product(
    body: AnthropicMessagesRequest,
    user: RateLimitedUser,
    product: str,
    request: Request,
) -> dict[str, Any] | StreamingResponse:
    validate_product(product)
    apply_posthog_context_from_headers(request)
    return await _handle_anthropic_messages(body, user, request, product=product)
