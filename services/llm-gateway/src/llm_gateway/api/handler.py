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
)
from llm_gateway.observability import capture_exception
from llm_gateway.request_context import RequestContext, get_request_id, set_auth_user, set_request_context
from llm_gateway.streaming.sse import format_sse_stream

logger = structlog.get_logger(__name__)


@dataclass
class ProviderConfig:
    name: str
    endpoint_name: str


ANTHROPIC_CONFIG = ProviderConfig(name="anthropic", endpoint_name="anthropic_messages")
OPENAI_CONFIG = ProviderConfig(name="openai", endpoint_name="chat_completions")
OPENAI_RESPONSES_CONFIG = ProviderConfig(name="openai", endpoint_name="responses")


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

    set_request_context(RequestContext(request_id=get_request_id(), product=product))
    set_auth_user(user)

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
    async def stream_generator() -> AsyncGenerator[bytes, None]:
        ACTIVE_STREAMS.labels(provider=provider_config.name, model=model, product=product).inc()
        CONCURRENT_REQUESTS.labels(provider=provider_config.name, model=model, product=product).inc()
        status_code = "200"
        provider_start = time.monotonic()
        first_chunk_received = False

        try:
            response = await asyncio.wait_for(llm_call(**request_data), timeout=timeout)

            async for chunk in format_sse_stream(response):
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
            logger.error(f"Streaming timeout for {provider_config.endpoint_name}")
            raise
        except Exception as e:
            status_code = str(getattr(e, "status_code", 500))
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

        REQUEST_LATENCY.labels(
            endpoint=provider_config.endpoint_name,
            provider=provider_config.name,
            streaming="false",
            product=product,
        ).observe(time.monotonic() - start_time)

        return response_dict
    except Exception:
        raise
