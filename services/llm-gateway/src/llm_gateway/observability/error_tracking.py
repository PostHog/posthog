from typing import Any

import posthoganalytics
import structlog

from llm_gateway.config import get_settings
from llm_gateway.provider_errors import provider_error_code

logger = structlog.get_logger(__name__)

_initialized = False

# Provider codes can contain request-specific values. Only codes reviewed as
# stable may become issue keys, so a provider cannot create an issue per failure.
_LOW_CARDINALITY_PROVIDER_ERROR_CODES = frozenset(
    {
        "authentication_error",
        "context_length_exceeded",
        "invalid_api_key",
        "invalid_organization",
        "invalid_request_error",
        "model_not_found",
        "permission_denied",
        "rate_limit_exceeded",
        "unsupported_value",
    }
)


# Modal, Baseten, and Cloudflare are OpenAI-compatible servers that the gateway calls through
# litellm's `openai/` prefix, so litellm reports `openai` as the provider for their failures.
# The routed provider that the caller supplies names the real backend, so it wins for these three.
# Every other route can carry a `<provider>/<model>` id the caller chose, where litellm knows the
# true upstream and the routed provider is only the endpoint the request came in on.
_OPENAI_COMPATIBLE_BACKENDS = frozenset({"baseten", "cloudflare", "modal"})


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
    routed_provider = properties.get("provider")
    if routed_provider in _OPENAI_COMPATIBLE_BACKENDS:
        provider = routed_provider
    else:
        provider = getattr(error, "llm_provider", None) or routed_provider
    status = getattr(error, "status_code", None)
    if not provider or status is None:
        return None

    provider_code = provider_error_code(error)
    fingerprint_code = provider_code if provider_code in _LOW_CARDINALITY_PROVIDER_ERROR_CODES else "unknown"
    return ":".join(
        [
            "llm-gateway",
            str(provider),
            type(error).__name__,
            str(status),
            fingerprint_code,
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
