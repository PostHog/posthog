import asyncio
import time
from collections.abc import AsyncGenerator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import structlog
from fastapi import HTTPException
from fastapi.responses import StreamingResponse

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
    TIME_TO_FIRST_CHUNK,
    TOKENS_INPUT,
    TOKENS_OUTPUT,
)
from llm_gateway.observability import capture_exception
from llm_gateway.streaming.sse import format_sse_stream

logger = structlog.get_logger(__name__)


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
        )

    CONCURRENT_REQUESTS.inc()
    try:
        return await _handle_non_streaming_request(
            request_data=request_data,
            user=user,
            model=model,
            provider_config=provider_config,
            llm_call=llm_call,
            start_time=start_time,
            timeout=settings.request_timeout,
        )

    except TimeoutError:
        PROVIDER_ERRORS.labels(provider=provider_config.name, error_type="timeout").inc()
        logger.error(f"Timeout in {provider_config.endpoint_name} endpoint")
        raise HTTPException(
            status_code=504,
            detail={"error": {"message": "Request timed out", "type": "timeout_error", "code": None}},
        ) from None
    except HTTPException:
        raise
    except Exception as e:
        PROVIDER_ERRORS.labels(provider=provider_config.name, error_type=type(e).__name__).inc()
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
        CONCURRENT_REQUESTS.dec()


async def _handle_streaming_request(
    request_data: dict[str, Any],
    user: AuthenticatedUser,
    model: str,
    provider_config: ProviderConfig,
    llm_call: Callable[..., Awaitable[Any]],
    start_time: float,
    timeout: float,
) -> StreamingResponse:
    async def stream_generator() -> AsyncGenerator[bytes, None]:
        ACTIVE_STREAMS.labels(provider=provider_config.name).inc()
        CONCURRENT_REQUESTS.inc()
        status_code = "200"
        provider_start = time.monotonic()
        first_chunk_received = False

        try:
            response = await asyncio.wait_for(llm_call(**request_data), timeout=timeout)

            async for chunk in format_sse_stream(response):
                if not first_chunk_received:
                    first_chunk_received = True
                    time_to_first = time.monotonic() - provider_start
                    PROVIDER_LATENCY.labels(provider=provider_config.name, model=model).observe(time_to_first)
                    TIME_TO_FIRST_CHUNK.labels(provider=provider_config.name, model=model).observe(time_to_first)
                yield chunk

        except asyncio.CancelledError:
            STREAMING_CLIENT_DISCONNECT.labels(provider=provider_config.name).inc()
            raise
        except TimeoutError:
            status_code = "504"
            logger.error(f"Streaming timeout for {provider_config.endpoint_name}")
            raise
        except Exception as e:
            status_code = str(getattr(e, "status_code", 500))
            capture_exception(e, {"provider": provider_config.name, "model": model, "streaming": True})
            raise
        finally:
            ACTIVE_STREAMS.labels(provider=provider_config.name).dec()
            CONCURRENT_REQUESTS.dec()
            REQUEST_COUNT.labels(
                endpoint=provider_config.endpoint_name,
                provider=provider_config.name,
                model=model,
                status_code=status_code,
                auth_method=user.auth_method,
            ).inc()
            REQUEST_LATENCY.labels(
                endpoint=provider_config.endpoint_name,
                provider=provider_config.name,
                streaming="true",
            ).observe(time.monotonic() - start_time)

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
) -> dict[str, Any]:
    provider_start = time.monotonic()
    response = await asyncio.wait_for(llm_call(**request_data), timeout=timeout)

    PROVIDER_LATENCY.labels(provider=provider_config.name, model=model).observe(time.monotonic() - provider_start)

    response_dict: dict[str, Any] = response.model_dump() if hasattr(response, "model_dump") else response

    REQUEST_COUNT.labels(
        endpoint=provider_config.endpoint_name,
        provider=provider_config.name,
        model=model,
        status_code="200",
        auth_method=user.auth_method,
    ).inc()

    if "usage" in response_dict:
        usage = response_dict["usage"]
        input_tokens = usage.get(provider_config.input_tokens_field, 0)
        output_tokens = usage.get(provider_config.output_tokens_field, 0)

        if 0 <= input_tokens <= 1_000_000:
            TOKENS_INPUT.labels(provider=provider_config.name, model=model).inc(input_tokens)
        if 0 <= output_tokens <= 1_000_000:
            TOKENS_OUTPUT.labels(provider=provider_config.name, model=model).inc(output_tokens)

    REQUEST_LATENCY.labels(
        endpoint=provider_config.endpoint_name,
        provider=provider_config.name,
        streaming="false",
    ).observe(time.monotonic() - start_time)

    return response_dict
