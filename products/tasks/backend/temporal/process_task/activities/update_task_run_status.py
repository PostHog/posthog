from dataclasses import dataclass
from typing import Optional

from django.utils import timezone

from temporalio import activity

from posthog.temporal.common.utils import asyncify

from products.tasks.backend.error_telemetry import truncate_error_message
from products.tasks.backend.metrics import observe_wizard_run_unbound
from products.tasks.backend.models import TaskRun
from products.tasks.backend.temporal.metrics import record_run_token_usage
from products.tasks.backend.temporal.observability import log_with_activity_context

# TaskRun.state marker for runs completed by the inactivity timeout; kept out of
# error_message so a normal completion never reads as a failure.
TIMED_OUT_INACTIVITY_STATE_KEY = "timed_out_inactivity"


@dataclass
class UpdateTaskRunStatusInput:
    run_id: str
    status: str
    error_message: Optional[str] = None
    timed_out_inactivity: bool = False
    # Optional with a default so payloads from in-flight workflows started
    # before this field existed still deserialize.
    error_type: Optional[str] = None


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
        # Terminal transitions capture analytics that traverse task, team, and
        # task.created_by; join them upfront instead of three lazy queries.
        task_run = TaskRun.objects.select_related("task", "team", "task__created_by").get(id=input.run_id)
    except TaskRun.DoesNotExist:
        activity.logger.warning(f"TaskRun {input.run_id} not found for status update")
        return

    old_status = task_run.status
    task_run.status = input.status

    if input.error_message:
        task_run.error_message = input.error_message

    if input.timed_out_inactivity:
        # Atomic merge so concurrent state writers aren't clobbered; reassigned so reads below see it.
        task_run.state = TaskRun.update_state_atomic(task_run.id, updates={TIMED_OUT_INACTIVITY_STATE_KEY: True})

    if input.status in [TaskRun.Status.COMPLETED, TaskRun.Status.FAILED]:
        task_run.completed_at = timezone.now()

    task_run.save(update_fields=["status", "error_message", "completed_at", "updated_at"])
    task_run.publish_stream_state_event()
    observe_wizard_run_unbound(task_run)

    if input.status in [TaskRun.Status.COMPLETED, TaskRun.Status.FAILED] and old_status != input.status:
        _capture_terminal_analytics(task_run, input)
        # Wake a parked workflow agent_task step, if this run was started by one.
        task_run.emit_workflow_completion_event_if_needed()

    log_with_activity_context(
        "Task run status updated",
        run_id=input.run_id,
        status=input.status,
    )


def _capture_terminal_analytics(task_run: TaskRun, input: UpdateTaskRunStatusInput) -> None:
    """Emit the terminal analytics event and token-expenditure metrics.

    This activity performs the DB status transition, so it is the single canonical
    emitter of the terminal analytics events for workflow-driven runs — the workflow
    itself only records metrics and logs for failures. Guarded on the actual
    transition so activity retries and repeat updates don't double-count.
    """
    try:
        if input.status == TaskRun.Status.COMPLETED:
            task_run.capture_event("task_run_completed", {"duration_seconds": task_run._duration_seconds()})
        else:
            task_run.capture_event(
                "task_run_failed",
                {
                    "error_message": truncate_error_message(input.error_message or task_run.error_message),
                    "error_type": input.error_type or "unspecified",
                    "duration_seconds": task_run._duration_seconds(),
                },
            )

        state = task_run.state if isinstance(task_run.state, dict) else {}
        usage = state.get("token_usage")
        if isinstance(usage, dict):
            record_run_token_usage(
                usage,
                origin_product=task_run.task.origin_product,
                run_environment=task_run.environment,
                rtk_enabled=task_run.effective_rtk(),
                status=input.status,
            )
    except Exception:
        activity.logger.warning(f"Failed to capture terminal analytics for run {task_run.id}", exc_info=True)
