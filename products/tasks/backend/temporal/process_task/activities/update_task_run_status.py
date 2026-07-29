from dataclasses import dataclass
from typing import Optional

from django.db import transaction
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

_TERMINAL_STATUSES = (TaskRun.Status.COMPLETED, TaskRun.Status.FAILED, TaskRun.Status.CANCELLED)


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
        # Lock the run row across the read-guard-save so a concurrent out-of-band cancel (a loop's
        # cancel_previous overlap policy, owner deactivation) can't slip a CANCELLED write in between
        # our read and save and get clobbered back to completed/failed. `of=("self",)` locks only the
        # run, not the joined task/team/created_by we select for the terminal-analytics join.
        with transaction.atomic():
            task_run = (
                TaskRun.objects.select_for_update(of=("self",))
                .select_related("task", "team", "task__created_by")
                .get(id=input.run_id)
            )

            old_status = task_run.status
            # Terminal statuses are final. A run cancelled out of band must not be resurrected to
            # completed/failed by its own workflow finishing afterward, which would both lie in the
            # audit trail and undo the cancellation. Re-checked here while holding the row lock.
            if old_status in _TERMINAL_STATUSES and input.status != old_status:
                log_with_activity_context(
                    "Skipping terminal status overwrite",
                    run_id=input.run_id,
                    old_status=old_status,
                    new_status=input.status,
                )
                return

            task_run.status = input.status
            if input.error_message:
                task_run.error_message = input.error_message
            if input.timed_out_inactivity:
                # Atomic merge so concurrent state writers aren't clobbered; reassigned so reads below see it.
                task_run.state = TaskRun.update_state_atomic(
                    task_run.id, updates={TIMED_OUT_INACTIVITY_STATE_KEY: True}
                )
            if input.status in [TaskRun.Status.COMPLETED, TaskRun.Status.FAILED]:
                task_run.completed_at = timezone.now()
            elif (
                input.status == TaskRun.Status.CANCELLED
                and task_run.environment == TaskRun.Environment.CLOUD
                and not task_run.completed_at
            ):
                task_run.completed_at = timezone.now()
            task_run.save(update_fields=["status", "error_message", "completed_at", "updated_at"])
    except TaskRun.DoesNotExist:
        activity.logger.warning(f"TaskRun {input.run_id} not found for status update")
        return

    # Side effects run after commit, outside the row lock (repo convention: no side effects in atomic).
    task_run.publish_stream_state_event()
    observe_wizard_run_unbound(task_run)

    if input.status in [TaskRun.Status.COMPLETED, TaskRun.Status.FAILED] and old_status != input.status:
        _capture_terminal_analytics(task_run, input)

    # This activity is how workflow-driven runs (finish tool, failures, timeouts, cancellations)
    # reach a terminal status, so loop bookkeeping must hook in here, not only in the HTTP PATCH
    # path (facade.api.update_task_run). Guarded on the actual transition so repeats and the
    # PATCH-then-activity dual write don't double-count consecutive_failures; swallowed so a
    # bookkeeping failure never fails (and re-runs) the status write itself.
    if old_status != input.status:
        from products.tasks.backend.logic.services.loop_runs import (  # noqa: PLC0415 — breaks the loop_runs -> process_task -> activities import cycle
            handle_loop_run_terminal,
        )

        try:
            handle_loop_run_terminal(task_run)
        except Exception:
            activity.logger.warning(f"Failed loop terminal bookkeeping for run {task_run.id}", exc_info=True)

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
            adapter = state.get("runtime_adapter")
            record_run_token_usage(
                usage,
                origin_product=task_run.task.origin_product,
                run_environment=task_run.environment,
                rtk_enabled=task_run.effective_rtk(),
                runtime_adapter=adapter if isinstance(adapter, str) else None,
                status=input.status,
            )
    except Exception:
        activity.logger.warning(f"Failed to capture terminal analytics for run {task_run.id}", exc_info=True)
