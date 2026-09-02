from typing import Any

import posthoganalytics
import structlog

from llm_gateway.config import get_settings
from llm_gateway.provider_errors import provider_error_code

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
    an unsupported parameter must not share an issue. Returns None for a failure
    that did not come from a provider call, which keeps the default grouping.
    """
    provider = properties.get("provider")
    status = getattr(error, "status_code", None)
    if not provider or status is None:
        return None

    code = provider_error_code(error)
    return ":".join(
        [
            "llm-gateway",
            str(provider),
            type(error).__name__,
            str(status),
            # Truncated because the provider controls this value, and an
            # unbounded one would mint an issue per request.
            code[:100] if code else "unknown",
        ]
    )


def capture_exception(
    error: Exception | None = None,
    additional_properties: dict[str, Any] | None = None,
) -> None:
    if not _ensure_initialized():
        return

    properties = dict(additional_properties or {})
    if error is not None:
        fingerprint = _provider_error_fingerprint(error, properties)
        if fingerprint is not None:
            properties["$exception_fingerprint"] = fingerprint

    try:
        posthoganalytics.capture_exception(
            error,
            distinct_id="llm-gateway-service",
            properties=properties if properties else None,
        )
    except Exception as capture_error:
        logger.warning("failed_to_capture_exception", posthog_error=str(capture_error))
