from datetime import UTC, datetime, timedelta
from typing import Any, cast

from django.conf import settings
from django.utils import timezone

import posthoganalytics
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from posthog.api.email_verification import email_verification_pending
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication
from posthog.exceptions_capture import capture_exception
from posthog.llm.wizard_blocklist import wizard_identity_blocked
from posthog.models import User
from posthog.models.oauth import OAuthAccessToken
from posthog.permissions import APIScopePermission
from posthog.storage.gateway_credential_cache import GATEWAY_CREDENTIAL_REQUIRED_SCOPE, oauth_credential_authorized
from posthog.temporal.oauth import POSTHOG_CODE_OAUTH_APP_CLIENT_IDS

from products.tasks.backend.facade.access import (
    DesktopAccessResolutionError,
    compute_quota_limit_response,
    get_desktop_access_decision,
)
from products.tasks.backend.facade.contracts import ComputeQuotaDenialReason
from products.tasks.backend.facade.desktop_gateway import (
    CREDIT_BUCKET_EXHAUSTED_DENIAL,
    DESKTOP_AGENT_MODELS,
    POSTHOG_CODE_CREDITS_EXHAUSTED_DETAIL,
    POSTHOG_CODE_PRODUCT,
    DesktopGatewayMintError,
    desktop_gateway_base_url,
    desktop_gateway_configured,
    desktop_rollout_enabled,
    desktop_token_ttl_seconds,
    mint_desktop_gateway_token,
    plan_allowed_models,
    posthog_code_plan,
    team_credit_refusal,
)
from products.tasks.backend.presentation.serializers import (
    DesktopAccessResponseSerializer,
    DesktopGatewayTokenRefusalSerializer,
    DesktopGatewayTokenSerializer,
    DesktopUsageSerializer,
    TaskRunErrorResponseSerializer,
)

from ee.billing.quota_limiting import team_quota_snapshot

# The legacy gateway's usage windows for posthog_code, which its cost throttles exempt.
_BURST_WINDOW_SECONDS = 86400
_SUSTAINED_WINDOW_SECONDS = 2592000
_USD_PER_CREDIT = 0.01
_DESKTOP_COMPONENT_RESOURCES = {
    "token_credits": "posthog_code_token_credits",
    "compute_credits": "sandbox_compute_credits",
    "cpu_millicore_seconds": "sandbox_compute_cpu_millicore_seconds",
    "memory_mib_seconds": "sandbox_compute_memory_mib_seconds",
}

_DESKTOP_ACCESS_MESSAGES = {
    "startup_plan": "PostHog Desktop isn't available for Startup or YC program organizations.",
    "prepaid_credits": "PostHog Desktop isn't available while this organization has prepaid credits.",
}


class DesktopGatewayTokenThrottle(UserRateThrottle):
    """Every desktop caller's request spends a slot, refusals included."""

    scope = "desktop_gateway_token"

    def get_rate(self) -> str:
        return f"{int(settings.DESKTOP_GATEWAY_MINTS_PER_HOUR)}/hour"


def _disabled(reason: str, http_status: int = status.HTTP_200_OK, **extra: Any) -> Response:
    payload = {"enabled": False, "reason": reason, **extra}
    return Response(DesktopGatewayTokenRefusalSerializer(payload).data, status=http_status)


def _desktop_oauth_credential(request: Request) -> tuple[OAuthAccessToken | None, Response | None]:
    authenticator = getattr(request, "successful_authenticator", None)
    if not isinstance(authenticator, OAuthAccessTokenAuthentication):
        return None, _disabled("oauth_required", status.HTTP_403_FORBIDDEN, detail="Sign in with PostHog Desktop.")
    access_token = authenticator.access_token
    application = getattr(access_token, "application", None)
    client_id = getattr(application, "client_id", None)
    # The raw scope text: `*` and filtered scope lists must not stand in for the gateway scope.
    raw_scopes = (access_token.scope or "").split()
    if (
        client_id not in POSTHOG_CODE_OAUTH_APP_CLIENT_IDS
        or GATEWAY_CREDENTIAL_REQUIRED_SCOPE not in raw_scopes
        # Sandbox tokens mint through the worker, under the run's own cap and lifetime.
        or "internal_run:read" in raw_scopes
        or access_token.sandbox_task_id is not None
        or access_token.impersonated_by_id is not None
    ):
        return None, _disabled(
            "oauth_required",
            status.HTTP_403_FORBIDDEN,
            detail="This credential cannot mint PostHog Desktop gateway tokens.",
        )
    return access_token, None


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _exempt_window(now: datetime, window_seconds: int) -> dict[str, Any]:
    return {
        "used_percent": 0.0,
        "resets_in_seconds": window_seconds,
        "reset_at": _iso(now + timedelta(seconds=window_seconds)),
        "exceeded": False,
    }


def _optional_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _credits_to_usd(credits: object) -> float | None:
    value = _optional_number(credits)
    return None if value is None else round(value * _USD_PER_CREDIT, 2)


def _optional_integer(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _desktop_usage_breakdown(limited: dict[str, Any]) -> dict[str, int | None] | None:
    components = {
        key: _optional_integer((limited.get(resource) or {}).get("usage"))
        for key, resource in _DESKTOP_COMPONENT_RESOURCES.items()
    }
    return None if all(value is None for value in components.values()) else components


@extend_schema(tags=["tasks"])
class DesktopAccessViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    authentication_classes = [
        SessionAuthentication,
        PersonalAPIKeyAuthentication,
        OAuthAccessTokenAuthentication,
    ]
    permission_classes = [IsAuthenticated, APIScopePermission]
    scope_object = "task"
    pagination_class = None
    serializer_class = DesktopAccessResponseSerializer

    @extend_schema(
        responses={
            200: OpenApiResponse(response=DesktopAccessResponseSerializer),
            503: OpenApiResponse(response=TaskRunErrorResponseSerializer),
        },
        summary="Check PostHog Desktop access",
        description="Evaluate Desktop access for the selected project and organization.",
    )
    @action(detail=False, methods=["get"], url_path="access", required_scopes=["llm_gateway:read"])
    def access(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        try:
            decision = get_desktop_access_decision(cast(User, request.user), self.organization)
        except DesktopAccessResolutionError:
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

        return Response(
            DesktopAccessResponseSerializer(
                {
                    "allowed": decision.allowed,
                    "reason": decision.reason.value if decision.reason is not None else None,
                }
            ).data
        )

    # App-only credential endpoint, so it stays out of generated clients and MCP tools.
    @extend_schema(exclude=True)
    @action(detail=False, methods=["post"], url_path="gateway_token", required_scopes=["llm_gateway:read"])
    def gateway_token(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Mints a `phe_` pinned to this team, the user and the plan's models. Any non-201 keeps the
        app on the legacy gateway."""
        access_token, refusal = _desktop_oauth_credential(request)
        if refusal is not None or access_token is None:
            return refusal or _disabled("oauth_required", status.HTTP_403_FORBIDDEN)
        if not DesktopGatewayTokenThrottle().allow_request(request, self):
            return _disabled(
                "throttled", status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many gateway token requests. Try later."
            )
        user = cast(User, request.user)
        team = self.team
        organization = self.organization

        if email_verification_pending(user):
            return _disabled("email_unverified", status.HTTP_403_FORBIDDEN, detail="Verify your email to continue.")
        # scoped_teams is frozen at consent, so re-check membership and project access.
        if not oauth_credential_authorized(access_token, team):
            return _disabled(
                "unauthorized",
                status.HTTP_403_FORBIDDEN,
                detail="This credential is no longer authorized for this project.",
            )
        if not user.distinct_id:
            return _disabled("oauth_required", status.HTTP_403_FORBIDDEN, detail="This account has no identity.")
        distinct_id = str(user.distinct_id)
        if wizard_identity_blocked(
            distinct_id=distinct_id,
            email=user.email,
            user_uuid=str(user.uuid),
            organization_ids=[str(organization.id)],
            team_ids=[team.id],
            surface="desktop_gateway_token",
        ):
            return _disabled("blocked", status.HTTP_403_FORBIDDEN, detail="This account cannot use the AI gateway.")

        if not desktop_gateway_configured():
            return _disabled("unconfigured")
        if not desktop_rollout_enabled(organization, team, distinct_id):
            return _disabled("not_rolled_out")

        try:
            # Cache funding for one token lifetime: the app re-mints that often, so staleness stays within a token.
            decision = get_desktop_access_decision(
                user, organization, funding_cache_seconds=desktop_token_ttl_seconds()
            )
        except DesktopAccessResolutionError:
            return _disabled(
                "desktop_access_unavailable",
                status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="We couldn't verify PostHog Desktop access. Try again.",
            )
        if not decision.allowed:
            access_reason = decision.reason.value if decision.reason is not None else None
            return _disabled(
                "desktop_access_blocked",
                status.HTTP_403_FORBIDDEN,
                access={"allowed": False, "reason": access_reason},
                detail=_DESKTOP_ACCESS_MESSAGES.get(access_reason or "", "PostHog Desktop access is required."),
            )

        try:
            credit_refusal = team_credit_refusal(team.id, "posthog_code_credits")
        except Exception as e:
            capture_exception(e, {"ai_product": POSTHOG_CODE_PRODUCT, "team_id": team.id})
            return _disabled("credit_state_unknown")
        if credit_refusal == "org_deactivated":
            return compute_quota_limit_response(ComputeQuotaDenialReason.ORGANIZATION_DEACTIVATED)
        if credit_refusal is not None:
            response = _disabled(
                "credit_bucket_exhausted",
                status.HTTP_402_PAYMENT_REQUIRED,
                detail=POSTHOG_CODE_CREDITS_EXHAUSTED_DETAIL,
            )
            response["X-PostHog-Denial"] = CREDIT_BUCKET_EXHAUSTED_DENIAL
            return response

        plan = posthog_code_plan(team)
        allowed_models = plan_allowed_models(plan)
        try:
            minted = mint_desktop_gateway_token(team_id=team.id, user=distinct_id, allowed_models=allowed_models)
        except DesktopGatewayMintError as e:
            if e.rate_limited:
                # The shared mint ceiling is counted and logged at the mint, so skip the per-session capture.
                return _disabled(
                    "mint_failed", status.HTTP_503_SERVICE_UNAVAILABLE, detail="Gateway token mint failed."
                )
            with posthoganalytics.new_context():
                posthoganalytics.set_capture_exception_code_variables_context(False)
                capture_exception(e, {"ai_product": POSTHOG_CODE_PRODUCT, "team_id": team.id})
            return _disabled("mint_failed", status.HTTP_503_SERVICE_UNAVAILABLE, detail="Gateway token mint failed.")

        echoed_models = minted.get("allowed_models")
        payload = {
            "enabled": True,
            "token": minted["token"],
            "expires_at": minted["expires_at"],
            "cap_usd": minted.get("cap_usd"),
            "gateway_url": desktop_gateway_base_url(),
            "product": POSTHOG_CODE_PRODUCT,
            "team_id": team.id,
            "plan": plan,
            # Go echoes only the pin it stored; a gateway without the echo stored what was sent.
            "allowed_models": echoed_models if isinstance(echoed_models, list) else allowed_models,
            "product_models": list(DESKTOP_AGENT_MODELS),
        }
        return Response(DesktopGatewayTokenSerializer(payload).data, status=status.HTTP_201_CREATED)

    @extend_schema(exclude=True)
    @action(detail=False, methods=["get"], url_path="usage", required_scopes=["llm_gateway:read"])
    def usage(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """The legacy gateway's `/v1/usage/posthog_code` body, from Django's own quota state."""
        snapshot = team_quota_snapshot(self.team)
        limited = snapshot["limited"]
        bucket = limited.get("posthog_code_credits") or {}
        exhausted = bool(bucket.get("limited"))
        now = timezone.now()
        period = self.organization.current_billing_period
        payload = {
            "product": POSTHOG_CODE_PRODUCT,
            "user_id": request.user.pk,
            "burst": _exempt_window(now, _BURST_WINDOW_SECONDS),
            "sustained": _exempt_window(now, _SUSTAINED_WINDOW_SECONDS),
            "ai_credits": {
                "exhausted": exhausted,
                "used_usd": _credits_to_usd(bucket.get("usage")),
                "limit_usd": _credits_to_usd(bucket.get("limit")),
                "breakdown": _desktop_usage_breakdown(limited),
            },
            "is_rate_limited": exhausted,
            # Older app builds require the field; no caller holds a Pro seat.
            "is_pro": False,
            "code_usage_subscribed": bool(snapshot["code_usage_billing_active"]),
            "billing_period_end": _iso(period.end) if period is not None else None,
        }
        return Response(DesktopUsageSerializer(payload).data)
