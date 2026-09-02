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
    rebuild_request_context,
    set_auth_user,
    set_effort,
    set_time_to_first_token,
)
from llm_gateway.streaming.sse import format_sse_stream

logger = structlog.get_logger(__name__)


def _clean_effort(value: Any) -> str | None:
    if isinstance(value, str) and (stripped := value.strip()):
        return stripped
    return None


def effort_from_output_config(request_data: dict[str, Any]) -> str | None:
    """Anthropic Messages: ``output_config: {"effort": "..."}``."""
    output_config = request_data.get("output_config")
    return _clean_effort(output_config.get("effort")) if isinstance(output_config, dict) else None


def effort_from_reasoning_effort(request_data: dict[str, Any]) -> str | None:
    """OpenAI chat completions: top-level ``reasoning_effort``."""
    return _clean_effort(request_data.get("reasoning_effort"))


def effort_from_reasoning(request_data: dict[str, Any]) -> str | None:
    """OpenAI Responses: ``reasoning: {"effort": "..."}``."""
    reasoning = request_data.get("reasoning")
    return _clean_effort(reasoning.get("effort")) if isinstance(reasoning, dict) else None


def no_effort(request_data: dict[str, Any]) -> str | None:
    """Endpoints with no reasoning-effort parameter (e.g. transcription)."""
    return None


@dataclass
class ProviderConfig:
    name: str
    endpoint_name: str
    # Where reasoning effort lives varies per API surface. Required (no default) so a new
    # provider can't be added without deciding; see the effort_from_* functions above.
    extract_effort: Callable[[dict[str, Any]], str | None]


ANTHROPIC_CONFIG = ProviderConfig(
    name="anthropic",
    endpoint_name="anthropic_messages",
    extract_effort=effort_from_output_config,
)
BEDROCK_CONFIG = ProviderConfig(
    name="bedrock",
    endpoint_name="bedrock_messages",
    extract_effort=effort_from_output_config,
)
OPENAI_CONFIG = ProviderConfig(
    name="openai",
    endpoint_name="chat_completions",
    extract_effort=effort_from_reasoning_effort,
)
OPENAI_RESPONSES_CONFIG = ProviderConfig(
    name="openai",
    endpoint_name="responses",
    extract_effort=effort_from_reasoning,
)
OPENAI_TRANSCRIPTION_CONFIG = ProviderConfig(
    name="openai",
    endpoint_name="audio_transcriptions",
    extract_effort=no_effort,
)
# Split endpoint labels so an adapter-specific regression is distinguishable in metrics.
CLOUDFLARE_ANTHROPIC_CONFIG = ProviderConfig(
    name="cloudflare",
    endpoint_name="cloudflare_anthropic_messages",
    extract_effort=effort_from_output_config,
)
CLOUDFLARE_OPENAI_CONFIG = ProviderConfig(
    name="cloudflare",
    endpoint_name="cloudflare_chat_completions",
    extract_effort=effort_from_reasoning_effort,
)
CLOUDFLARE_OPENAI_RESPONSES_CONFIG = ProviderConfig(
    name="cloudflare",
    endpoint_name="cloudflare_responses",
    extract_effort=effort_from_reasoning,
)
# Modal-served GLM (OpenAI-compatible vLLM endpoint). Same per-surface split as Cloudflare so a
# Modal-specific regression is distinguishable in metrics during the migration.
MODAL_ANTHROPIC_CONFIG = ProviderConfig(
    name="modal",
    endpoint_name="modal_anthropic_messages",
    extract_effort=effort_from_output_config,
)
MODAL_OPENAI_CONFIG = ProviderConfig(
    name="modal",
    endpoint_name="modal_chat_completions",
    extract_effort=effort_from_reasoning_effort,
)
MODAL_OPENAI_RESPONSES_CONFIG = ProviderConfig(
    name="modal",
    endpoint_name="modal_responses",
    extract_effort=effort_from_reasoning,
)
BASETEN_ANTHROPIC_CONFIG = ProviderConfig(
    name="baseten",
    endpoint_name="baseten_anthropic_messages",
    extract_effort=effort_from_output_config,
)
BASETEN_OPENAI_CONFIG = ProviderConfig(
    name="baseten",
    endpoint_name="baseten_chat_completions",
    extract_effort=effort_from_reasoning_effort,
)
BASETEN_OPENAI_RESPONSES_CONFIG = ProviderConfig(
    name="baseten",
    endpoint_name="baseten_responses",
    extract_effort=effort_from_reasoning,
)

_KNOWN_LITELLM_PROVIDER_PREFIXES = (
    "anthropic/",
    "bedrock/",
    "fireworks_ai/",
    "openai/",
    "openrouter/",
)


def normalize_litellm_model_name(model: str, provider: str) -> str:
    """Add an explicit LiteLLM provider prefix when a provider endpoint receives a bare model ID."""
    if model.startswith(_KNOWN_LITELLM_PROVIDER_PREFIXES):
        return model
    return f"{provider}/{model}"


# Block model prefixes that would route to a provider we don't call via the generic path:
# - Google needs litellm[google] (not installed) — would crash in vertex_llm_base with ImportError.
# - Native `cloudflare/...` bypasses per-call credential injection and the CLOUDFLARE_ALLOWED_MODELS
#   allowlist the `@cf/...` path enforces — reject so callers can't smuggle models onto gateway creds.
# Matches explicit prefixes (gemini/, vertex_ai/) and bare gemini- names litellm routes to vertex/gemini,
# which may not be in the cost registry yet when brand new.
_UNSUPPORTED_PROVIDERS = frozenset({"vertex_ai", "vertex_ai-language-models", "gemini", "cloudflare"})
_UNSUPPORTED_MODEL_PREFIXES = (
    *(f"{p}/" for p in _UNSUPPORTED_PROVIDERS),
    "gemini-",
)


class ProviderError(HTTPException):
    """An HTTPException raised from the upstream provider call itself, as opposed to gateway-local
    validation (unsupported model, bad headers, timeouts). Lets downstream handlers tell a genuine
    provider failure apart from a gateway 400 that merely echoes caller-controlled input — e.g. the
    Anthropic billing-block detector must not key off an unsupported-model message containing the
    caller's model name. Subclasses HTTPException so it serializes to the client identically.
    """


# Provider replies that mean the gateway's own upstream credentials were refused, rather than
# anything the caller did. OpenAI answers `invalid_organization` when the configured organization
# and the API key disagree; `invalid_api_key` covers a revoked or mistyped key. Keep this a tight
# allowlist: a caller-attributable 401 (an expired PostHog token) must keep its own message.
_CREDENTIAL_REJECTION_CODES: tuple[str, ...] = ("invalid_organization", "invalid_api_key")
# Fallback for providers that leave the error code empty. Matched case-insensitively.
_CREDENTIAL_REJECTION_SIGNATURES: tuple[str, ...] = (
    "organization tied to the api key",
    "no such organization",
    "incorrect api key provided",
)
# Also the client-facing error type and code, so callers can branch on one stable string.
CREDENTIAL_REJECTION_ERROR_TYPE = "provider_credentials_rejected"


def _is_credential_rejection(status_code: int, code: Any, message: str) -> bool:
    # litellm maps an upstream 401 onto several exception classes and does not always keep the
    # provider's status, so accept the 400 it falls back to as well as the 401/403 it sent.
    if status_code not in (400, 401, 403):
        return False
    if isinstance(code, str) and code.lower() in _CREDENTIAL_REJECTION_CODES:
        return True
    lowered = message.lower()
    # litellm reports the provider code inside the serialized upstream body, not on the exception.
    # Matched with its JSON quotes so a caller-chosen model name echoed into a 400 cannot pose as
    # a credential rejection.
    if any(f'"{rejection_code}"' in lowered for rejection_code in _CREDENTIAL_REJECTION_CODES):
        return True
    return any(signature in lowered for signature in _CREDENTIAL_REJECTION_SIGNATURES)


def classify_provider_failure(e: Exception, provider: str) -> tuple[str, ProviderError]:
    """The metrics label and the client-facing error for one upstream provider failure.

    A credential rejection gets gateway-owned copy instead of the upstream message. The raw text
    ("You do not have access to the organization tied to the API key") reads like an account or
    billing problem on the caller's side, so a person who sees it cannot tell it from a usage
    limit, and neither can a client that classifies errors by message. The upstream message stays
    in the logs and in error tracking.
    """
    status_code = getattr(e, "status_code", 500)
    message = getattr(e, "message", str(e))
    code = getattr(e, "code", None)
    if _is_credential_rejection(status_code, code, message):
        return CREDENTIAL_REJECTION_ERROR_TYPE, ProviderError(
            status_code=status_code,
            detail={
                "error": {
                    "message": (
                        f"PostHog's {provider} credentials were rejected. This is a problem with the "
                        "PostHog gateway, not a usage limit on your account. Retries fail until "
                        "PostHog fixes it."
                    ),
                    "type": CREDENTIAL_REJECTION_ERROR_TYPE,
                    "code": CREDENTIAL_REJECTION_ERROR_TYPE,
                }
            },
        )
    return type(e).__name__, ProviderError(
        status_code=status_code,
        detail={"error": {"message": message, "type": getattr(e, "type", "internal_error"), "code": code}},
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


# LLM routing/auth params — never accept from user input (request redirection, key exfiltration).
FORBIDDEN_REQUEST_PARAMS = frozenset(
    {"api_key", "api_base", "base_url", "api_version", "organization", "model_list", "fallbacks", "custom_llm_provider"}
)


def _sanitize_request_value(value: Any) -> Any:
    # Strip recursively: litellm forwards nested params (e.g. model_list[*].litellm_params.api_key)
    # to the provider, so a shallow filter is insufficient.
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

    rebuild_request_context(product)
    set_auth_user(user)

    # Stash effort for the PostHog callback to stamp on the $ai_generation event (mirrors
    # time_to_first_token). Set unconditionally so a stale value can't leak if the context
    # is reused.
    set_effort(provider_config.extract_effort(request_data))

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
        error_type, provider_error = classify_provider_failure(e, provider_config.name)
        PROVIDER_ERRORS.labels(provider=provider_config.name, error_type=error_type, product=product).inc()
        capture_exception(e, {"provider": provider_config.name, "model": model, "user_id": user.user_id})
        status_code = getattr(e, "status_code", 500)
        logger.exception(
            "llm_request_failed",
            endpoint=provider_config.endpoint_name,
            streaming=False,
            status_code=status_code,
            error_type=error_type,
            error_message=getattr(e, "message", str(e)),
            provider_error_type=getattr(e, "type", None),
            provider_error_code=getattr(e, "code", None),
        )
        raise provider_error from e
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
        error_type, provider_error = classify_provider_failure(e, provider_config.name)
        PROVIDER_ERRORS.labels(provider=provider_config.name, error_type=error_type, product=product).inc()
        capture_exception(e, {"provider": provider_config.name, "model": model, "streaming": True})
        status_code = getattr(e, "status_code", 500)
        logger.exception(
            "llm_request_failed",
            endpoint=provider_config.endpoint_name,
            streaming=True,
            status_code=status_code,
            error_type=error_type,
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
        raise provider_error from e

    async def stream_generator() -> AsyncGenerator[bytes]:
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
