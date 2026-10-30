from typing import cast
from uuid import UUID

from django.conf import settings

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.exceptions import NotFound
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.models import User
from posthog.utils import absolute_uri

from products.wizard.backend.facade import api as wizard_facade
from products.wizard.backend.facade.contracts import StartWizardInstallInput
from products.wizard.backend.facade.errors import WizardRunNotFoundError
from products.wizard.backend.presentation.installs.errors import (
    WIZARD_INSTALL_START_ERRORS,
    WizardInstallStartError,
    install_start_api_error,
)
from products.wizard.backend.presentation.installs.serializers import (
    WizardInstallStartRequestSerializer,
    WizardInstallStartSerializer,
    WizardInstallStatusSerializer,
)
from products.wizard.backend.presentation.permissions import WizardInstallAuthenticationRequired
from products.wizard.backend.presentation.runs.serializers import WizardRunErrorSerializer
from products.wizard.backend.presentation.security import refuse_blocked_gateway_identity
from products.wizard.backend.presentation.throttles import WizardRunCreateThrottle, WizardRunReadThrottle


class WizardInstallViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """
    Start a cloud setup run on a GitHub repository of the project and check on it.

    Agents connected through MCP call these endpoints with an OAuth access token.
    """

    permission_classes = [WizardInstallAuthenticationRequired]
    scope_object = "task"
    scope_object_read_actions = ["retrieve"]
    scope_object_write_actions = ["create"]
    http_method_names = ["get", "post", "head", "options"]
    lookup_field = "run_id"
    lookup_value_regex = "[0-9a-fA-F-]{36}"
    pagination_class = None

    def get_throttles(self) -> list:
        if self.action == "create":
            return [WizardRunCreateThrottle()]
        return [WizardRunReadThrottle()]

    @validated_request(
        request_serializer=WizardInstallStartRequestSerializer,
        responses={
            200: OpenApiResponse(
                response=WizardInstallStartSerializer, description="A retry returned the run it already started."
            ),
            201: OpenApiResponse(response=WizardInstallStartSerializer, description="The setup run started."),
            400: OpenApiResponse(response=WizardRunErrorSerializer),
            403: OpenApiResponse(response=WizardRunErrorSerializer),
            404: OpenApiResponse(response=WizardRunErrorSerializer),
            409: OpenApiResponse(response=WizardRunErrorSerializer),
            429: OpenApiResponse(response=WizardRunErrorSerializer),
        },
        summary="Start a setup run",
        description=(
            "Start the setup agent in the cloud on a GitHub repository of this project. "
            "It adds PostHog to the code and opens a pull request. "
            "Each user can have one setup run active per project at a time."
        ),
    )
    # POST /projects/:projectId/wizard/installs
    def create(self, request: ValidatedRequest, *args: object, **kwargs: object) -> Response:
        user = cast(User, request.user)
        self._require_cloud_execution()
        refuse_blocked_gateway_identity(request, self.team.organization_id, call_site="wizard_install")

        try:
            result = wizard_facade.start_install(
                StartWizardInstallInput(
                    team_id=self.team_id,
                    created_by_id=user.id,
                    repository=request.validated_data["repository"],
                    branch=request.validated_data.get("branch"),
                    idempotency_key=request.validated_data.get("idempotency_key"),
                )
            )
        except WIZARD_INSTALL_START_ERRORS as error:
            raise install_start_api_error(cast(WizardInstallStartError, error))

        data = WizardInstallStartSerializer(
            {
                "run_id": result.run.id,
                "status": result.run.status,
                "url": absolute_uri(f"/project/{self.team_id}/wizard/runs"),
            }
        ).data
        return Response(data, status=status.HTTP_201_CREATED if result.created else status.HTTP_200_OK)

    @extend_schema(
        responses={
            200: WizardInstallStatusSerializer,
            404: OpenApiResponse(response=WizardRunErrorSerializer),
        },
        summary="Get a setup run's status",
        description=(
            "Get the status of a cloud setup run, its task list, the pull request link once it exists, "
            "and a next step to relay to the user."
        ),
    )
    # GET /projects/:projectId/wizard/installs/:runId
    def retrieve(self, request: Request, *args: object, **kwargs: object) -> Response:
        self._require_cloud_execution()
        try:
            install_status = wizard_facade.get_install_status(self.team_id, UUID(cast(str, self.kwargs["run_id"])))
        except (ValueError, WizardRunNotFoundError):
            raise NotFound("No setup run was found for this project.")
        return Response(WizardInstallStatusSerializer(install_status).data)

    @staticmethod
    def _require_cloud_execution() -> None:
        if not settings.WIZARD_CLOUD_RUN_OAUTH_CLIENT_ID:
            raise NotFound("Cloud setup runs aren't available for this project.")
