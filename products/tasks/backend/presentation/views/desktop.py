from typing import cast

import posthoganalytics
from drf_spectacular.utils import extend_schema
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.event_usage import groups
from posthog.models.user import User
from posthog.permissions import OrganizationAdminWritePermissions

from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.presentation.desktop_serializers import DesktopBetaTermsAcceptanceSerializer


class DesktopBetaTermsViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "project"
    permission_classes = [OrganizationAdminWritePermissions]
    pagination_class = None

    def dangerously_get_required_scopes(self, request: Request, view) -> list[str] | None:
        if self.action in {"create", "revoke"}:
            return ["organization:write"]
        if self.action == "list" or request.method == "OPTIONS":
            return ["organization:read"]
        return None

    @extend_schema(responses={200: DesktopBetaTermsAcceptanceSerializer})
    def list(self, request: Request, **kwargs) -> Response:
        acceptance = tasks_facade.get_desktop_beta_terms_acceptance(self.organization.id)
        return Response(DesktopBetaTermsAcceptanceSerializer(acceptance).data)

    @extend_schema(request=None, responses={200: DesktopBetaTermsAcceptanceSerializer})
    def create(self, request: Request, **kwargs) -> Response:
        user = cast(User, request.user)
        acceptance = tasks_facade.accept_desktop_beta_terms(self.organization.id, user.id)
        return Response(DesktopBetaTermsAcceptanceSerializer(acceptance).data)

    @extend_schema(
        operation_id="desktop_beta_terms_revoke",
        request=None,
        responses={200: DesktopBetaTermsAcceptanceSerializer},
    )
    @action(detail=False, methods=["post"], url_path="revoke")
    def revoke(self, request: Request, **kwargs) -> Response:
        user = cast(User, request.user)
        was_revoked = tasks_facade.revoke_desktop_beta_terms(self.organization.id)
        if was_revoked:
            posthoganalytics.capture(
                distinct_id=user.distinct_id,
                event="desktop beta terms withdrawn",
                groups=groups(self.organization),
            )
        acceptance = tasks_facade.get_desktop_beta_terms_acceptance(self.organization.id)
        return Response(DesktopBetaTermsAcceptanceSerializer(acceptance).data)
