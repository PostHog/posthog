from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.permissions import APIScopePermission, PostHogFeatureFlagPermission
from .models import Task, TaskProgress
from typing import cast
from .serializers import TaskSerializer
from .temporal.client import execute_task_processing_workflow
import logging


class TaskViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    serializer_class = TaskSerializer
    permission_classes = [IsAuthenticated, APIScopePermission, PostHogFeatureFlagPermission]
    # Scope and object used by APIScopePermission. Use either an existing object name or INTERNAL to bypass access-level mapping.
    required_scopes = ["INTERNAL"]
    scope_object = "INTERNAL"
    queryset = Task.objects.all()
    # Require the 'tasks' PostHog feature flag for all actions
    posthog_feature_flag = {
        "tasks": [
            "list",
            "retrieve",
            "create",
            "update",
            "partial_update",
            "destroy",
            "update_status",
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
        import logging

        logger = logging.getLogger(__name__)
        logger.info(f"Creating task with data: {serializer.validated_data}")
        serializer.save(team=self.team)

    def perform_update(self, serializer):
        import logging

        logger = logging.getLogger(__name__)

        # Get the current task state before update
        task = cast(Task, serializer.instance)
        previous_status = task.status

        logger.info(f"perform_update called for task {task.id} with validated_data: {serializer.validated_data}")

        # Save the changes
        serializer.save()

        # Check if status changed and trigger workflow
        new_status = serializer.validated_data.get("status", previous_status)
        if new_status != previous_status:
            logger.info(f"Task {task.id} status changed from {previous_status} to {new_status}")

            try:
                logger.info(f"Attempting to trigger workflow for task {task.id}")
                execute_task_processing_workflow(
                    task_id=str(task.id),
                    team_id=task.team.id,
                    previous_status=previous_status,
                    new_status=new_status,
                    user_id=getattr(self.request.user, "id", None),
                )
                logger.info(f"Workflow trigger completed for task {task.id}")
            except Exception as e:
                logger.exception(f"Failed to trigger task processing workflow for task {task.id}: {e}")
                import traceback

                logger.exception(f"Workflow error traceback: {traceback.format_exc()}")
        else:
            logger.info(f"Task {task.id} updated but status unchanged ({previous_status})")

    @action(detail=True, methods=["patch"])
    def update_status(self, request, pk=None):
        import logging

        logger = logging.getLogger(__name__)

        logger.info(f"update_status called for task {pk} with data: {request.data}")

        task = cast(Task, self.get_object())
        new_status = request.data.get("status")

        logger.info(f"Task {task.id}: current_status={task.status}, new_status={new_status}")

        if new_status and new_status in Task.Status.values:
            previous_status = task.status
            task.status = new_status
            task.save()

            logger.info(f"Task {task.id} status updated from {previous_status} to {new_status}")

            # Trigger Temporal workflow for background processing
            try:
                logger.info(f"Attempting to trigger workflow for task {task.id}")
                execute_task_processing_workflow(
                    task_id=str(task.id),
                    team_id=task.team.id,
                    previous_status=previous_status,
                    new_status=new_status,
                    user_id=getattr(request.user, "id", None),
                )
                logger.info(f"Workflow trigger completed for task {task.id}")
            except Exception as e:
                # Log the error but don't fail the status update
                logger.exception(f"Failed to trigger task processing workflow for task {task.id}: {e}")
                import traceback

                logger.exception(f"Workflow error traceback: {traceback.format_exc()}")

            return Response(TaskSerializer(task).data)
        else:
            logger.warning(f"Invalid status '{new_status}' for task {pk}. Valid statuses: {Task.Status.values}")
        return Response({"error": "Invalid status"}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["patch"])
    def update_position(self, request, pk=None):
        task = self.get_object()
        new_position = request.data.get("position")
        if new_position is not None:
            task.position = new_position
            task.save()
            return Response(TaskSerializer(task).data)
        return Response({"error": "Position is required"}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=["post"], url_path="bulk_reorder")
    def bulk_reorder(self, request, *args, **kwargs):
        """
        Reorder tasks in bulk across one or more columns (statuses).

        Expected payload:
        {
            "columns": {
                "TODO": ["id1", "id2", ...],
                "IN_PROGRESS": ["id3", ...],
                ...
            }
        }
        Only the provided IDs will be updated. Positions are assigned based on array order (0..n-1),
        and status is set to the column key.
        """
        from django.db import transaction

        payload = request.data or {}
        columns = payload.get("columns") or {}
        if not isinstance(columns, dict) or not columns:
            return Response(
                {"error": "columns is required and must be a non-empty object"}, status=status.HTTP_400_BAD_REQUEST
            )

        # Flatten all ids and validate
        all_ids = []
        for status_key, id_list in columns.items():
            if status_key not in Task.Status.values:
                return Response({"error": f"Invalid status '{status_key}'"}, status=status.HTTP_400_BAD_REQUEST)
            if not isinstance(id_list, list):
                return Response(
                    {"error": f"columns['{status_key}'] must be a list of task ids"}, status=status.HTTP_400_BAD_REQUEST
                )
            all_ids.extend(id_list)

        if not all_ids:
            return Response({"updated": 0, "tasks": []})

        # Fetch tasks that belong to the current team
        tasks = Task.objects.filter(team=self.team, id__in=all_ids)
        task_by_id = {str(t.id): t for t in tasks}

        # Ensure all provided ids belong to the team
        missing = [tid for tid in all_ids if tid not in task_by_id]
        if missing:
            return Response(
                {"error": f"Some task ids were not found for this team: {missing}"}, status=status.HTTP_400_BAD_REQUEST
            )

        updated = []
        with transaction.atomic():
            for status_key, id_list in columns.items():
                for idx, tid in enumerate(id_list):
                    task = task_by_id[str(tid)]
                    if task.status != status_key or task.position != idx:
                        task.status = status_key
                        task.position = idx
                        updated.append(task)

            if updated:
                Task.objects.bulk_update(updated, ["status", "position"])  # updated_at handled by model defaults if any

        # Return serialized updated tasks
        serialized = TaskSerializer(updated, many=True, context=self.get_serializer_context()).data
        return Response({"updated": len(updated), "tasks": serialized})

    @action(detail=True, methods=["get"])
    def progress(self, request, pk=None, **kwargs):
        """Get the latest progress for a task's Claude Code execution."""
        task = self.get_object()
        try:
            # Get the most recent progress record for this task
            progress = TaskProgress.objects.filter(task=task, team=self.team).order_by("-created_at").first()

            if not progress:
                return Response({"has_progress": False, "message": "No execution progress found for this task"})

            return Response(
                {
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
            )

        except Exception:
            logging.exception("Error fetching task progress")
            return Response(
                {"error": "An internal error occurred while fetching progress."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=True, methods=["get"])
    def progress_stream(self, request, pk=None, **kwargs):
        """Get real-time progress updates (polling endpoint)."""
        task = self.get_object()
        since = request.query_params.get("since")  # Timestamp to get updates since

        try:
            queryset = TaskProgress.objects.filter(task=task, team=self.team).order_by("-created_at")

            if since:
                from django.utils.dateparse import parse_datetime

                since_dt = parse_datetime(since)
                if since_dt:
                    queryset = queryset.filter(updated_at__gt=since_dt)

            progress_records = queryset[:5]  # Limit to 5 most recent

            return Response(
                {
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
            )

        except Exception:
            return Response(
                {"error": "An internal error occurred while fetching progress stream."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
