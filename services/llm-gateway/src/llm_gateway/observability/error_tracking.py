from typing import Any

import posthoganalytics
import structlog

from llm_gateway.config import get_settings
from llm_gateway.request_context import get_auth_user, get_product, is_private_scout_request

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
    posthoganalytics.host = settings.posthog_host  # ty: ignore[invalid-assignment]
    _initialized = True
    return True


def capture_exception(
    error: Exception | None = None,
    additional_properties: dict[str, Any] | None = None,
) -> None:
    if is_private_scout_request(get_auth_user(), get_product()):
        return
    properties = additional_properties or {}

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
