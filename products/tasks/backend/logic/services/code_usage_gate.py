import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.auth import OAuthAccessTokenAuthentication
from posthog.permissions import get_authenticator_scopes
from posthog.temporal.oauth import SANDBOX_OAUTH_APP_CLIENT_IDS

from products.tasks.backend.access import DesktopAccessResolutionError, get_desktop_access_decision
from products.tasks.backend.facade.contracts import DesktopAccessReason
from products.tasks.backend.logic.services.compute_quota import (
    COMPUTE_QUOTA_DENIAL_CODE,
    ORGANIZATION_DEACTIVATED_DENIAL_CODE,
    organization_deactivated,
)
from products.tasks.backend.metrics import observe_code_usage_gate_check
from products.tasks.backend.presentation.serializers import TaskRunErrorResponseSerializer

if TYPE_CHECKING:
    from posthog.models import Organization, User

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CodeUsageStatus:
    is_rate_limited: bool
    limit_type: str | None  # "burst" (daily) | "sustained" (monthly) | None
    reset_at: str | None  # ISO 8601, the billing period end when known
    is_pro: bool


def get_posthog_code_usage(user, team_id: int) -> CodeUsageStatus | None:
    """None (fail open) on any failure, so a Redis or DB error never blocks task creation."""
    from posthog.models import Team  # noqa: PLC0415

    from ee.billing.quota_limiting import QuotaResource, is_team_over_credit_budget  # noqa: PLC0415

    try:
        team = Team.objects.select_related("organization").get(id=team_id)
        limited = is_team_over_credit_budget(team.api_token, QuotaResource.POSTHOG_CODE_CREDITS)
        if not limited:
            return CodeUsageStatus(is_rate_limited=False, limit_type=None, reset_at=None, is_pro=False)
        period = team.organization.current_billing_period
    except Exception:
        logger.warning("code_usage_gate: credit bucket check failed", exc_info=True)
        return None
    return CodeUsageStatus(
        is_rate_limited=True,
        limit_type=None,
        reset_at=period.end.isoformat() if period else None,
        is_pro=False,
    )


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
    open when the credit bucket can't be read, so every check is counted by outcome
    (`checked_allowed` / `checked_blocked` / `fail_open`) and a silently removed backstop is
    visible, not just logged. Deactivated organizations are blocked first.
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
