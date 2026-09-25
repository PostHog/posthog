from typing import cast
from uuid import UUID

from django.conf import settings
from django.http import HttpResponse
from django.http.response import HttpResponseBase

from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.streaming import sse_streaming_response
from posthog.api.utils import action
from posthog.auth import OAuthAccessTokenAuthentication, SessionAuthentication
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
    UpdateWizardRunTaskListSerializer,
    WizardRunCreateRequestSerializer,
    WizardRunErrorSerializer,
    WizardRunSerializer,
    WizardRunStatusUpdateRequestSerializer,
    WizardRunTaskListSerializer,
)
from products.wizard.backend.presentation.runs.stream import wizard_run_event_stream
from products.wizard.backend.presentation.sessions.views import EventStreamRenderer, _wizard_sync_killswitch_enabled
from products.wizard.backend.presentation.throttles import WizardRunCreateThrottle, WizardRunReadThrottle


class WizardRunViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """
    API endpoints for managing Wizard runs. For browser–based access.
    """

    permission_classes = [WizardRunSessionAuthenticationRequired]
    scope_object = "wizard_session"
    scope_object_read_actions = ["list", "retrieve", "stream"]
    scope_object_write_actions = ["create", "partial_update"]
    http_method_names = ["get", "post", "patch", "head", "options"]
    lookup_field = "run_id"
    lookup_value_regex = "[0-9a-fA-F-]{36}"
    pagination_class = WizardRunPagination

    def dangerously_get_required_scopes(self, request: Request, view: object) -> list[str] | None:
        if self.action in ("create", "partial_update") and isinstance(
            request.successful_authenticator, OAuthAccessTokenAuthentication
        ):
            return ["wizard_run:write"]
        return None

    def get_throttles(self) -> list:
        if self.action == "create":
            return [WizardRunCreateThrottle()]
        return [WizardRunReadThrottle()]

    @extend_schema(
        responses={200: WizardRunSerializer(many=True)},
        parameters=[
            OpenApiParameter(
                name="status",
                type=str,
                enum=[status.value for status in WizardRunStatus],
                many=True,
                style="form",
                explode=False,
                description="Filter by one or more comma-separated run statuses.",
            )
        ],
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

        # TODO: if creating a local run, only allow the Wizard's client ID.
        # Users should not be allowed to create local runs.

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
        description="Stream the current run state and subsequent updates. Use EventSource to consume this endpoint.",
        responses={(200, "text/event-stream"): {"type": "string"}, 204: None},
    )
    @action(detail=True, methods=["get"], pagination_class=None, renderer_classes=[EventStreamRenderer])
    def stream(self, request: Request, *args: object, **kwargs: object) -> HttpResponseBase:
        if _wizard_sync_killswitch_enabled(str(getattr(request.user, "distinct_id", self.team_id))):
            return HttpResponse(status=204)
        run = self._get_run()
        if getattr(settings, "SERVER_GATEWAY_INTERFACE", "ASGI") != "ASGI":
            raise RuntimeError("wizard_runs.stream requires ASGI.")
        return sse_streaming_response(wizard_run_event_stream(self.team_id, run.id), endpoint="wizard_run")

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


class WizardRunTasksViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """
    API endpoints for managing Wizard run tasks. Access is scoped to the Wizard only.

    The Wizard should be the only client that can update the tasks of a run.
    """

    scope_object = "wizard_run"
    scope_object_read_actions = ["get_tasks"]
    scope_object_write_actions = ["tasks"]
    http_method_names = ["get", "put", "head", "options"]
    pagination_class = None
    lookup_field = "run_id"
    lookup_value_regex = "[0-9a-fA-F-]{36}"

    def get_throttles(self) -> list:
        return [WizardRunReadThrottle()]

    # PUT /projects/:projectId/wizard/runs/:runId/tasks
    @extend_schema(request=UpdateWizardRunTaskListSerializer, responses={204: None})
    @action(detail=True, methods=["put"], url_path="tasks")
    def tasks(self, request: Request, *args: object, **kwargs: object) -> Response:
        if not isinstance(request.successful_authenticator, OAuthAccessTokenAuthentication):
            raise PermissionDenied("Use the setup agent's OAuth credentials to update run tasks.")
        run = self._get_run()
        if run.created_by_id != request.user.id:
            raise PermissionDenied("Only the user who started this Wizard run can update it.")

        serializer = UpdateWizardRunTaskListSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        wizard_facade.update_run_task_list(self.team_id, run.id, serializer.to_contract())
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(responses={200: WizardRunTaskListSerializer})
    @tasks.mapping.get
    def get_tasks(self, request: Request, *args: object, **kwargs: object) -> Response:
        return Response(WizardRunTaskListSerializer(self._get_run()).data)

    def _get_run(self) -> WizardRunDTO:
        try:
            return wizard_facade.get_run(self.team_id, UUID(cast(str, self.kwargs["run_id"])))
        except WizardRunNotFoundError:
            raise NotFound("No Wizard run was found for this project.")
