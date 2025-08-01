from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.permissions import APIScopePermission
from .models import Task, TaskProgress
from .serializers import TaskSerializer
from .temporal.client import execute_task_processing_workflow
import logging


class TaskViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    serializer_class = TaskSerializer
    permission_classes = [IsAuthenticated, APIScopePermission]
    required_scopes = ["task:read"]
    scope_object = "task"
    queryset = Task.objects.all()

    def safely_get_queryset(self, queryset):
        return queryset.filter(team=self.team).order_by("position")

    def get_serializer_context(self):
        return {**super().get_serializer_context(), "team": self.team}

    def perform_create(self, serializer):
        serializer.save(team=self.team)

    def perform_update(self, serializer):
        import logging

        logger = logging.getLogger(__name__)

        # Get the current task state before update
        task = serializer.instance
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
                    team_id=task.team_id,
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

        task = self.get_object()
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
                    team_id=task.team_id,
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
