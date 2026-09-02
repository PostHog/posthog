from typing import cast

from drf_spectacular.utils import extend_schema
from rest_framework import viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models.user import User
from posthog.permissions import OrganizationAdminWritePermissions

from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.presentation.desktop_serializers import DesktopBetaTermsAcceptanceSerializer


class DesktopBetaTermsViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "organization"
    permission_classes = [OrganizationAdminWritePermissions]
    pagination_class = None

    @extend_schema(responses={200: DesktopBetaTermsAcceptanceSerializer})
    def list(self, request: Request, **kwargs) -> Response:
        acceptance = tasks_facade.get_desktop_beta_terms_acceptance(self.organization.id)
        return Response(DesktopBetaTermsAcceptanceSerializer(acceptance).data)

    @extend_schema(request=None, responses={200: DesktopBetaTermsAcceptanceSerializer})
    def create(self, request: Request, **kwargs) -> Response:
        user = cast(User, request.user)
        acceptance = tasks_facade.accept_desktop_beta_terms(self.organization.id, user.id)
        return Response(DesktopBetaTermsAcceptanceSerializer(acceptance).data)
