import time
from typing import Any

import httpx
import litellm
import structlog
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from llm_gateway.api.handler import ANTHROPIC_CONFIG, BEDROCK_CONFIG, _sanitize_request_data, handle_llm_request
from llm_gateway.bedrock import count_tokens_with_bedrock, ensure_bedrock_configured, map_to_bedrock_model
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
from llm_gateway.request_context import (
    apply_posthog_context_from_headers,
    extract_posthog_provider_from_headers,
    extract_posthog_use_bedrock_fallback_from_headers,
)

logger = structlog.get_logger(__name__)

anthropic_router = APIRouter()

ANTHROPIC_COUNT_TOKENS_URL = "https://api.anthropic.com/v1/messages/count_tokens"
ANTHROPIC_API_VERSION = "2023-06-01"
COUNT_TOKENS_ENDPOINT_NAME = "anthropic_count_tokens"
BEDROCK_COUNT_TOKENS_ENDPOINT_NAME = "bedrock_count_tokens"


def _invalid_header_exception(message: str) -> HTTPException:
    return HTTPException(status_code=400, detail={"error": {"message": message, "type": "invalid_request_error"}})


def _get_provider_from_headers(request: Request) -> str:
    try:
        return extract_posthog_provider_from_headers(request) or "anthropic"
    except ValueError as exc:
        raise _invalid_header_exception(str(exc)) from exc


def _get_use_bedrock_fallback_from_headers(request: Request) -> bool:
    try:
        return extract_posthog_use_bedrock_fallback_from_headers(request) or False
    except ValueError as exc:
        raise _invalid_header_exception(str(exc)) from exc


def strip_server_side_tools(data: dict[str, Any], *, model: str, product: str) -> None:
    """Remove Anthropic server-side tools (e.g. web_search) that Bedrock doesn't support.

    Server-side tools have a non-standard type (like web_search_20250305), while regular tools use custom or function (or omit type entirely, defaulting to custom).
    """
    if "tools" not in data:
        return

    supported: list[dict[str, Any]] = []
    for tool in data["tools"]:
        if tool.get("type", "custom") in ("custom", "function"):
            supported.append(tool)
        else:
            logger.warning(
                "Stripping unsupported tool for Bedrock",
                tool_name=tool.get("name"),
                tool_type=tool.get("type"),
                model=model,
                product=product,
            )

    if supported:
        data["tools"] = supported
    else:
        del data["tools"]


async def _send_bedrock_messages(
    request_data: dict[str, Any],
    user: RateLimitedUser,
    request: Request,
    is_streaming: bool,
    product: str,
) -> dict[str, Any] | StreamingResponse:
    settings = get_settings()
    bedrock_region_name = ensure_bedrock_configured(settings)

    data = dict(request_data)
    data["model"] = map_to_bedrock_model(data["model"], region_name=bedrock_region_name)

    anthropic_beta = request.headers.get("anthropic-beta")
    if anthropic_beta:
        data["anthropic_beta"] = [h.strip() for h in anthropic_beta.split(",") if h.strip()]

    strip_server_side_tools(data, model=data["model"], product=product)

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
    provider = _get_provider_from_headers(request)
    use_bedrock_fallback = _get_use_bedrock_fallback_from_headers(request)

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
        if not use_bedrock_fallback or exc.status_code < 500:
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
    request: Request,
    product: str = "llm_gateway",
) -> dict[str, Any]:
    data = _sanitize_request_data(body.model_dump(exclude_none=True, exclude=GATEWAY_ONLY_FIELDS))
    provider = _get_provider_from_headers(request)
    use_bedrock_fallback = _get_use_bedrock_fallback_from_headers(request)

    if provider == "bedrock":
        return await _bedrock_count_tokens_impl(data, body.model, user, product)

    # Anthropic path
    try:
        return await _anthropic_count_tokens_impl(data, body.model, user, product)
    except HTTPException as exc:
        if not use_bedrock_fallback or exc.status_code < 500:
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
        logger.exception(
            "count_tokens_proxy_failed",
            endpoint=COUNT_TOKENS_ENDPOINT_NAME,
            error_type=type(e).__name__,
            error_message=str(e),
        )
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
    bedrock_region_name = ensure_bedrock_configured(settings)

    bedrock_model = map_to_bedrock_model(model, region_name=bedrock_region_name)
    start_time = time.monotonic()
    status_code = "200"

    try:
        input_tokens = await count_tokens_with_bedrock(
            data,
            bedrock_model,
            bedrock_region_name,
            settings.request_timeout,
        )
        return {"input_tokens": input_tokens}
    except HTTPException as e:
        status_code = str(e.status_code)
        raise
    except Exception as e:
        status_code = "502"
        error_type_name = type(e).__name__
        logger.exception(
            "Error proxying bedrock count_tokens request",
            model=bedrock_model,
            max_tokens=data.get("max_tokens", 4096),
            error_type=error_type_name,
            error_message=str(e),
        )
        raise HTTPException(
            status_code=502,
            detail={
                "error": {
                    "message": f"Failed to count tokens via Bedrock ({error_type_name})",
                    "type": "proxy_error",
                }
            },
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
    request: Request,
) -> dict[str, Any]:
    return await _handle_count_tokens(body, user, request)


@anthropic_router.post("/{product}/v1/messages/count_tokens", response_model=None)
async def anthropic_count_tokens_with_product(
    body: AnthropicCountTokensRequest,
    user: RateLimitedUser,
    product: str,
    request: Request,
) -> dict[str, Any]:
    validate_product(product)
    return await _handle_count_tokens(body, user, request, product=product)


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
