from typing import cast
from uuid import UUID

from django.conf import settings

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import SessionAuthentication
from posthog.exceptions import Conflict

from products.wizard.backend.facade import api as wizard_facade
from products.wizard.backend.facade.contracts import WizardRunDTO
from products.wizard.backend.facade.enums import WizardRunEnvironment, WizardRunStatus
from products.wizard.backend.facade.errors import IllegalStatusTransitionError, WizardRunNotFoundError
from products.wizard.backend.presentation.permissions import WizardRunSessionAuthenticationRequired
from products.wizard.backend.presentation.runs.errors import (
    WIZARD_RUN_CREATION_ERRORS,
    WizardRunCreationError,
    run_creation_api_error,
)
from products.wizard.backend.presentation.runs.pagination import WizardRunPagination
from products.wizard.backend.presentation.runs.serializers import (
    WizardRunCreateRequestSerializer,
    WizardRunErrorSerializer,
    WizardRunSerializer,
    WizardRunStatusUpdateRequestSerializer,
)
from products.wizard.backend.presentation.throttles import WizardRunCreateThrottle, WizardRunReadThrottle


class WizardRunViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    permission_classes = [WizardRunSessionAuthenticationRequired]
    scope_object = "wizard_session"
    scope_object_read_actions = ["list", "retrieve"]
    scope_object_write_actions = ["create", "partial_update"]
    http_method_names = ["get", "post", "patch", "head", "options"]
    lookup_field = "run_id"
    lookup_value_regex = "[0-9a-fA-F-]{36}"
    pagination_class = WizardRunPagination

    def get_throttles(self) -> list:
        if self.action == "create":
            return [WizardRunCreateThrottle()]
        return [WizardRunReadThrottle()]

    @extend_schema(
        responses={200: WizardRunSerializer(many=True)},
        description="List Wizard runs for this project, ordered from newest to oldest.",
    )
    def list(self, request: Request, *args: object, **kwargs: object) -> Response:
        # GET /projects/:projectId/wizard/runs
        paginator = cast(WizardRunPagination, self.paginator)
        return paginator.paginate_runs(request, team_id=self.team_id)

    @extend_schema(
        request=WizardRunCreateRequestSerializer,
        responses={
            201: WizardRunSerializer,
            400: OpenApiResponse(response=WizardRunErrorSerializer),
            403: OpenApiResponse(response=WizardRunErrorSerializer),
            404: OpenApiResponse(response=WizardRunErrorSerializer),
            429: OpenApiResponse(response=WizardRunErrorSerializer),
        },
        description="Create a local or cloud Wizard run for a project workspace.",
    )
    def create(self, request: Request, *args: object, **kwargs: object) -> Response:
        # POST /projects/:projectId/wizard/runs
        serializer = WizardRunCreateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        params = serializer.to_contract(team_id=self.team_id, created_by_id=cast(int, request.user.id))
        if params.environment == WizardRunEnvironment.CLOUD:
            self._validate_cloud_creation(request)
        try:
            result = wizard_facade.create_run_with_result(params)
        except WIZARD_RUN_CREATION_ERRORS as error:
            raise run_creation_api_error(cast(WizardRunCreationError, error))

        response_status = status.HTTP_201_CREATED if result.created else status.HTTP_200_OK

        return Response(WizardRunSerializer(result.run).data, status=response_status)

    @staticmethod
    def _validate_cloud_creation(request: Request) -> None:
        if not settings.WIZARD_CLOUD_RUN_OAUTH_CLIENT_ID:
            raise NotFound("Running the Wizard in the cloud is not available.")
        if not isinstance(request.successful_authenticator, SessionAuthentication):
            raise PermissionDenied("Sign in to start a cloud Wizard run.")

    @extend_schema(
        responses={
            200: WizardRunSerializer,
            404: OpenApiResponse(response=WizardRunErrorSerializer),
        },
        description="Retrieve a Wizard run in this project.",
    )
    # GET /projects/:projectId/wizard/runs/:runId
    def retrieve(self, request: Request, *args: object, **kwargs: object) -> Response:
        run = self._get_run()
        return Response(WizardRunSerializer(run).data)

    @extend_schema(
        request=WizardRunStatusUpdateRequestSerializer,
        responses={
            200: WizardRunSerializer,
            400: OpenApiResponse(response=WizardRunErrorSerializer),
            403: OpenApiResponse(response=WizardRunErrorSerializer),
            404: OpenApiResponse(response=WizardRunErrorSerializer),
            409: OpenApiResponse(response=WizardRunErrorSerializer),
        },
        description="Change the terminal status of a local Wizard run.",
    )
    # PATCH /projects/:projectId/wizard/runs/:runId
    def partial_update(self, request: Request, *args: object, **kwargs: object) -> Response:
        serializer = WizardRunStatusUpdateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        next_status = serializer.to_status()

        try:
            current = self._get_owned_run()

            if current.environment == WizardRunEnvironment.CLOUD:
                if next_status != WizardRunStatus.CANCELLED:
                    raise Conflict(
                        "Only cancellation can be requested for a cloud Wizard run.", code="cloud_run_managed"
                    )

                run = wizard_facade.cancel_run(self.team_id, current.id)

            elif next_status == WizardRunStatus.CANCELLED:
                run = wizard_facade.cancel_run(self.team_id, current.id)

            else:
                # todo: once we have the state sync system, all transitions should be handled by it
                run = wizard_facade.update_run_status(
                    self.team_id,
                    current.id,
                    next_status,
                    error_code=serializer.to_error_code(),
                )

        except IllegalStatusTransitionError:
            raise Conflict(
                f"This Wizard run cannot be {next_status.value} from its current status.",
                code="invalid_transition",
            )

        return Response(WizardRunSerializer(run).data)

    def _get_run(self) -> WizardRunDTO:
        try:
            return wizard_facade.get_run(self.team_id, self._run_id())
        except WizardRunNotFoundError:
            raise NotFound("No Wizard run was found for this project.")

    def _run_id(self) -> UUID:
        return UUID(cast(str, self.kwargs["run_id"]))

    def _get_owned_run(self) -> WizardRunDTO:
        run = self._get_run()

        if run.created_by_id != self.request.user.id:
            raise PermissionDenied("Only the user who started this Wizard run can update it.")

        return run
