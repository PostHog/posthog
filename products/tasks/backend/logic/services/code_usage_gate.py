import logging
from dataclasses import dataclass
from typing import Any

from django.conf import settings

import requests
from rest_framework import status
from rest_framework.response import Response

from posthog.models import OAuthAccessToken
from posthog.temporal.oauth import create_oauth_access_token_for_user
from posthog.utils import get_instance_region

from products.tasks.backend.presentation.serializers import TaskRunErrorResponseSerializer

logger = logging.getLogger(__name__)

GATEWAY_PRODUCT = "posthog_code"

# Short timeout: this runs on the creation hot path; on failure we fail open.
GATEWAY_USAGE_TIMEOUT_SECONDS = 2.5


@dataclass(frozen=True)
class CodeUsageStatus:
    is_rate_limited: bool
    limit_type: str | None  # "burst" (daily) | "sustained" (monthly) | None
    reset_at: str | None  # ISO 8601 string from the gateway, when known
    is_pro: bool


def _gateway_usage_url() -> str | None:
    """Resolve the LLM gateway usage endpoint for this deployment.

    Region-based in cloud, the local gateway (localhost:3308, matching the
    desktop client) under DEBUG. Returns None when no gateway applies, so
    callers fail open.
    """
    region = get_instance_region()
    if region == "US":
        base = "https://gateway.us.posthog.com"
    elif region == "EU":
        base = "https://gateway.eu.posthog.com"
    elif settings.DEBUG:
        base = "http://localhost:3308"
    else:
        return None
    return f"{base}/v1/usage/{GATEWAY_PRODUCT}"


def _parse_usage(data: dict[str, Any]) -> CodeUsageStatus:
    sustained = data.get("sustained") or {}
    burst = data.get("burst") or {}
    sustained_exceeded = bool(sustained.get("exceeded"))
    burst_exceeded = bool(burst.get("exceeded"))
    is_limited = bool(data.get("is_rate_limited")) or sustained_exceeded or burst_exceeded

    # Surface the bucket that's actually over for the reset hint; burst (daily) takes priority.
    if burst_exceeded:
        limit_type, reset_at = "burst", burst.get("reset_at")
    elif sustained_exceeded:
        limit_type, reset_at = "sustained", sustained.get("reset_at")
    else:
        limit_type, reset_at = None, None

    return CodeUsageStatus(
        is_rate_limited=is_limited,
        limit_type=limit_type,
        reset_at=reset_at,
        is_pro=bool(data.get("is_pro")),
    )


def get_posthog_code_usage(user, team_id: int) -> CodeUsageStatus | None:
    """Fetch the team's posthog_code usage from the LLM gateway.

    Returns None (fail open) on any failure — gateway hiccups must never block
    task creation. Mints a short-lived, least-privilege `llm_gateway:read` token
    the same way the sandbox agent authenticates to the gateway.
    """
    url = _gateway_usage_url()
    if not url:
        return None

    try:
        token = create_oauth_access_token_for_user(
            user, team_id, scopes=["llm_gateway:read"], include_internal_scopes=False
        )
    except Exception:
        logger.warning("code_usage_gate: failed to mint gateway token", exc_info=True)
        return None

    try:
        response = requests.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=GATEWAY_USAGE_TIMEOUT_SECONDS,
        )
        if response.status_code != 200:
            logger.warning("code_usage_gate: gateway usage returned %s", response.status_code)
            return None
        return _parse_usage(response.json())
    except requests.RequestException:
        logger.warning("code_usage_gate: gateway usage request failed", exc_info=True)
        return None
    except (ValueError, AttributeError):
        logger.warning("code_usage_gate: could not parse gateway usage response", exc_info=True)
        return None
    finally:
        # Short-lived token: delete it so repeated gate checks don't pile up OAuthAccessToken rows.
        # Swallow cleanup errors so a DB hiccup here can't break the fail-open guarantee.
        try:
            OAuthAccessToken.objects.filter(token=token).delete()
        except Exception:
            logger.warning("code_usage_gate: failed to delete gateway token", exc_info=True)


def rate_limit_error_payload(usage: CodeUsageStatus) -> dict[str, Any]:
    """Structured 429 body the PostHog Code client parses into its upgrade prompt.

    Omits unknown bucket/reset fields so they don't render as null in the shared
    error serializer (which other error responses reuse).
    """
    payload: dict[str, Any] = {
        "type": "rate_limited",
        "code": "usage_limit_exceeded",
        "error": "You've reached your PostHog Code usage limit.",
        "is_pro": usage.is_pro,
    }
    if usage.limit_type is not None:
        payload["limit_type"] = usage.limit_type
    if usage.reset_at is not None:
        payload["reset_at"] = usage.reset_at
    return payload


def cloud_usage_limit_response(user, team_id: int) -> Response | None:
    """Return a structured 429 Response when the team is over its posthog_code usage limit, else None.

    Fails open: if the gateway can't be reached, returns None and the run proceeds.
    """
    usage = get_posthog_code_usage(user, team_id)
    if usage is None or not usage.is_rate_limited:
        return None
    return Response(
        TaskRunErrorResponseSerializer(rate_limit_error_payload(usage)).data,
        status=status.HTTP_429_TOO_MANY_REQUESTS,
    )
