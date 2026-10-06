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
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView

from posthog.auth import ScopedServiceJWTAuthentication

from ..facade.hub import (
    INTERNAL_PURPOSE,
    count_accounts,
    count_org_members,
    mfa_bypasses,
    posthog_account_exists,
    record_call,
    resolve,
    token_allows,
)
from ..facade.temporal import start_sync_now
from .serializers import (
    CountAccountsRequestSerializer,
    CountResponseSerializer,
    MfaExportResponseSerializer,
    OrgMemberCountRequestSerializer,
    OrgMemberCountResponseSerializer,
    PosthogMembershipRequestSerializer,
    PosthogMembershipResponseSerializer,
    ResolveRequestSerializer,
    ResolveResponseSerializer,
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


class HubOperationPermission(BasePermission):
    """Checks the token's op, region and lifetime. DRF runs permissions before throttles, so a refused token never spends the shared budget."""

    message = "This token is not valid for this operation."

    def has_permission(self, request: Request, view: APIView) -> bool:
        return token_allows(cast(dict[str, Any], request.auth or {}), cast(_HubView, view).op)


class _HubView(APIView):
    authentication_classes = [SecurityHubAuthentication]
    permission_classes = [IsAuthenticated, HubOperationPermission]
    throttle_classes = [SecurityHubThrottle]
    http_method_names = ["post", "options"]
    op: ClassVar[str]

    def initial(self, request: Request, *args: Any, **kwargs: Any) -> None:
        super().initial(request, *args, **kwargs)
        record_call(self.op)


class ResolveView(_HubView):
    op = "subject:resolve"

    @extend_schema(exclude=True)
    def post(self, request: Request) -> Response:
        serializer = ResolveRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        resolved = resolve(serializer.validated_data["query"])
        user = resolved.user
        organization = None
        if resolved.kind == "organization" and resolved.organization_ids:
            organization = {"id": resolved.organization_ids[0], "exists": True}
        payload = {
            "kind": resolved.kind,
            "user": {"uuid": user.uuid, "email": user.email, "is_active": user.is_active} if user else None,
            "organization_ids": list(resolved.organization_ids),
            "organization": organization,
        }
        return Response(ResolveResponseSerializer(payload).data)


class CountAccountsView(_HubView):
    op = "accounts:count"

    @extend_schema(exclude=True)
    def post(self, request: Request) -> Response:
        serializer = CountAccountsRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        counted = count_accounts(serializer.validated_data["target_type"], serializer.validated_data["target_value"])
        return Response(CountResponseSerializer(counted).data)


class OrgMemberCountView(_HubView):
    op = "org:member_count"

    @extend_schema(exclude=True)
    def post(self, request: Request) -> Response:
        serializer = OrgMemberCountRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        exists, members = count_org_members(str(serializer.validated_data["organization_id"]))
        payload = {"exists": exists, "active_members": members.count, "capped": members.capped}
        return Response(OrgMemberCountResponseSerializer(payload).data)


class PosthogMembershipView(_HubView):
    op = "posthog_membership:check"

    @extend_schema(exclude=True)
    def post(self, request: Request) -> Response:
        serializer = PosthogMembershipRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if "user_uuid" in data:
            found = posthog_account_exists(user_uuid=str(data["user_uuid"]))
        else:
            found = posthog_account_exists(organization_id=str(data["organization_id"]))
        return Response(PosthogMembershipResponseSerializer({"has_posthog_account": found}).data)


class SyncNowView(_HubView):
    op = "rules:sync_now"

    @extend_schema(exclude=True)
    def post(self, request: Request) -> Response:
        # The hub does not wait for the pull, and the 5-minute schedule is the backstop.
        try:
            start_sync_now()
        except Exception:
            logger.exception("security_hub_sync_now_failed")
            return Response(status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response(status=status.HTTP_202_ACCEPTED)


class MfaBypassExportView(_HubView):
    op = "mfa_bypass:export"

    @extend_schema(exclude=True)
    def post(self, request: Request) -> Response:
        exported = mfa_bypasses()
        return Response(MfaExportResponseSerializer(exported).data)


urlpatterns = [
    path("resolve/", csrf_exempt(ResolveView.as_view())),
    path("count-accounts/", csrf_exempt(CountAccountsView.as_view())),
    path("org-member-count/", csrf_exempt(OrgMemberCountView.as_view())),
    path("posthog-membership/", csrf_exempt(PosthogMembershipView.as_view())),
    path("sync-now/", csrf_exempt(SyncNowView.as_view())),
    path("mfa-bypass-export/", csrf_exempt(MfaBypassExportView.as_view())),
]
