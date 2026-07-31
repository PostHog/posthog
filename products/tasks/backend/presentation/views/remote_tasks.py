from typing import Any

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import APIException, NotFound, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication, SessionAuthentication
from posthog.models.integration import Integration
from posthog.permissions import APIScopePermission

from products.tasks.backend.logic.connect import (
    PosthogConnectError,
    PosthogConnectIntegrationError,
    dispatch_remote_task,
    get_remote_task,
)


class RemoteTaskDispatchSerializer(serializers.Serializer):
    integration_id = serializers.IntegerField(
        help_text="Id of a `posthog` connection in this project, identifying the target cell to dispatch into."
    )
    target_team_id = serializers.IntegerField(
        help_text="Team id in the target region to create the task under. The connected user must have task access there."
    )
    description = serializers.CharField(
        help_text="The prompt/work description passed to the remote agent.",
    )
    title = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Optional short title; auto-generated from the description when omitted.",
    )
    repository = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text="Optional target GitHub repository in `organization/repo` format.",
    )


class RemoteTaskHandleSerializer(serializers.Serializer):
    region = serializers.CharField(help_text="Target region the task was dispatched to (e.g. EU).")
    target_team_id = serializers.IntegerField(help_text="Team id the task was created under in the target region.")
    task_id = serializers.CharField(help_text="Id of the created task in the target region; use it to poll status.")
    task_number = serializers.IntegerField(allow_null=True, required=False, help_text="Human-facing task number.")
    title = serializers.CharField(allow_null=True, required=False, help_text="Resolved task title.")
    status = serializers.CharField(
        allow_null=True, required=False, help_text="Latest run status, if a run has started."
    )


class RemoteTaskStatusQuerySerializer(serializers.Serializer):
    integration_id = serializers.IntegerField(help_text="Id of the `posthog` connection used to dispatch.")
    target_team_id = serializers.IntegerField(help_text="Team id in the target region the task belongs to.")
    # UUIDField (not CharField): the value is interpolated into the remote URL path, so it must be a
    # canonical UUID and cannot smuggle `../` segments to reach other endpoints on the target cell.
    task_id = serializers.UUIDField(help_text="Id of the remote task to poll.")


class RemoteTaskStatusSerializer(serializers.Serializer):
    region = serializers.CharField(help_text="Target region the task is running in.")
    target_team_id = serializers.IntegerField(help_text="Team id the task belongs to in the target region.")
    task_id = serializers.CharField(help_text="Id of the remote task.")
    status = serializers.CharField(
        allow_null=True, help_text="Latest run status (e.g. queued, in_progress, completed, failed)."
    )
    report = serializers.CharField(
        allow_null=True,
        help_text="The task's latest output, bounded and scrubbed for remote return. Null until a run produces output.",
    )
    error_message = serializers.CharField(
        allow_null=True, required=False, help_text="Error from the latest run, if it failed."
    )


class RemoteTaskViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    """Dispatch and poll Tasks that run in another PostHog region, via a `posthog` connection.

    Used when work must execute region-resident — e.g. querying a direct-connect source only reachable
    from the target cell. Only the create request and the bounded, scrubbed report cross the boundary.
    """

    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission]
    scope_object = "task"
    serializer_class = RemoteTaskHandleSerializer

    def _get_integration(self, integration_id: int) -> Integration:
        try:
            return Integration.objects.get(team_id=self.team_id, id=integration_id, kind="posthog")
        except Integration.DoesNotExist:
            raise NotFound("No PostHog connection with that id in this project.")

    @extend_schema(
        request=RemoteTaskDispatchSerializer,
        responses={
            201: OpenApiResponse(
                response=RemoteTaskHandleSerializer, description="Handle for the dispatched remote task."
            )
        },
        summary="Dispatch a task to another region",
        description="Create a Task in the target region identified by a `posthog` connection, and return a handle to poll it.",
    )
    def create(self, request: Request, **kwargs: Any) -> Response:
        serializer = RemoteTaskDispatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        integration = self._get_integration(data["integration_id"])
        try:
            handle = dispatch_remote_task(
                integration,
                target_team_id=data["target_team_id"],
                description=data["description"],
                title=data.get("title") or None,
                repository=data.get("repository") or None,
            )
        except PosthogConnectIntegrationError as err:
            raise ValidationError(str(err))
        except PosthogConnectError as err:
            raise _remote_unavailable(err)
        return Response(RemoteTaskHandleSerializer(handle).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        parameters=[RemoteTaskStatusQuerySerializer],
        responses={200: OpenApiResponse(response=RemoteTaskStatusSerializer, description="Current status and report.")},
        summary="Poll a remote task",
        description="Fetch the status and bounded, scrubbed report of a task previously dispatched to another region.",
    )
    @action(detail=False, methods=["get"], url_path="status", required_scopes=["task:read"])
    def task_status(self, request: Request, **kwargs: Any) -> Response:
        query = RemoteTaskStatusQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        data = query.validated_data
        integration = self._get_integration(data["integration_id"])
        try:
            result = get_remote_task(integration, target_team_id=data["target_team_id"], task_id=str(data["task_id"]))
        except PosthogConnectIntegrationError as err:
            raise ValidationError(str(err))
        except PosthogConnectError as err:
            raise _remote_unavailable(err)
        return Response(RemoteTaskStatusSerializer(result).data)


class _RemoteRegionUnavailable(APIException):
    status_code = status.HTTP_502_BAD_GATEWAY
    default_detail = "The target region could not be reached."
    default_code = "remote_region_unavailable"


def _remote_unavailable(err: PosthogConnectError) -> _RemoteRegionUnavailable:
    return _RemoteRegionUnavailable(str(err))
