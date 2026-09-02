from typing import Any

import posthoganalytics
import structlog

from llm_gateway.config import get_settings

logger = structlog.get_logger(__name__)

_initialized = False


def _ensure_initialized() -> bool:
    global _initialized
    if _initialized:
        return True

    settings = get_settings()
    if not settings.posthog_project_token:
        return False

    posthoganalytics.api_key = settings.posthog_project_token  # ty: ignore[invalid-assignment]
    _initialized = True
    return True


def _provider_error_fingerprint(error: Exception, properties: dict[str, Any]) -> str | None:
    """Group a provider failure by what the provider rejected.

    litellm raises the same exception type from the same line for every provider
    4xx, so the default type-and-stack grouping merges unrelated failures into one
    issue that carries the title of whichever came first. An expired credential and
    an unsupported parameter must not share an issue. Returns None for exceptions
    that carry no provider status, which keeps the default grouping.
    """
    status = _fingerprint_part(getattr(error, "status_code", None))
    if status is None:
        return None

    provider = _fingerprint_part(properties.get("provider"))
    return ":".join(
        [
            "llm-gateway",
            provider or "unknown",
            type(error).__name__,
            status,
            _provider_error_code(error) or "unknown",
        ]
    )


def _provider_error_code(error: Exception) -> str | None:
    """Read the provider's own error code, for example `invalid_organization`.

    litellm copies the code onto the exception for some provider failures and
    leaves it on the response payload for the rest, so both are read.
    """
    direct = _fingerprint_part(getattr(error, "code", None)) or _fingerprint_part(getattr(error, "type", None))
    if direct:
        return direct

    payload = getattr(error, "body", None) or _read_response_payload(getattr(error, "response", None))
    return _fingerprint_part(_code_from_payload(payload))


def _read_response_payload(response: object) -> object:
    reader = getattr(response, "json", None)
    if not callable(reader):
        return None
    try:
        return reader()
    except Exception:
        # A grouping key is not worth an exception. litellm also builds
        # placeholder responses that carry no body at all.
        return None


def _code_from_payload(payload: object) -> object:
    if not isinstance(payload, dict):
        return None
    error = payload.get("error")
    fields = error if isinstance(error, dict) else payload
    return fields.get("code") or fields.get("type")


def _fingerprint_part(value: object) -> str | None:
    if value is None:
        return None
    # Truncated because a provider controls these values, and an unbounded one
    # would mint an issue per request.
    text = str(value).strip()[:100]
    return text or None


def capture_exception(
    error: Exception | None = None,
    additional_properties: dict[str, Any] | None = None,
) -> None:
    properties = dict(additional_properties or {})

    if error is not None:
        fingerprint = _provider_error_fingerprint(error, properties)
        if fingerprint is not None:
            properties["$exception_fingerprint"] = fingerprint

    if not _ensure_initialized():
        return

    try:
        posthoganalytics.capture_exception(
            error,
            distinct_id="llm-gateway-service",
            properties=properties if properties else None,
        )
    except Exception as capture_error:
        logger.warning("failed_to_capture_exception", posthog_error=str(capture_error))
