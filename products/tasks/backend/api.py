import logging
import traceback
from typing import cast

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import PersonalAPIKeyAuthentication
from posthog.permissions import APIScopePermission, PostHogFeatureFlagPermission

from .agents import get_agent_dict_by_id, get_all_agents
from .models import Task, TaskProgress, TaskWorkflow, WorkflowStage
from .serializers import (
    AgentDefinitionSerializer,
    AgentListResponseSerializer,
    ErrorResponseSerializer,
    TaskBulkReorderRequestSerializer,
    TaskBulkReorderResponseSerializer,
    TaskProgressResponseSerializer,
    TaskProgressStreamResponseSerializer,
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
            "update_stage",
            "update_position",
            "bulk_reorder",
            "progress",
            "progress_stream",
        ]
    }

    def safely_get_queryset(self, queryset):
        return queryset.filter(team=self.team).order_by("position")

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
        # Get the current task state before update
        task = cast(Task, serializer.instance)
        previous_status = task.current_stage.key if task.current_stage else "backlog"

        logger.info(f"perform_update called for task {task.id} with validated_data: {serializer.validated_data}")

        # Save the changes
        serializer.save()

        # Check if current_stage changed and trigger workflow
        new_stage = serializer.validated_data.get("current_stage")
        new_status = new_stage.key if new_stage else "backlog"
        if new_status != previous_status:
            logger.info(f"Task {task.id} status changed from {previous_status} to {new_status}")
            self._trigger_workflow(task)
        else:
            logger.info(f"Task {task.id} updated but status unchanged ({previous_status})")

    @extend_schema(
        summary="Update task stage",
        description="Move a task to a different workflow stage. This will trigger workflow automation.",
        request=TaskUpdateStageRequestSerializer,
        responses={
            200: OpenApiResponse(response=TaskSerializer, description="Task with updated stage"),
            400: OpenApiResponse(response=ErrorResponseSerializer, description="Invalid stage or validation error"),
            404: OpenApiResponse(description="Task not found"),
        },
        examples=[
            OpenApiExample(
                "Update Stage Request",
                description="Example request to move a task to in-progress stage",
                request_only=True,
                value={"current_stage": "789e0123-e89b-12d3-a456-426614174002"},
            )
        ],
    )
    @action(detail=True, methods=["patch"], required_scopes=["task:write"])
    def update_stage(self, request, pk=None, **kwargs):
        logger.info(f"update_stage called for task {pk} with data: {request.data}")

        task = cast(Task, self.get_object())
        new_stage_id = request.data.get("current_stage")

        logger.info(f"Task {task.id}: current_stage={task.current_stage}, new_stage={new_stage_id}")

        if not new_stage_id:
            return Response(
                ErrorResponseSerializer({"error": "Stage is required"}).data, status=status.HTTP_400_BAD_REQUEST
            )

        try:
            new_stage = WorkflowStage.objects.get(id=new_stage_id)
        except WorkflowStage.DoesNotExist:
            logger.warning(f"Invalid stage '{new_stage_id}' for task {pk}")
            return Response(
                ErrorResponseSerializer({"error": "Invalid stage"}).data, status=status.HTTP_400_BAD_REQUEST
            )

        previous_status = task.current_stage.key if task.current_stage else "backlog"

        task.current_stage = new_stage
        task.save()

        new_status = task.current_stage.key if task.current_stage else "backlog"

        logger.info(f"Task {task.id} stage updated from {previous_status} to {new_status}")

        # Trigger Temporal workflow for background processing
        self._trigger_workflow(task)

        return Response(TaskSerializer(task).data)

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
        summary="Bulk reorder tasks",
        description="Reorder tasks in bulk across one or more workflow stages. Tasks will be moved to the specified stages and assigned positions based on array order.",
        request=TaskBulkReorderRequestSerializer,
        responses={
            200: OpenApiResponse(response=TaskBulkReorderResponseSerializer, description="Bulk reorder results"),
            400: OpenApiResponse(response=ErrorResponseSerializer, description="Invalid request or stage keys"),
        },
        examples=[
            OpenApiExample(
                "Bulk Reorder Request",
                description="Example request to reorder tasks across multiple stages",
                request_only=True,
                value={
                    "columns": {
                        "TODO": ["123e4567-e89b-12d3-a456-426614174000", "456e7890-e89b-12d3-a456-426614174001"],
                        "IN_PROGRESS": ["789e0123-e89b-12d3-a456-426614174002"],
                        "DONE": ["012e3456-e89b-12d3-a456-426614174003"],
                    }
                },
            )
        ],
    )
    @action(detail=False, methods=["post"], url_path="bulk_reorder", required_scopes=["task:write"])
    def bulk_reorder(self, request, *args, **kwargs):
        payload = request.data or {}
        columns = payload.get("columns") or {}
        if not isinstance(columns, dict) or not columns:
            return Response(
                ErrorResponseSerializer({"error": "columns is required and must be a non-empty object"}).data,
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Flatten all ids and validate
        all_ids = []
        for stage_key, id_list in columns.items():
            # Validate that the stage key exists in at least one active workflow
            from .models import WorkflowStage

            if not WorkflowStage.objects.filter(key=stage_key, is_archived=False).exists():
                return Response(
                    ErrorResponseSerializer({"error": f"Invalid stage '{stage_key}'"}).data,
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if not isinstance(id_list, list):
                return Response(
                    ErrorResponseSerializer({"error": f"columns['{stage_key}'] must be a list of task ids"}).data,
                    status=status.HTTP_400_BAD_REQUEST,
                )
            all_ids.extend(id_list)

        if not all_ids:
            return Response(TaskBulkReorderResponseSerializer({"updated": 0, "tasks": []}).data)

        # Fetch tasks that belong to the current team
        tasks = Task.objects.filter(team=self.team, id__in=all_ids)
        task_by_id = {str(t.id): t for t in tasks}

        # Ensure all provided ids belong to the team
        missing = [tid for tid in all_ids if tid not in task_by_id]
        if missing:
            return Response(
                ErrorResponseSerializer({"error": f"Some task ids were not found for this team: {missing}"}).data,
                status=status.HTTP_400_BAD_REQUEST,
            )

        updated = []
        # Capture stage change events so we can trigger workflows after DB update
        stage_change_events = []  # list of tuples: (task_id, previous_status, new_status)
        with transaction.atomic():
            for stage_key, id_list in columns.items():
                # Find the stage for this key across all workflows
                from .models import WorkflowStage

                stage = WorkflowStage.objects.filter(key=stage_key, is_archived=False).first()

                for idx, tid in enumerate(id_list):
                    task = task_by_id[str(tid)]
                    task_needs_update = False

                    # Check if stage changed
                    if stage and task.current_stage != stage:
                        previous_status = task.current_stage.key if task.current_stage else "backlog"
                        task.current_stage = stage
                        task.workflow = stage.workflow
                        new_status = task.current_stage.key if task.current_stage else "backlog"

                        # Record stage changes so we can trigger workflows after bulk update
                        if previous_status != new_status:
                            stage_change_events.append((str(task.id), previous_status, new_status))
                        task_needs_update = True

                    # Check if position changed
                    if task.position != idx:
                        task.position = idx
                        task_needs_update = True

                    if task_needs_update:
                        updated.append(task)

            if updated:
                Task.objects.bulk_update(updated, ["current_stage", "workflow", "position"])

        # Trigger Temporal workflows for any tasks whose stage changed
        if stage_change_events:
            for task_id, previous_status, new_status in stage_change_events:
                try:
                    execute_task_processing_workflow(
                        task_id=str(task_id),
                        team_id=task_by_id[str(task_id)].team.id,
                        user_id=getattr(self.request.user, "id", None),
                    )
                except Exception:
                    logging.exception(
                        f"Failed to trigger task processing workflow for task {task_id}: {previous_status} -> {new_status}"
                    )

        # Return serialized updated tasks
        serialized = TaskSerializer(updated, many=True, context=self.get_serializer_context()).data
        response_data = {"updated": len(updated), "tasks": serialized}
        return Response(TaskBulkReorderResponseSerializer(response_data).data)

    @extend_schema(
        summary="Get task progress",
        description="Get the latest execution progress for a task's Claude Code workflow",
        responses={
            200: OpenApiResponse(
                response=TaskProgressResponseSerializer,
                description="Task progress information",
                examples=[
                    OpenApiExample(
                        "Progress Available",
                        description="Example response when progress is available",
                        response_only=True,
                        value={
                            "has_progress": True,
                            "id": "345e6789-e89b-12d3-a456-426614174004",
                            "status": "in_progress",
                            "current_step": "Running tests",
                            "completed_steps": 3,
                            "total_steps": 5,
                            "progress_percentage": 60.0,
                            "output_log": "✓ Code analysis complete\n✓ Dependencies installed\n✓ Tests running...",
                            "error_message": "",
                            "created_at": "2024-01-15T10:30:00Z",
                            "updated_at": "2024-01-15T10:35:00Z",
                            "completed_at": None,
                            "workflow_id": "task-workflow-123",
                            "workflow_run_id": "run-456",
                        },
                    ),
                    OpenApiExample(
                        "No Progress",
                        description="Example response when no progress is available",
                        response_only=True,
                        value={"has_progress": False, "message": "No execution progress found for this task"},
                    ),
                ],
            ),
            404: OpenApiResponse(description="Task not found"),
        },
    )
    @action(detail=True, methods=["get"], required_scopes=["task:read"])
    def progress(self, request, pk=None, **kwargs):
        task = self.get_object()

        # Get the most recent progress record for this task
        progress = TaskProgress.objects.filter(task=task, team=self.team).order_by("-created_at").first()

        if not progress:
            response_data = {"has_progress": False, "message": "No execution progress found for this task"}
            return Response(TaskProgressResponseSerializer(response_data).data)

        response_data = {
            "has_progress": True,
            "id": progress.id,
            "status": progress.status,
            "current_step": progress.current_step,
            "completed_steps": progress.completed_steps,
            "total_steps": progress.total_steps,
            "progress_percentage": progress.progress_percentage,
            "output_log": progress.output_log,
            "error_message": progress.error_message,
            "created_at": progress.created_at,
            "updated_at": progress.updated_at,
            "completed_at": progress.completed_at,
            "workflow_id": progress.workflow_id,
            "workflow_run_id": progress.workflow_run_id,
        }
        return Response(TaskProgressResponseSerializer(response_data).data)

    @extend_schema(
        summary="Stream task progress",
        description="Get real-time progress updates for a task. Use the 'since' parameter to get only recent updates.",
        parameters=[
            OpenApiParameter(
                name="since",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description="ISO datetime to get progress updates since (format: YYYY-MM-DDTHH:MM:SS.ffffffZ)",
            )
        ],
        responses={
            200: OpenApiResponse(
                response=TaskProgressStreamResponseSerializer,
                description="Recent progress updates",
            ),
            404: OpenApiResponse(description="Task not found"),
        },
    )
    @action(detail=True, methods=["get"], required_scopes=["task:read"])
    def progress_stream(self, request, pk=None, **kwargs):
        task = self.get_object()

        since = request.query_params.get("since")  # Timestamp to get updates since
        since_dt = parse_datetime(since) if since else None

        queryset = TaskProgress.objects.filter(task=task, team=self.team).order_by("-created_at")

        if since_dt:
            queryset = queryset.filter(updated_at__gt=since_dt)

        progress_records = queryset[:5]  # Limit to 5 most recent

        response_data = {
            "progress_updates": [
                {
                    "id": p.id,
                    "status": p.status,
                    "current_step": p.current_step,
                    "completed_steps": p.completed_steps,
                    "total_steps": p.total_steps,
                    "progress_percentage": p.progress_percentage,
                    "output_log": p.output_log,
                    "error_message": p.error_message,
                    "updated_at": p.updated_at,
                    "workflow_id": p.workflow_id,
                }
                for p in progress_records
            ],
            "server_time": timezone.now().isoformat(),
        }
        return Response(TaskProgressStreamResponseSerializer(response_data).data)


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
