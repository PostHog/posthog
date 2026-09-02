import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

from django.conf import settings

import requests
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.auth import OAuthAccessTokenAuthentication
from posthog.models import OAuthAccessToken
from posthog.permissions import get_authenticator_scopes

if TYPE_CHECKING:
    from posthog.models import Organization, User
from posthog.temporal.oauth import SANDBOX_OAUTH_APP_CLIENT_IDS, create_oauth_access_token_for_user
from posthog.utils import get_instance_region

from products.tasks.backend.access import DesktopAccessResolutionError, get_desktop_access_decision
from products.tasks.backend.facade.contracts import DesktopAccessReason
from products.tasks.backend.logic.services.compute_quota import (
    COMPUTE_QUOTA_DENIAL_CODE,
    ORGANIZATION_DEACTIVATED_DENIAL_CODE,
    organization_deactivated,
)
from products.tasks.backend.metrics import observe_code_usage_gate_check
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
    """Structured 429 body the PostHog Desktop client parses into its upgrade prompt.

    Omits unknown bucket/reset fields so they don't render as null in the shared
    error serializer (which other error responses reuse).
    """
    payload: dict[str, Any] = {
        "type": "rate_limited",
        "code": "usage_limit_exceeded",
        "error": "You've reached your PostHog Desktop usage limit.",
        "is_pro": usage.is_pro,
    }
    if usage.limit_type is not None:
        payload["limit_type"] = usage.limit_type
    if usage.reset_at is not None:
        payload["reset_at"] = usage.reset_at
    return payload


def _billing_limit_response(code: str, error: str) -> Response:
    return Response(
        TaskRunErrorResponseSerializer({"type": "billing_limit", "code": code, "error": error}).data,
        status=status.HTTP_429_TOO_MANY_REQUESTS,
    )


def organization_deactivated_response() -> Response:
    return _billing_limit_response(
        ORGANIZATION_DEACTIVATED_DENIAL_CODE,
        "Your organization has been deactivated. Contact PostHog support if you think this is a mistake.",
    )


def compute_quota_limit_response(reason: str = COMPUTE_QUOTA_DENIAL_CODE) -> Response:
    if reason == ORGANIZATION_DEACTIVATED_DENIAL_CODE:
        return organization_deactivated_response()
    return _billing_limit_response(
        COMPUTE_QUOTA_DENIAL_CODE,
        "Your organization reached its PostHog Desktop usage limit.",
    )


def _task_bound_internal_run(request: Request, task_id: str | UUID | None) -> bool:
    authenticator = getattr(request, "successful_authenticator", None)
    authenticator_scopes = get_authenticator_scopes(authenticator) or []
    if "internal_run:read" not in authenticator_scopes or task_id is None:
        return False
    if not isinstance(authenticator, OAuthAccessTokenAuthentication):
        return False

    access_token = authenticator.access_token
    application = access_token.application
    if application is None or application.client_id not in SANDBOX_OAUTH_APP_CLIENT_IDS:
        return False

    try:
        parsed_task_id = UUID(str(task_id))
    except ValueError:
        return False
    return access_token.sandbox_task_id == parsed_task_id


def code_access_required_response(
    request: Request,
    organization: "Organization",
    *,
    task_id: str | UUID | None = None,
    fail_open_on_resolution_error: bool = False,
) -> Response | None:
    if _task_bound_internal_run(request, task_id):
        return None

    try:
        decision = get_desktop_access_decision(cast("User", request.user), organization)
    except DesktopAccessResolutionError:
        logger.warning(
            "desktop_access_resolution_failed",
            extra={"organization_id": organization.id, "fail_open": fail_open_on_resolution_error},
        )
        if fail_open_on_resolution_error:
            return None
        return Response(
            TaskRunErrorResponseSerializer(
                {
                    "type": "service_unavailable",
                    "code": "desktop_access_unavailable",
                    "error": "We couldn't verify PostHog Desktop access. Try again.",
                }
            ).data,
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    if decision.allowed:
        return None

    messages = {
        DesktopAccessReason.STARTUP_PLAN: (
            "PostHog Desktop isn't available for Startup or YC program organizations. "
            "Select another organization to continue."
        ),
        DesktopAccessReason.PREPAID_CREDITS: (
            "PostHog Desktop isn't available while this organization has prepaid credits. "
            "Select another organization to continue."
        ),
    }
    reason = decision.reason
    error_message = (
        messages[reason] if reason is not None else "PostHog Desktop access is required to run tasks in the cloud."
    )
    payload: dict[str, Any] = {
        "type": "permission_denied",
        "code": "code_access_required",
        "error": error_message,
    }
    if reason is not None:
        payload["reason"] = reason.value
    return Response(
        TaskRunErrorResponseSerializer(payload).data,
        status=status.HTTP_403_FORBIDDEN,
    )


def usage_limit_response(user, team_id: int) -> Response | None:
    """Return a 429 when the team is over its PostHog Desktop usage limit, else None.

    The cost backstop on cloud runs, applied on top of the entitlement gate above. Fails
    open when the gateway can't be reached, so every check is counted by outcome
    (`checked_allowed` / `checked_blocked` / `fail_open`) and a degraded gateway silently
    removing the backstop is visible, not just logged. Deactivated organizations are blocked
    locally first, so that block holds even when the gateway check fails open.
    """
    if organization_deactivated(team_id):
        observe_code_usage_gate_check(outcome="org_deactivated")
        return organization_deactivated_response()

    usage = get_posthog_code_usage(user, team_id)
    if usage is None:
        observe_code_usage_gate_check(outcome="fail_open")
        return None
    if not usage.is_rate_limited:
        observe_code_usage_gate_check(outcome="checked_allowed")
        return None
    observe_code_usage_gate_check(outcome="checked_blocked")
    return Response(
        TaskRunErrorResponseSerializer(rate_limit_error_payload(usage)).data,
        status=status.HTTP_429_TOO_MANY_REQUESTS,
    )
