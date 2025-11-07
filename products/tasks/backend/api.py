import logging
import traceback
from typing import cast

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from posthog.api.mixins import validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication
from posthog.permissions import APIScopePermission, PostHogFeatureFlagPermission

from .models import Task, TaskRun
from .serializers import (
    ErrorResponseSerializer,
    TaskRunAppendLogRequestSerializer,
    TaskRunDetailSerializer,
    TaskSerializer,
    TaskUpdatePositionRequestSerializer,
)
from .temporal.client import execute_task_processing_workflow

logger = logging.getLogger(__name__)


@extend_schema(tags=["tasks"])
class TaskViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """
    API for managing tasks within a project. Tasks represent units of work to be performed by an agent.
    """

    serializer_class = TaskSerializer
    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission, PostHogFeatureFlagPermission]
    scope_object = "task"
    queryset = Task.objects.all()
    posthog_feature_flag = {
        "tasks": [
            "list",
            "retrieve",
            "create",
            "update",
            "partial_update",
            "destroy",
            "update_position",
            "progress",
            "progress_stream",
            "run",
        ]
    }

    def safely_get_queryset(self, queryset):
        qs = queryset.filter(team=self.team).order_by("position")

        params = self.request.query_params if hasattr(self, "request") else {}

        # Filter by origin product
        origin_product = params.get("origin_product")
        if origin_product:
            qs = qs.filter(origin_product=origin_product)

        stage = params.get("stage")
        if stage:
            qs = qs.filter(runs__stage=stage)

        # Filter by repository or organization inside repository_config JSON
        organization = params.get("organization")
        repository = params.get("repository")

        if repository:
            repo_str = repository.strip()
            if "/" in repo_str:
                org_part, repo_part = repo_str.split("/", 1)
                org_part = org_part.strip()
                repo_part = repo_part.strip()
                if org_part and repo_part:
                    qs = qs.filter(
                        repository_config__organization__iexact=org_part,
                        repository_config__repository__iexact=repo_part,
                    )
                elif repo_part:
                    qs = qs.filter(repository_config__repository__iexact=repo_part)
                elif org_part:
                    qs = qs.filter(repository_config__organization__iexact=org_part)
            else:
                qs = qs.filter(repository_config__repository__iexact=repo_str)

        if organization:
            qs = qs.filter(repository_config__organization__iexact=organization.strip())

        # Prefetch runs to avoid N+1 queries when fetching latest_run
        qs = qs.prefetch_related("runs")

        return qs

    def get_serializer_context(self):
        return {**super().get_serializer_context(), "team": self.team}

    def perform_create(self, serializer):
        logger.info(f"Creating task with data: {serializer.validated_data}")
        serializer.save(team=self.team)

    def _trigger_workflow(self, task: Task) -> None:
        try:
            logger.info(f"Attempting to trigger task processing workflow for task {task.id}")
            execute_task_processing_workflow(
                task_id=str(task.id),
                team_id=task.team.id,
                user_id=getattr(self.request.user, "id", None),
            )
            logger.info(f"Workflow trigger completed for task {task.id}")
        except Exception as e:
            logger.exception(f"Failed to trigger task processing workflow for task {task.id}: {e}")

            logger.exception(f"Workflow error traceback: {traceback.format_exc()}")

    def perform_update(self, serializer):
        task = cast(Task, serializer.instance)
        logger.info(f"perform_update called for task {task.id} with validated_data: {serializer.validated_data}")
        serializer.save()
        logger.info(f"Task {task.id} updated successfully")

    @validated_request(
        request_serializer=TaskUpdatePositionRequestSerializer,
        responses={
            200: OpenApiResponse(response=TaskSerializer, description="Task with updated position"),
            400: OpenApiResponse(response=ErrorResponseSerializer, description="Invalid position"),
            404: OpenApiResponse(description="Task not found"),
        },
        summary="Update task position",
        description="Update the position of a task within its current stage",
        strict_request_validation=True,
    )
    @action(detail=True, methods=["patch"], required_scopes=["task:write"])
    def update_position(self, request, pk=None, **kwargs):
        task = self.get_object()

        new_position = request.validated_data.get("position")

        if new_position is None:
            return Response(
                ErrorResponseSerializer({"error": "Position is required"}).data, status=status.HTTP_400_BAD_REQUEST
            )

        task.position = new_position
        task.save()

        return Response(TaskSerializer(task).data)

    @validated_request(
        request_serializer=None,
        responses={
            200: OpenApiResponse(response=TaskSerializer, description="Workflow started for task"),
            404: OpenApiResponse(description="Task not found"),
        },
        summary="Run task",
        description="Kick off the workflow for the task in its current stage.",
    )
    @action(detail=True, methods=["post"], url_path="run", required_scopes=["task:write"])
    def run(self, request, pk=None, **kwargs):
        task = cast(Task, self.get_object())

        logger.info(f"Triggering workflow for task {task.id}")

        self._trigger_workflow(task)

        return Response(TaskSerializer(task, context=self.get_serializer_context()).data)


@extend_schema(tags=["task-runs"])
class TaskRunViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """
    API for managing task runs. Each run represents an execution of a task.
    """

    serializer_class = TaskRunDetailSerializer
    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission, PostHogFeatureFlagPermission]
    scope_object = "task"
    queryset = TaskRun.objects.select_related("task").all()
    posthog_feature_flag = {
        "tasks": [
            "list",
            "retrieve",
            "create",
            "update",
            "partial_update",
            "progress_run",
            "set_output",
            "append_log",
        ]
    }
    http_method_names = ["get", "post", "patch", "head", "options"]
    filter_rewrite_rules = {"team_id": "team_id"}

    def safely_get_queryset(self, queryset):
        # Task runs are always scoped to a specific task
        task_id = self.kwargs.get("parent_lookup_task_id")
        if not task_id:
            raise NotFound("Task ID is required")

        # Verify task belongs to team
        if not Task.objects.filter(id=task_id, team=self.team).exists():
            raise NotFound("Task not found")

        return queryset.filter(team=self.team, task_id=task_id)

    def get_serializer_context(self):
        return {**super().get_serializer_context(), "team": self.team}

    def perform_create(self, serializer):
        task_id = self.kwargs.get("parent_lookup_task_id")
        if not task_id:
            raise NotFound("Task ID is required")
        task = Task.objects.get(id=task_id, team=self.team)
        serializer.save(team=self.team, task=task)

    @validated_request(
        request_serializer=None,
        responses={
            200: OpenApiResponse(response=TaskRunDetailSerializer, description="Run with updated output"),
            404: OpenApiResponse(description="Run not found"),
        },
        summary="Set run output",
        description="Update the output field for a task run (e.g., PR URL, commit SHA, etc.)",
    )
    @action(detail=True, methods=["patch"], url_path="set_output", required_scopes=["task:write"])
    def set_output(self, request, pk=None, **kwargs):
        task_run = cast(TaskRun, self.get_object())

        output_data = request.data.get("output", {})
        if not isinstance(output_data, dict):
            return Response(
                ErrorResponseSerializer({"error": "output must be a dictionary"}).data,
                status=status.HTTP_400_BAD_REQUEST,
            )

        # TODO: Validate output data according to schema for the task type.
        task_run.output = output_data
        task_run.save(update_fields=["output", "updated_at"])

        return Response(TaskRunDetailSerializer(task_run, context=self.get_serializer_context()).data)

    @validated_request(
        request_serializer=TaskRunAppendLogRequestSerializer,
        responses={
            200: OpenApiResponse(response=TaskRunDetailSerializer, description="Run with updated log"),
            400: OpenApiResponse(response=ErrorResponseSerializer, description="Invalid log entries"),
            404: OpenApiResponse(description="Run not found"),
        },
        summary="Append log entries",
        description="Append one or more log entries to the task run log array",
        strict_request_validation=True,
    )
    @action(detail=True, methods=["post"], url_path="append_log", required_scopes=["task:write"])
    def append_log(self, request, pk=None, **kwargs):
        task_run = cast(TaskRun, self.get_object())

        entries = request.validated_data["entries"]
        task_run.append_log(entries)

        return Response(TaskRunDetailSerializer(task_run, context=self.get_serializer_context()).data)
