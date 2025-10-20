import logging
import traceback
from typing import cast

from django.db import transaction
from django.db.models import OuterRef, Subquery

from drf_spectacular.utils import OpenApiExample, OpenApiResponse, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import PersonalAPIKeyAuthentication
from posthog.permissions import APIScopePermission, PostHogFeatureFlagPermission

from .agents import get_agent_dict_by_id, get_all_agents
from .models import Task, TaskRun, TaskWorkflow, WorkflowStage
from .serializers import (
    AgentDefinitionSerializer,
    AgentListResponseSerializer,
    ErrorResponseSerializer,
    TaskRunAppendLogRequestSerializer,
    TaskRunDetailSerializer,
    TaskRunProgressRequestSerializer,
    TaskSerializer,
    TaskUpdatePositionRequestSerializer,
    TaskUpdateStageRequestSerializer,
    TaskWorkflowSerializer,
    WorkflowDeactivateResponseSerializer,
    WorkflowStageArchiveResponseSerializer,
    WorkflowStageSerializer,
)
from .temporal.client import execute_task_processing_workflow

logger = logging.getLogger(__name__)


@extend_schema(tags=["tasks"])
class TaskViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """
    API for managing tasks within a project. Tasks represent units of work that can be tracked through workflow stages.
    """

    serializer_class = TaskSerializer
    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication]
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

        # Filter by workflow id
        workflow_id = params.get("workflow")
        if workflow_id:
            qs = qs.filter(workflow_id=workflow_id)

        stage_id = params.get("current_stage")
        if stage_id:
            latest_run = TaskRun.objects.filter(task=OuterRef("pk")).order_by("-created_at").values("current_stage")[:1]
            qs = qs.annotate(latest_stage=Subquery(latest_run)).filter(latest_stage=stage_id)

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
            logger.info(f"Attempting to trigger workflow for task {task.id}")
            execute_task_processing_workflow(
                task_id=str(task.id),
                team_id=task.team.id,
                user_id=getattr(self.request.user, "id", None),
            )
            logger.info(f"Workflow trigger completed for task {task.id}")
        except Exception as e:
            logger.exception(f"Failed to trigger workflow for task {task.id}: {e}")

            logger.exception(f"Workflow error traceback: {traceback.format_exc()}")

    def perform_update(self, serializer):
        task = cast(Task, serializer.instance)
        logger.info(f"perform_update called for task {task.id} with validated_data: {serializer.validated_data}")
        serializer.save()
        logger.info(f"Task {task.id} updated successfully")

    @extend_schema(
        summary="Update task position",
        description="Update the position of a task within its current stage",
        request=TaskUpdatePositionRequestSerializer,
        responses={
            200: OpenApiResponse(response=TaskSerializer, description="Task with updated position"),
            400: OpenApiResponse(response=ErrorResponseSerializer, description="Invalid position"),
            404: OpenApiResponse(description="Task not found"),
        },
    )
    @action(detail=True, methods=["patch"], required_scopes=["task:write"])
    def update_position(self, request, pk=None, **kwargs):
        task = self.get_object()

        new_position = request.data.get("position")

        if new_position is None:
            return Response(
                ErrorResponseSerializer({"error": "Position is required"}).data, status=status.HTTP_400_BAD_REQUEST
            )

        task.position = new_position
        task.save()

        return Response(TaskSerializer(task).data)

    @extend_schema(
        summary="Run task",
        description="Kick off the workflow for the task in its current stage.",
        request=None,
        responses={
            200: OpenApiResponse(response=TaskSerializer, description="Workflow started for task"),
            400: OpenApiResponse(response=ErrorResponseSerializer, description="Task has no workflow configured"),
            404: OpenApiResponse(description="Task not found"),
        },
    )
    @action(detail=True, methods=["post"], url_path="run", required_scopes=["task:write"])
    def run(self, request, pk=None, **kwargs):
        task = cast(Task, self.get_object())

        if not task.effective_workflow:
            return Response(
                ErrorResponseSerializer({"error": "Task has no workflow configured"}).data,
                status=status.HTTP_400_BAD_REQUEST,
            )

        logger.info(f"Triggering workflow for task {task.id}")

        self._trigger_workflow(task)

        return Response(TaskSerializer(task, context=self.get_serializer_context()).data)


@extend_schema(tags=["workflows"])
class TaskWorkflowViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """
    API for managing task workflows. Workflows define the stages and automation rules that tasks move through.
    """

    serializer_class = TaskWorkflowSerializer
    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission, PostHogFeatureFlagPermission]
    scope_object = "task"
    queryset = TaskWorkflow.objects.all()
    posthog_feature_flag = {
        "tasks": [
            "list",
            "retrieve",
            "create",
            "update",
            "partial_update",
            "destroy",
            "set_default",
            "deactivate",
            "create_default",
        ]
    }

    def safely_get_queryset(self, queryset):
        return queryset.filter(team=self.team, is_active=True)

    def get_serializer_context(self):
        return {**super().get_serializer_context(), "team": self.team}

    @extend_schema(
        summary="Set default workflow",
        description="Set this workflow as the team's default workflow. All new tasks will use this workflow unless specified otherwise.",
        request=None,
        responses={
            200: OpenApiResponse(response=TaskWorkflowSerializer, description="Updated workflow"),
            404: OpenApiResponse(description="Workflow not found"),
        },
    )
    @action(detail=True, methods=["post"], required_scopes=["task:write"])
    def set_default(self, request, pk=None, **kwargs):
        workflow = self.get_object()

        with transaction.atomic():
            # Unset current default
            TaskWorkflow.objects.filter(team=self.team, is_default=True).update(is_default=False)

            # Set new default
            workflow.is_default = True
            workflow.save(update_fields=["is_default"])

        return Response(TaskWorkflowSerializer(workflow, context=self.get_serializer_context()).data)

    @extend_schema(
        summary="Deactivate workflow",
        description="Deactivate a workflow and move its tasks to the team's default workflow. Cannot deactivate the default workflow.",
        request=None,
        responses={
            200: OpenApiResponse(
                response=WorkflowDeactivateResponseSerializer, description="Workflow deactivated successfully"
            ),
            400: OpenApiResponse(response=ErrorResponseSerializer, description="Cannot deactivate default workflow"),
            404: OpenApiResponse(description="Workflow not found"),
        },
    )
    @action(detail=True, methods=["post"], required_scopes=["task:write"])
    def deactivate(self, request, pk=None, **kwargs):
        workflow = cast(TaskWorkflow, self.get_object())

        try:
            workflow.deactivate_safely()
            return Response(WorkflowDeactivateResponseSerializer({"message": "Workflow deactivated successfully"}).data)
        except ValueError:
            return Response(
                ErrorResponseSerializer({"error": "Cannot deactivate the default workflow"}).data,
                status=status.HTTP_400_BAD_REQUEST,
            )

    @extend_schema(
        summary="Create default workflow",
        description="Create a default workflow for the team if none exists. This creates a standard workflow with common stages.",
        request=None,
        responses={
            200: OpenApiResponse(response=TaskWorkflowSerializer, description="Created default workflow"),
            400: OpenApiResponse(response=ErrorResponseSerializer, description="Team already has a default workflow"),
        },
    )
    @action(detail=False, methods=["post"], required_scopes=["task:write"])
    def create_default(self, request, **kwargs):
        existing_default = TaskWorkflow.objects.filter(team=self.team, is_default=True).first()

        if existing_default:
            return Response(
                ErrorResponseSerializer({"error": "Team already has a default workflow"}).data,
                status=status.HTTP_400_BAD_REQUEST,
            )

        workflow = TaskWorkflow.create_default_workflow(self.team)

        return Response(TaskWorkflowSerializer(workflow, context=self.get_serializer_context()).data)


@extend_schema(tags=["workflow-stages"])
class WorkflowStageViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """
    API for managing workflow stages. Stages represent the different states a task can be in within a workflow.
    """

    serializer_class = WorkflowStageSerializer
    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission, PostHogFeatureFlagPermission]
    scope_object = "task"
    queryset = WorkflowStage.objects.all()
    posthog_feature_flag = {"tasks": ["list", "retrieve", "create", "update", "partial_update", "destroy", "archive"]}
    filter_rewrite_rules = {"team_id": "workflow__team_id"}

    def safely_get_queryset(self, queryset):
        return queryset.filter(is_archived=False)

    def perform_create(self, serializer):
        workflow_id = self.kwargs.get("parent_lookup_workflow_id")

        if workflow_id:
            if not TaskWorkflow.objects.filter(id=workflow_id, team=self.team).exists():
                raise NotFound("Workflow not found")

        serializer.save()

    @extend_schema(
        summary="Archive workflow stage",
        description="Archive a workflow stage instead of deleting it. Archived stages are hidden from UI but preserve task associations.",
        request=None,
        responses={
            200: OpenApiResponse(
                response=WorkflowStageArchiveResponseSerializer, description="Stage archived successfully"
            ),
            404: OpenApiResponse(description="Stage not found"),
        },
    )
    @action(detail=True, methods=["post"], required_scopes=["task:write"])
    def archive(self, request, pk=None, **kwargs):
        stage = self.get_object()
        stage.archive()
        return Response(WorkflowStageArchiveResponseSerializer({"message": "Stage archived successfully"}).data)


@extend_schema(tags=["task-runs"])
class TaskRunViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """
    API for managing task runs. Each run represents an execution of a task through workflow stages.
    """

    serializer_class = TaskRunDetailSerializer
    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication]
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
            "update_stage",
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

    def perform_update(self, serializer):
        task_run = cast(TaskRun, serializer.instance)

        previous_stage = task_run.current_stage.key if task_run.current_stage else None
        logger.info(f"perform_update called for run {task_run.id} with validated_data: {serializer.validated_data}")

        serializer.save()

        new_stage = serializer.validated_data.get("current_stage")
        new_stage_key = new_stage.key if new_stage else None
        if new_stage_key != previous_stage:
            logger.info(f"Run {task_run.id} stage changed from {previous_stage} to {new_stage_key}")
        else:
            logger.info(f"Run {task_run.id} updated successfully")

    @extend_schema(
        summary="Update run stage",
        description="Move a task run to a different workflow stage.",
        request=TaskUpdateStageRequestSerializer,
        responses={
            200: OpenApiResponse(response=TaskRunDetailSerializer, description="Run with updated stage"),
            400: OpenApiResponse(response=ErrorResponseSerializer, description="Invalid stage or validation error"),
            404: OpenApiResponse(description="Run not found"),
        },
    )
    @action(detail=True, methods=["patch"], required_scopes=["task:write"])
    def update_stage(self, request, pk=None, **kwargs):
        logger.info(f"update_stage called for run {pk} with data: {request.data}")

        task_run = cast(TaskRun, self.get_object())
        new_stage_id = request.data.get("current_stage")

        if not new_stage_id:
            return Response(
                ErrorResponseSerializer({"error": "Stage is required"}).data, status=status.HTTP_400_BAD_REQUEST
            )

        try:
            new_stage = WorkflowStage.objects.get(id=new_stage_id)
        except WorkflowStage.DoesNotExist:
            logger.warning(f"Invalid stage '{new_stage_id}' for run {pk}")
            return Response(
                ErrorResponseSerializer({"error": "Invalid stage"}).data, status=status.HTTP_400_BAD_REQUEST
            )

        previous_stage = task_run.current_stage.key if task_run.current_stage else None
        task_run.current_stage = new_stage
        task_run.save(update_fields=["current_stage", "updated_at"])

        new_stage_key = task_run.current_stage.key if task_run.current_stage else None
        logger.info(f"Run {task_run.id} stage updated from {previous_stage} to {new_stage_key}")

        return Response(TaskRunDetailSerializer(task_run, context=self.get_serializer_context()).data)

    @extend_schema(
        summary="Progress run to next stage",
        description=(
            "Advance a task run to the next workflow stage, or to a specified stage. "
            "If 'next_stage_id' is provided, the run will move to that stage. "
            "Otherwise, the run will be moved to the next stage in its workflow."
        ),
        request=TaskRunProgressRequestSerializer,
        responses={
            200: OpenApiResponse(response=TaskRunDetailSerializer, description="Run progressed to next stage"),
            400: OpenApiResponse(
                response=ErrorResponseSerializer, description="No next stage available or invalid stage"
            ),
            404: OpenApiResponse(description="Run not found"),
        },
    )
    @action(detail=True, methods=["post"], required_scopes=["task:write"])
    def progress_run(self, request, pk=None, **kwargs):
        task_run = cast(TaskRun, self.get_object())

        payload = TaskRunProgressRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        provided_stage_id = payload.validated_data.get("next_stage_id")

        new_stage = None
        if provided_stage_id:
            try:
                candidate = WorkflowStage.objects.get(id=provided_stage_id)
            except WorkflowStage.DoesNotExist:
                return Response(
                    ErrorResponseSerializer({"error": "Invalid next_stage_id"}).data,
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if candidate.is_archived:
                return Response(
                    ErrorResponseSerializer({"error": "Stage is archived"}).data,
                    status=status.HTTP_400_BAD_REQUEST,
                )

            new_stage = candidate
        else:
            new_stage = task_run.get_next_stage()

        if not new_stage:
            return Response(
                ErrorResponseSerializer({"error": "No next stage available for this run"}).data,
                status=status.HTTP_400_BAD_REQUEST,
            )

        task_run.current_stage = new_stage
        task_run.save(update_fields=["current_stage", "updated_at"])

        return Response(TaskRunDetailSerializer(task_run, context=self.get_serializer_context()).data)

    @extend_schema(
        summary="Set run output",
        description="Update the output field for a task run (e.g., PR URL, commit SHA, etc.)",
        request=serializers.Serializer,
        responses={
            200: OpenApiResponse(response=TaskRunDetailSerializer, description="Run with updated output"),
            404: OpenApiResponse(description="Run not found"),
        },
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

    @extend_schema(
        summary="Append log entries",
        description="Append one or more log entries to the task run log array",
        request=TaskRunAppendLogRequestSerializer,
        responses={
            200: OpenApiResponse(response=TaskRunDetailSerializer, description="Run with updated log"),
            400: OpenApiResponse(response=ErrorResponseSerializer, description="Invalid log entries"),
            404: OpenApiResponse(description="Run not found"),
        },
    )
    @action(detail=True, methods=["post"], url_path="append_log", required_scopes=["task:write"])
    def append_log(self, request, pk=None, **kwargs):
        task_run = cast(TaskRun, self.get_object())

        serializer = TaskRunAppendLogRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        entries = serializer.validated_data["entries"]
        task_run.append_log(entries)

        return Response(TaskRunDetailSerializer(task_run, context=self.get_serializer_context()).data)


@extend_schema(tags=["agents"])
class AgentDefinitionViewSet(TeamAndOrgViewSetMixin, viewsets.ReadOnlyModelViewSet):
    """
    API for retrieving agent definitions. Agents are automation services that can be assigned to workflow stages to process tasks.
    """

    serializer_class = AgentDefinitionSerializer
    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication]
    queryset = None  # No model queryset since we're using hardcoded agents
    scope_object = "task"
    posthog_feature_flag = {"tasks": ["list", "retrieve"]}

    @extend_schema(
        summary="List agent definitions",
        description="Get a list of available agent definitions that can be assigned to workflow stages.",
        responses={
            200: OpenApiResponse(
                response=AgentListResponseSerializer,
                description="List of agent definitions",
                examples=[
                    OpenApiExample(
                        "Agent List Response",
                        description="Example response with available agents",
                        response_only=True,
                        value={
                            "results": [
                                {
                                    "id": "claude_code_agent",
                                    "name": "Claude Code Agent",
                                    "agent_type": "code_execution",
                                    "description": "Executes code changes and technical tasks using Claude Code",
                                    "config": {"timeout": 3600, "sandbox": True},
                                    "is_active": True,
                                }
                            ]
                        },
                    )
                ],
            )
        },
    )
    def list(self, request, *args, **kwargs):
        agents = get_all_agents()
        return Response(AgentListResponseSerializer({"results": agents}).data)

    @extend_schema(
        summary="Get agent definition",
        description="Retrieve a specific agent definition by ID.",
        responses={
            200: OpenApiResponse(response=AgentDefinitionSerializer, description="Agent definition"),
            404: OpenApiResponse(description="Agent not found"),
        },
    )
    def retrieve(self, request, pk=None, *args, **kwargs):
        agent = get_agent_dict_by_id(pk)
        if agent:
            return Response(AgentDefinitionSerializer(agent).data)

        raise NotFound(f"Unable to find agent definition")
