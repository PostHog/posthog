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

    posthoganalytics.api_key = settings.posthog_project_token
    _initialized = True
    return True


def capture_exception(
    error: Exception | None = None,
    additional_properties: dict[str, Any] | None = None,
) -> None:
    properties = additional_properties or {}

    if not _ensure_initialized():
        return

    try:
        posthoganalytics.capture(
            distinct_id="llm-gateway-service",
            event="$exception",
            properties={
                "$exception_type": type(error).__name__ if error else "Unknown",
                "$exception_message": str(error) if error else "No message",
                **properties,
            },
        )
    except Exception as capture_error:
        logger.warning("failed_to_capture_exception", posthog_error=str(capture_error))
