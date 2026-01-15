import asyncio
import json
import time
from collections.abc import AsyncGenerator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import litellm
import structlog
from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from llm_gateway.analytics import get_analytics_service
from llm_gateway.auth.models import AuthenticatedUser
from llm_gateway.config import get_settings
from llm_gateway.metrics.prometheus import (
    ACTIVE_STREAMS,
    CONCURRENT_REQUESTS,
    PROVIDER_ERRORS,
    PROVIDER_LATENCY,
    REQUEST_COUNT,
    REQUEST_LATENCY,
    STREAMING_CLIENT_DISCONNECT,
    STREAMING_USAGE_EXTRACTION,
    TIME_TO_FIRST_CHUNK,
    TOKENS_INPUT,
    TOKENS_OUTPUT,
)
from llm_gateway.observability import capture_exception
from llm_gateway.request_context import record_output_tokens
from llm_gateway.streaming.sse import format_sse_stream

logger = structlog.get_logger(__name__)


def _extract_usage_from_sse_bytes(chunks: list[bytes]) -> tuple[int | None, int | None]:
    """Extract usage from raw SSE bytes (for passthrough providers like Anthropic).

    Anthropic SSE format:
    - message_start: {"type": "message_start", "message": {..., "usage": {"input_tokens": X}}}
    - message_delta: {"type": "message_delta", "usage": {"output_tokens": Y}}
    """
    input_tokens: int | None = None
    output_tokens: int | None = None

    for chunk in chunks:
        try:
            text = chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk
            for line in text.split("\n"):
                if not line.startswith("data: "):
                    continue
                data_str = line[6:].strip()
                if not data_str or data_str == "[DONE]":
                    continue
                data = json.loads(data_str)

                if data.get("type") == "message_start":
                    message = data.get("message", {})
                    usage = message.get("usage", {})
                    input_tokens = usage.get("input_tokens")
                elif data.get("type") == "message_delta":
                    usage = data.get("usage", {})
                    if "output_tokens" in usage:
                        output_tokens = usage.get("output_tokens")
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue

    return input_tokens, output_tokens


def _record_token_metrics(
    provider: str, model: str, product: str, input_tokens: int | None, output_tokens: int | None
) -> None:
    """Record token usage metrics if values are within valid range."""
    if input_tokens is not None and 0 <= input_tokens <= 1_000_000:
        TOKENS_INPUT.labels(provider=provider, model=model, product=product).inc(input_tokens)
    if output_tokens is not None and 0 <= output_tokens <= 1_000_000:
        TOKENS_OUTPUT.labels(provider=provider, model=model, product=product).inc(output_tokens)


def _extract_streaming_usage(
    collected_chunks: list[Any], messages: list[Any], provider: str, model: str, product: str
) -> int | None:
    """Extract and log usage from streaming response chunks. Returns output_tokens if found."""
    if not collected_chunks:
        logger.warning(
            "streaming_usage_missing",
            provider=provider,
            model=model,
            reason="no chunks collected during stream",
            chunk_count=0,
        )
        STREAMING_USAGE_EXTRACTION.labels(provider=provider, status="no_chunks").inc()
        return None

    is_passthrough = isinstance(collected_chunks[0], bytes)

    if is_passthrough:
        input_tokens, output_tokens = _extract_usage_from_sse_bytes(collected_chunks)
    else:
        input_tokens, output_tokens = None, None
        complete = litellm.stream_chunk_builder(collected_chunks, messages=messages)
        if complete and complete.usage:
            input_tokens = complete.usage.prompt_tokens
            output_tokens = complete.usage.completion_tokens

    has_input = input_tokens is not None
    has_output = output_tokens is not None

    if has_input and has_output:
        logger.info(
            "streaming_usage",
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            passthrough=is_passthrough,
        )
        _record_token_metrics(provider, model, product, input_tokens, output_tokens)
        STREAMING_USAGE_EXTRACTION.labels(provider=provider, status="success").inc()
    elif has_input or has_output:
        status = "partial_input_only" if has_input else "partial_output_only"
        missing = "output_tokens" if has_input else "input_tokens"
        logger.warning(
            "streaming_usage_partial",
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            reason=f"{missing} missing from response",
            passthrough=is_passthrough,
            chunk_count=len(collected_chunks),
        )
        STREAMING_USAGE_EXTRACTION.labels(provider=provider, status=status).inc()
    else:
        logger.warning(
            "streaming_usage_missing",
            provider=provider,
            model=model,
            reason="no usage data found in response",
            passthrough=is_passthrough,
            chunk_count=len(collected_chunks),
        )
        STREAMING_USAGE_EXTRACTION.labels(provider=provider, status="missing").inc()

    return output_tokens


@dataclass
class ProviderConfig:
    name: str
    endpoint_name: str
    input_tokens_field: str
    output_tokens_field: str


ANTHROPIC_CONFIG = ProviderConfig(
    name="anthropic",
    endpoint_name="anthropic_messages",
    input_tokens_field="input_tokens",
    output_tokens_field="output_tokens",
)

OPENAI_CONFIG = ProviderConfig(
    name="openai",
    endpoint_name="chat_completions",
    input_tokens_field="prompt_tokens",
    output_tokens_field="completion_tokens",
)

OPENAI_RESPONSES_CONFIG = ProviderConfig(
    name="openai",
    endpoint_name="responses",
    input_tokens_field="input_tokens",
    output_tokens_field="output_tokens",
)


async def handle_llm_request(
    request_data: dict[str, Any],
    user: AuthenticatedUser,
    model: str,
    is_streaming: bool,
    provider_config: ProviderConfig,
    llm_call: Callable[..., Awaitable[Any]],
    product: str = "llm_gateway",
) -> dict[str, Any] | StreamingResponse:
    settings = get_settings()
    start_time = time.monotonic()

    structlog.contextvars.bind_contextvars(
        user_id=user.user_id,
        team_id=user.team_id,
        provider=provider_config.name,
        model=model,
    )

    if is_streaming:
        return await _handle_streaming_request(
            request_data=request_data,
            user=user,
            model=model,
            provider_config=provider_config,
            llm_call=llm_call,
            start_time=start_time,
            timeout=settings.streaming_timeout,
            product=product,
        )

    CONCURRENT_REQUESTS.labels(provider=provider_config.name, model=model, product=product).inc()
    try:
        return await _handle_non_streaming_request(
            request_data=request_data,
            user=user,
            model=model,
            provider_config=provider_config,
            llm_call=llm_call,
            start_time=start_time,
            timeout=settings.request_timeout,
            product=product,
        )

    except TimeoutError:
        PROVIDER_ERRORS.labels(provider=provider_config.name, error_type="timeout", product=product).inc()
        logger.error(f"Timeout in {provider_config.endpoint_name} endpoint")
        raise HTTPException(
            status_code=504,
            detail={"error": {"message": "Request timed out", "type": "timeout_error", "code": None}},
        ) from None
    except HTTPException:
        raise
    except Exception as e:
        PROVIDER_ERRORS.labels(provider=provider_config.name, error_type=type(e).__name__, product=product).inc()
        capture_exception(e, {"provider": provider_config.name, "model": model, "user_id": user.user_id})
        logger.exception(f"Error in {provider_config.endpoint_name} endpoint: {e}")
        status_code = getattr(e, "status_code", 500)
        raise HTTPException(
            status_code=status_code,
            detail={
                "error": {
                    "message": getattr(e, "message", str(e)),
                    "type": getattr(e, "type", "internal_error"),
                    "code": getattr(e, "code", None),
                }
            },
        ) from e
    finally:
        CONCURRENT_REQUESTS.labels(provider=provider_config.name, model=model, product=product).dec()


async def _handle_streaming_request(
    request_data: dict[str, Any],
    user: AuthenticatedUser,
    model: str,
    provider_config: ProviderConfig,
    llm_call: Callable[..., Awaitable[Any]],
    start_time: float,
    timeout: float,
    product: str = "llm_gateway",
) -> StreamingResponse:
    collected_chunks: list[Any] = []

    async def stream_generator() -> AsyncGenerator[bytes, None]:
        ACTIVE_STREAMS.labels(provider=provider_config.name, model=model, product=product).inc()
        CONCURRENT_REQUESTS.labels(provider=provider_config.name, model=model, product=product).inc()
        status_code = "200"
        provider_start = time.monotonic()
        first_chunk_received = False
        error: Exception | None = None

        async def collect_chunks_wrapper(
            llm_response: AsyncGenerator[Any, None],
        ) -> AsyncGenerator[Any, None]:
            async for chunk in llm_response:
                collected_chunks.append(chunk)
                yield chunk

        try:
            response = await asyncio.wait_for(llm_call(**request_data), timeout=timeout)

            async for chunk in format_sse_stream(collect_chunks_wrapper(response)):
                if not first_chunk_received:
                    first_chunk_received = True
                    time_to_first = time.monotonic() - provider_start
                    PROVIDER_LATENCY.labels(provider=provider_config.name, model=model, product=product).observe(
                        time_to_first
                    )
                    TIME_TO_FIRST_CHUNK.labels(provider=provider_config.name, model=model, product=product).observe(
                        time_to_first
                    )
                yield chunk

        except asyncio.CancelledError:
            STREAMING_CLIENT_DISCONNECT.labels(provider=provider_config.name, model=model, product=product).inc()
            raise
        except TimeoutError:
            status_code = "504"
            error = TimeoutError("Streaming timeout")
            logger.error(f"Streaming timeout for {provider_config.endpoint_name}")
            raise
        except Exception as e:
            status_code = str(getattr(e, "status_code", 500))
            error = e
            capture_exception(e, {"provider": provider_config.name, "model": model, "streaming": True})
            logger.exception(f"Streaming error in {provider_config.endpoint_name} endpoint: {e}")
            raise
        finally:
            ACTIVE_STREAMS.labels(provider=provider_config.name, model=model, product=product).dec()
            CONCURRENT_REQUESTS.labels(provider=provider_config.name, model=model, product=product).dec()
            REQUEST_COUNT.labels(
                endpoint=provider_config.endpoint_name,
                provider=provider_config.name,
                model=model,
                status_code=status_code,
                auth_method=user.auth_method,
                product=product,
            ).inc()
            REQUEST_LATENCY.labels(
                endpoint=provider_config.endpoint_name,
                provider=provider_config.name,
                streaming="true",
                product=product,
            ).observe(time.monotonic() - start_time)

            output_tokens: int | None = None
            try:
                output_tokens = _extract_streaming_usage(
                    collected_chunks=collected_chunks,
                    messages=request_data.get("messages", []),
                    provider=provider_config.name,
                    model=model,
                    product=product,
                )
            except Exception as usage_error:
                logger.error(
                    "streaming_usage_parse_failed",
                    provider=provider_config.name,
                    model=model,
                    error=str(usage_error),
                    error_type=type(usage_error).__name__,
                    chunk_count=len(collected_chunks) if collected_chunks else 0,
                )
                STREAMING_USAGE_EXTRACTION.labels(provider=provider_config.name, status="error").inc()

            if output_tokens is not None:
                try:
                    await record_output_tokens(output_tokens)
                except Exception as throttle_error:
                    logger.error("output_token_recording_failed", error=str(throttle_error))

            try:
                analytics = get_analytics_service()
                if analytics:
                    latency_seconds = time.monotonic() - start_time
                    analytics.capture(
                        user=user,
                        model=model,
                        provider=provider_config.name,
                        input_messages=request_data.get("messages", []),
                        latency_seconds=latency_seconds,
                        response=None,
                        error=error,
                        is_streaming=True,
                        input_tokens_field=provider_config.input_tokens_field,
                        output_tokens_field=provider_config.output_tokens_field,
                        product=product,
                    )
            except Exception as analytics_error:
                logger.warning("Failed to capture analytics", error=str(analytics_error))

    return StreamingResponse(
        stream_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _handle_non_streaming_request(
    request_data: dict[str, Any],
    user: AuthenticatedUser,
    model: str,
    provider_config: ProviderConfig,
    llm_call: Callable[..., Awaitable[Any]],
    start_time: float,
    timeout: float,
    product: str = "llm_gateway",
) -> dict[str, Any]:
    provider_start = time.monotonic()
    response_dict: dict[str, Any] | None = None
    error: Exception | None = None

    try:
        response = await asyncio.wait_for(llm_call(**request_data), timeout=timeout)
        PROVIDER_LATENCY.labels(provider=provider_config.name, model=model, product=product).observe(
            time.monotonic() - provider_start
        )
        response_dict = response.model_dump() if hasattr(response, "model_dump") else response

        REQUEST_COUNT.labels(
            endpoint=provider_config.endpoint_name,
            provider=provider_config.name,
            model=model,
            status_code="200",
            auth_method=user.auth_method,
            product=product,
        ).inc()

        if "usage" in response_dict:
            usage = response_dict["usage"]
            input_tokens = usage.get(provider_config.input_tokens_field, 0)
            output_tokens = usage.get(provider_config.output_tokens_field, 0)

            if 0 <= input_tokens <= 1_000_000:
                TOKENS_INPUT.labels(provider=provider_config.name, model=model, product=product).inc(input_tokens)
            if 0 <= output_tokens <= 1_000_000:
                TOKENS_OUTPUT.labels(provider=provider_config.name, model=model, product=product).inc(output_tokens)

        REQUEST_LATENCY.labels(
            endpoint=provider_config.endpoint_name,
            provider=provider_config.name,
            streaming="false",
            product=product,
        ).observe(time.monotonic() - start_time)

        return response_dict
    except Exception as e:
        error = e
        raise
    finally:
        try:
            analytics = get_analytics_service()
            if analytics:
                latency_seconds = time.monotonic() - start_time
                analytics.capture(
                    user=user,
                    model=model,
                    provider=provider_config.name,
                    input_messages=request_data.get("messages", []),
                    latency_seconds=latency_seconds,
                    response=response_dict,
                    error=error,
                    is_streaming=False,
                    input_tokens_field=provider_config.input_tokens_field,
                    output_tokens_field=provider_config.output_tokens_field,
                    product=product,
                )
        except Exception as analytics_error:
            logger.warning("Failed to capture analytics", error=str(analytics_error))
