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
    LLM_TIME_TO_FIRST_TOKEN,
    PROVIDER_ERRORS,
    REQUEST_COUNT,
    REQUEST_LATENCY,
    STREAMING_CLIENT_DISCONNECT,
)
from llm_gateway.observability import capture_exception
from llm_gateway.request_context import (
    RequestContext,
    get_posthog_flags,
    get_posthog_properties,
    get_request_id,
    set_auth_user,
    set_request_context,
    set_time_to_first_token,
)
from llm_gateway.streaming.sse import format_sse_stream

logger = structlog.get_logger(__name__)


@dataclass
class ProviderConfig:
    name: str
    endpoint_name: str


ANTHROPIC_CONFIG = ProviderConfig(name="anthropic", endpoint_name="anthropic_messages")
BEDROCK_CONFIG = ProviderConfig(name="bedrock", endpoint_name="bedrock_messages")
OPENAI_CONFIG = ProviderConfig(name="openai", endpoint_name="chat_completions")
OPENAI_RESPONSES_CONFIG = ProviderConfig(name="openai", endpoint_name="responses")
OPENAI_TRANSCRIPTION_CONFIG = ProviderConfig(name="openai", endpoint_name="audio_transcriptions")

# Google providers require litellm[google], which we don't install. Reject these
# at the edge so litellm doesn't crash deep in vertex_llm_base with an ImportError.
# Match both explicit provider prefixes (gemini/foo, vertex_ai/foo) and bare names
# that litellm will route to vertex/gemini — most commonly anything starting with
# "gemini-" (e.g. "gemini-3-pro-preview") — since those may not yet be in the cost
# registry when brand new.
_UNSUPPORTED_PROVIDERS = frozenset({"vertex_ai", "vertex_ai-language-models", "gemini"})
_UNSUPPORTED_MODEL_PREFIXES = (
    *(f"{p}/" for p in _UNSUPPORTED_PROVIDERS),
    "gemini-",
)


def _raise_unsupported_model(model: str) -> None:
    raise HTTPException(
        status_code=400,
        detail={
            "error": {
                "message": f"Model '{model}' is not supported by this gateway",
                "type": "invalid_request_error",
                "code": "model_not_supported",
            }
        },
    )


def _raise_if_unsupported_model(model: str) -> None:
    from llm_gateway.services.model_registry import ModelRegistryService

    if model.lower().startswith(_UNSUPPORTED_MODEL_PREFIXES):
        _raise_unsupported_model(model)
    info = ModelRegistryService.get_instance().get_model(model)
    if info is not None and info.provider in _UNSUPPORTED_PROVIDERS:
        _raise_unsupported_model(model)


# Parameters that control LLM client routing/authentication.
# These must never be accepted from user input to prevent request
# redirection and API key exfiltration.
FORBIDDEN_REQUEST_PARAMS = frozenset(
    {"api_key", "api_base", "base_url", "api_version", "organization", "model_list", "fallbacks", "custom_llm_provider"}
)


def _sanitize_request_value(value: Any) -> Any:
    # Recursively strip forbidden params from nested dicts and lists.
    # litellm forwards nested params (e.g. model_list[*].litellm_params.api_key)
    # to the upstream provider, so a shallow filter is insufficient.
    if isinstance(value, dict):
        return {k: _sanitize_request_value(v) for k, v in value.items() if k not in FORBIDDEN_REQUEST_PARAMS}
    if isinstance(value, list):
        return [_sanitize_request_value(item) for item in value]
    return value


def _sanitize_request_data(data: dict[str, Any]) -> dict[str, Any]:
    return {k: _sanitize_request_value(v) for k, v in data.items() if k not in FORBIDDEN_REQUEST_PARAMS}


async def handle_llm_request(
    request_data: dict[str, Any],
    user: AuthenticatedUser,
    model: str,
    is_streaming: bool,
    provider_config: ProviderConfig,
    llm_call: Callable[..., Awaitable[Any]],
    product: str = "llm_gateway",
) -> dict[str, Any] | StreamingResponse:
    _raise_if_unsupported_model(model)
    request_data = _sanitize_request_data(request_data)
    settings = get_settings()
    start_time = time.monotonic()

    set_request_context(
        RequestContext(
            request_id=get_request_id(),
            product=product,
            posthog_properties=get_posthog_properties(),
            posthog_flags=get_posthog_flags(),
        )
    )
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
        logger.error(
            "llm_request_timeout",
            endpoint=provider_config.endpoint_name,
            streaming=False,
        )
        raise HTTPException(
            status_code=504,
            detail={"error": {"message": "Request timed out", "type": "timeout_error", "code": None}},
        ) from None
    except HTTPException:
        raise
    except Exception as e:
        PROVIDER_ERRORS.labels(provider=provider_config.name, error_type=type(e).__name__, product=product).inc()
        capture_exception(e, {"provider": provider_config.name, "model": model, "user_id": user.user_id})
        status_code = getattr(e, "status_code", 500)
        logger.exception(
            "llm_request_failed",
            endpoint=provider_config.endpoint_name,
            streaming=False,
            status_code=status_code,
            error_type=type(e).__name__,
            error_message=getattr(e, "message", str(e)),
            provider_error_type=getattr(e, "type", None),
            provider_error_code=getattr(e, "code", None),
        )
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
    CONCURRENT_REQUESTS.labels(provider=provider_config.name, model=model, product=product).inc()
    try:
        llm_response = await asyncio.wait_for(llm_call(**request_data), timeout=timeout)
    except TimeoutError:
        CONCURRENT_REQUESTS.labels(provider=provider_config.name, model=model, product=product).dec()
        PROVIDER_ERRORS.labels(provider=provider_config.name, error_type="timeout", product=product).inc()
        REQUEST_COUNT.labels(
            endpoint=provider_config.endpoint_name,
            provider=provider_config.name,
            model=model,
            status_code="504",
            auth_method=user.auth_method,
            product=product,
        ).inc()
        REQUEST_LATENCY.labels(
            endpoint=provider_config.endpoint_name,
            provider=provider_config.name,
            streaming="true",
            product=product,
        ).observe(time.monotonic() - start_time)
        logger.error(
            "llm_request_timeout",
            endpoint=provider_config.endpoint_name,
            streaming=True,
        )
        raise HTTPException(
            status_code=504,
            detail={"error": {"message": "Request timed out", "type": "timeout_error", "code": None}},
        ) from None
    except Exception as e:
        CONCURRENT_REQUESTS.labels(provider=provider_config.name, model=model, product=product).dec()
        PROVIDER_ERRORS.labels(provider=provider_config.name, error_type=type(e).__name__, product=product).inc()
        capture_exception(e, {"provider": provider_config.name, "model": model, "streaming": True})
        status_code = getattr(e, "status_code", 500)
        logger.exception(
            "llm_request_failed",
            endpoint=provider_config.endpoint_name,
            streaming=True,
            status_code=status_code,
            error_type=type(e).__name__,
            error_message=getattr(e, "message", str(e)),
            provider_error_type=getattr(e, "type", None),
            provider_error_code=getattr(e, "code", None),
        )
        REQUEST_COUNT.labels(
            endpoint=provider_config.endpoint_name,
            provider=provider_config.name,
            model=model,
            status_code=str(status_code),
            auth_method=user.auth_method,
            product=product,
        ).inc()
        REQUEST_LATENCY.labels(
            endpoint=provider_config.endpoint_name,
            provider=provider_config.name,
            streaming="true",
            product=product,
        ).observe(time.monotonic() - start_time)
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

    async def stream_generator() -> AsyncGenerator[bytes, None]:
        ACTIVE_STREAMS.labels(provider=provider_config.name, model=model, product=product).inc()
        status_code = "200"
        provider_start = time.monotonic()
        first_chunk_received = False

        try:
            async for chunk in format_sse_stream(llm_response):
                if not first_chunk_received:
                    first_chunk_received = True
                    time_to_first = time.monotonic() - provider_start
                    LLM_TIME_TO_FIRST_TOKEN.labels(provider=provider_config.name, model=model, product=product).observe(
                        time_to_first
                    )
                    set_time_to_first_token(time_to_first)
                yield chunk

        except asyncio.CancelledError:
            STREAMING_CLIENT_DISCONNECT.labels(provider=provider_config.name, model=model, product=product).inc()
            raise
        except TimeoutError:
            status_code = "504"
            PROVIDER_ERRORS.labels(provider=provider_config.name, error_type="timeout", product=product).inc()
            logger.error(
                "stream_chunk_timeout",
                endpoint=provider_config.endpoint_name,
            )
            raise
        except Exception as e:
            status_code = str(getattr(e, "status_code", 500))
            PROVIDER_ERRORS.labels(provider=provider_config.name, error_type=type(e).__name__, product=product).inc()
            capture_exception(e, {"provider": provider_config.name, "model": model, "streaming": True})
            logger.exception(
                "stream_chunk_failed",
                endpoint=provider_config.endpoint_name,
                status_code=status_code,
                error_type=type(e).__name__,
                error_message=str(e),
            )
            raise
        finally:
            duration_ms = round((time.monotonic() - start_time) * 1000, 2)
            if status_code == "200":
                logger.info(
                    "llm_request_completed",
                    endpoint=provider_config.endpoint_name,
                    streaming=True,
                    duration_ms=duration_ms,
                )
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
    status_code = "200"
    try:
        response = await asyncio.wait_for(llm_call(**request_data), timeout=timeout)
        response_dict = response.model_dump() if hasattr(response, "model_dump") else response
        duration_ms = round((time.monotonic() - start_time) * 1000, 2)
        logger.info(
            "llm_request_completed",
            endpoint=provider_config.endpoint_name,
            streaming=False,
            duration_ms=duration_ms,
        )
        return response_dict
    except TimeoutError:
        status_code = "504"
        raise
    except Exception as e:
        status_code = str(getattr(e, "status_code", 500))
        raise
    finally:
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
            streaming="false",
            product=product,
        ).observe(time.monotonic() - start_time)
