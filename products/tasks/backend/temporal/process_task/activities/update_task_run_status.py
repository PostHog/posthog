from dataclasses import dataclass
from typing import Optional

from django.utils import timezone

from temporalio import activity

from posthog.temporal.common.utils import asyncify

from products.tasks.backend.models import TaskRun
from products.tasks.backend.temporal.observability import log_with_activity_context


@dataclass
class UpdateTaskRunStatusInput:
    run_id: str
    status: str
    error_message: Optional[str] = None


@activity.defn
@asyncify
def update_task_run_status(input: UpdateTaskRunStatusInput) -> None:
    """Update the status of a task run."""
    log_with_activity_context(
        "Updating task run status",
        run_id=input.run_id,
        status=input.status,
    )

    try:
        task_run = TaskRun.objects.get(id=input.run_id)
    except TaskRun.DoesNotExist:
        activity.logger.warning(f"TaskRun {input.run_id} not found for status update")
        return

    task_run.status = input.status

    if input.error_message:
        task_run.error_message = input.error_message

    if input.status in [TaskRun.Status.COMPLETED, TaskRun.Status.FAILED]:
        task_run.completed_at = timezone.now()

    task_run.save(update_fields=["status", "error_message", "completed_at", "updated_at"])

    log_with_activity_context(
        "Task run status updated",
        run_id=input.run_id,
        status=input.status,
    )
