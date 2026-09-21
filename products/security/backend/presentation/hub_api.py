"""
Routes the security hub calls in this region.

The hub runs outside the cluster, so these routes sit on the public /api/ path. Contour
does not expose /api/internal/. A scoped HS256 token pinned to this region and one
operation is the only gate, and one global throttle caps the traffic.
"""

from typing import Any, ClassVar, cast

from django.urls import path
from django.views.decorators.csrf import csrf_exempt

import structlog
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView

from posthog.auth import ScopedServiceJWTAuthentication

from ..facade.temporal import start_sync_now
from ..logic.accounts import count_active_accounts, count_active_org_members, has_posthog_account, resolve_subject
from ..logic.hub_auth import INTERNAL_PURPOSE, claims_allow
from ..logic.mfa_export import export_mfa_bypasses
from ..metrics import HUB_API_AUTH_COUNTER
from .serializers import (
    CountAccountsRequestSerializer,
    OrgMemberCountRequestSerializer,
    PosthogMembershipRequestSerializer,
    ResolveRequestSerializer,
)

logger = structlog.get_logger(__name__)


class SecurityHubAuthentication(ScopedServiceJWTAuthentication):
    purpose = INTERNAL_PURPOSE
    require_team = False


class SecurityHubThrottle(SimpleRateThrottle):
    """One budget for every hub route together, whoever the caller is."""

    scope = "security_hub"
    rate = "100/minute"

    def get_cache_key(self, request: Request, view: APIView) -> str:
        return self.cache_format % {"scope": self.scope, "ident": "global"}


class _HubView(APIView):
    authentication_classes = [SecurityHubAuthentication]
    permission_classes = [IsAuthenticated]
    throttle_classes = [SecurityHubThrottle]
    http_method_names = ["post", "options"]
    op: ClassVar[str]

    def initial(self, request: Request, *args: Any, **kwargs: Any) -> None:
        super().initial(request, *args, **kwargs)
        claims = cast(dict[str, Any], request.auth or {})
        if not claims_allow(claims, self.op):
            raise PermissionDenied("This token is not valid for this operation.")
        HUB_API_AUTH_COUNTER.labels(op=self.op).inc()


class ResolveView(_HubView):
    op = "subject:resolve"

    @extend_schema(exclude=True)
    def post(self, request: Request) -> Response:
        serializer = ResolveRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        resolved = resolve_subject(serializer.validated_data["query"])
        user = resolved.user
        organization = None
        if resolved.kind == "organization" and resolved.organization_ids:
            organization = {"id": resolved.organization_ids[0], "exists": True}
        return Response(
            {
                "kind": resolved.kind,
                "user": {"uuid": user.uuid, "email": user.email, "is_active": user.is_active} if user else None,
                "organization_ids": list(resolved.organization_ids),
                "organization": organization,
            }
        )


class CountAccountsView(_HubView):
    op = "accounts:count"

    @extend_schema(exclude=True)
    def post(self, request: Request) -> Response:
        serializer = CountAccountsRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        counted = count_active_accounts(
            serializer.validated_data["target_type"], serializer.validated_data["target_value"]
        )
        return Response({"count": counted.count, "capped": counted.capped})


class OrgMemberCountView(_HubView):
    op = "org:member_count"

    @extend_schema(exclude=True)
    def post(self, request: Request) -> Response:
        serializer = OrgMemberCountRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        exists, members = count_active_org_members(str(serializer.validated_data["organization_id"]))
        return Response({"exists": exists, "active_members": members.count, "capped": members.capped})


class PosthogMembershipView(_HubView):
    op = "posthog_membership:check"

    @extend_schema(exclude=True)
    def post(self, request: Request) -> Response:
        serializer = PosthogMembershipRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if "user_uuid" in data:
            found = has_posthog_account(user_uuid=str(data["user_uuid"]))
        else:
            found = has_posthog_account(organization_id=str(data["organization_id"]))
        return Response({"has_posthog_account": found})


class SyncNowView(_HubView):
    op = "rules:sync_now"

    @extend_schema(exclude=True)
    def post(self, request: Request) -> Response:
        # The hub does not wait for the pull, and the 5-minute schedule is the backstop.
        try:
            start_sync_now()
        except Exception:
            logger.exception("security_hub_sync_now_failed")
            return Response({}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response({}, status=status.HTTP_202_ACCEPTED)


class MfaBypassExportView(_HubView):
    op = "mfa_bypass:export"

    @extend_schema(exclude=True)
    def post(self, request: Request) -> Response:
        exported = export_mfa_bypasses()
        bypass = exported.global_bypass
        return Response(
            {
                "emails": list(exported.emails),
                "global": {"reason": bypass.reason, "actor": bypass.actor, "expires_at": bypass.expires_at.isoformat()}
                if bypass
                else None,
            }
        )


urlpatterns = [
    path("resolve/", csrf_exempt(ResolveView.as_view())),
    path("count-accounts/", csrf_exempt(CountAccountsView.as_view())),
    path("org-member-count/", csrf_exempt(OrgMemberCountView.as_view())),
    path("posthog-membership/", csrf_exempt(PosthogMembershipView.as_view())),
    path("sync-now/", csrf_exempt(SyncNowView.as_view())),
    path("mfa-bypass-export/", csrf_exempt(MfaBypassExportView.as_view())),
]
