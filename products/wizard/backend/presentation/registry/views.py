from typing import cast

from drf_spectacular.utils import extend_schema
from rest_framework import viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import User

from products.wizard.backend.facade import api as wizard_facade
from products.wizard.backend.presentation.permissions import WizardRunSessionAuthenticationRequired
from products.wizard.backend.presentation.registry.pagination import WizardRegistryPagination
from products.wizard.backend.presentation.registry.serializers import WizardProgramSerializer


class WizardRegistryViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    permission_classes = [WizardRunSessionAuthenticationRequired]
    scope_object = "wizard_session"
    scope_object_read_actions = ["list"]
    http_method_names = ["get", "head", "options"]
    pagination_class = WizardRegistryPagination

    @extend_schema(
        responses={200: WizardProgramSerializer(many=True)},
        description="List Wizard programs available for this project.",
    )
    def list(self, request: Request, *args: object, **kwargs: object) -> Response:
        # GET /projects/:projectId/wizard/registry
        user = cast(User, request.user)
        programs = wizard_facade.get_registry(
            distinct_id=cast(str, user.distinct_id),
            organization_id=str(self.team.organization_id),
        )
        page = self.paginate_queryset(programs)
        assert page is not None
        return self.get_paginated_response(WizardProgramSerializer(page, many=True).data)
