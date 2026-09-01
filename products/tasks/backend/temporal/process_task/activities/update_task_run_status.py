from dataclasses import dataclass
from typing import Any, Optional

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from temporalio import activity
from temporalio.exceptions import ApplicationError

from posthog.temporal.common.utils import asyncify

from products.tasks.backend.error_telemetry import truncate_error_message
from products.tasks.backend.metrics import observe_prewarmed_unused_if_never_activated, observe_wizard_run_unbound
from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.temporal.metrics import record_run_token_usage
from products.tasks.backend.temporal.observability import log_with_activity_context

# TaskRun.state marker for runs completed by the inactivity timeout; kept out of
# error_message so a normal completion never reads as a failure.
TIMED_OUT_INACTIVITY_STATE_KEY = "timed_out_inactivity"
# TaskRun.state marker for runs stopped by the hard wall-clock cap. Written without an
# error_message: the marker is the machine-readable reason, and a fabricated prose
# message would just get parroted back to users by every error surface.
TIMED_OUT_WALL_CLOCK_STATE_KEY = "timed_out_wall_clock"
# TaskRun.state marker for runs terminalized because their sandbox disappeared.
SANDBOX_GONE_STATE_KEY = "sandbox_gone"

# Allowlist for `timeout_marker` so the activity never writes an arbitrary state key.
_TERMINAL_STATE_MARKERS = (
    TIMED_OUT_INACTIVITY_STATE_KEY,
    TIMED_OUT_WALL_CLOCK_STATE_KEY,
    SANDBOX_GONE_STATE_KEY,
)

_TERMINAL_STATUSES = (TaskRun.Status.COMPLETED, TaskRun.Status.FAILED, TaskRun.Status.CANCELLED)


@dataclass(frozen=False)
class UpdateTaskRunStatusInput:
    run_id: str
    status: str
    error_message: Optional[str] = None
    timed_out_inactivity: bool = False
    # Optional with a default so payloads from in-flight workflows started
    # before this field existed still deserialize.
    error_type: Optional[str] = None
    # One of _TERMINAL_STATE_MARKERS, recorded as a True key in TaskRun.state.
    # Optional with a default for the same in-flight payload reason as error_type.
    timeout_marker: Optional[str] = None
    agent_active_at_termination: Optional[bool] = None
    end_of_turn_received: Optional[bool] = None
    last_agent_heartbeat_at: Optional[str] = None
    seconds_since_last_agent_heartbeat: Optional[float] = None


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
            marker = TIMED_OUT_INACTIVITY_STATE_KEY if input.timed_out_inactivity else input.timeout_marker
            if marker in _TERMINAL_STATE_MARKERS:
                # Atomic merge so concurrent state writers aren't clobbered; reassigned so reads below see it.
                task_run.state = TaskRun.update_state_atomic(task_run.id, updates={marker: True})
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
        # The row was hard-deleted mid-run (team/org deletion cascades bypass the model
        # delete() guards). Nothing can ever terminalize this run again, so fail the
        # workflow instead of letting it run on believing the status was written.
        raise ApplicationError(
            f"TaskRun {input.run_id} no longer exists; its rows were deleted while the workflow was running",
            non_retryable=True,
            type="TaskRunDeletedError",
        )

    # Side effects run after commit, outside the row lock (repo convention: no side effects in atomic).
    task_run.publish_stream_state_event()
    observe_wizard_run_unbound(task_run)

    if input.status in _TERMINAL_STATUSES and old_status != input.status:
        task_run.close_ci_progress_step()

    if input.status in [TaskRun.Status.COMPLETED, TaskRun.Status.FAILED] and old_status != input.status:
        _capture_terminal_analytics(task_run, input)

    if input.timed_out_inactivity and old_status != input.status:
        task_run.task.soft_delete_if_unclaimed_prewarm(task_run)

    # A warm Run that reaches terminal without ever being activated was never used — the sandbox was
    # booted and thrown away. Counting it against `prewarmed_activated_total` gives the warm hit rate,
    # and the reason separates a deliberate hand-back from one nobody reclaimed.
    if input.status in _TERMINAL_STATUSES and old_status != input.status:
        observe_prewarmed_unused_if_never_activated(
            task_run,
            reason="idle_timeout"
            if input.timed_out_inactivity
            else ("released" if input.status == TaskRun.Status.CANCELLED else "other"),
        )

    if input.status in _TERMINAL_STATUSES:
        from products.tasks.backend.logic.services.loop_runs import (  # noqa: PLC0415 — breaks the loop_runs -> process_task -> activities import cycle
            handle_loop_run_terminal,
        )

        try:
            handle_loop_run_terminal(task_run, error_type=input.error_type)
        except Exception:
            activity.logger.warning(f"Failed loop terminal bookkeeping for run {task_run.id}", exc_info=True)

    log_with_activity_context(
        "Task run status updated",
        run_id=input.run_id,
        status=input.status,
        termination_reason=marker if marker in _TERMINAL_STATE_MARKERS else None,
    )


def _capture_posthog_ai_chat_analytics(
    task_run: TaskRun, input: UpdateTaskRunStatusInput, *, termination_reason: Optional[str]
) -> None:
    """Emit the PostHog AI chat outcome events, the sandbox counterpart to legacy `chat with ai`.

    PostHog AI usage series are built on `chat with ai`, which only the LangGraph runner emits
    (`ee/hogai/chat_agent/runner.py`). A sandbox conversation never reaches that runner, so without
    this the series decay to zero as conversations move over.

    This sits on the run transition rather than on each turn, so it fires only once the outcome is
    known. A run spans every turn its sandbox stays alive, so the event counts runs where the legacy
    one counted turns — `usage_turns` carries the turn count for a series that needs it.
    """
    if task_run.task.origin_product != Task.OriginProduct.POSTHOG_AI:
        return
    state = task_run.state if isinstance(task_run.state, dict) else {}
    if state.get("await_user_message"):
        # A prewarmed sandbox that idled out before anyone typed into it. The inactivity timeout
        # terminalizes it as completed, so without this guard, opening the panel and walking away
        # counts as a chat. PostHog AI removes the key when it delivers the first message; that
        # removal is best-effort, so a failed one drops a real chat rather than inventing one.
        return
    properties = {
        "agent_runtime": "sandbox",
        # Agent modes are a LangGraph concept, and the sandbox runtime has none.
        "agent_mode": None,
        "is_new_conversation": _is_first_chat_run_of_task(task_run, state),
        "duration_seconds": task_run._duration_seconds(),
        "termination_reason": termination_reason,
    }
    if input.status == TaskRun.Status.COMPLETED:
        task_run.capture_event("chat with ai", properties)
        return
    task_run.capture_event(
        "chat with ai failed",
        {
            **properties,
            "error_message": truncate_error_message(input.error_message or task_run.error_message),
            "error_type": input.error_type or "unspecified",
        },
    )


def _is_first_chat_run_of_task(task_run: TaskRun, state: dict[str, Any]) -> bool:
    """Whether this run opened the conversation, the run-level reading of `is_new_conversation`.

    A terminal run resumes into a successor rather than reopening, so "no earlier run" is what
    separates a new conversation from a continued one. Two kinds of earlier history do not count:

    - A prewarm nobody typed into. It idles out on its own and the next message resumes into a
      successor, so counting it would report the user's first real chat as a continuation.
    - The LangGraph half of a converted conversation. That conversation already counted once on
      the legacy runtime, and its sandbox side starts on a fresh task with no earlier run.
    """
    if state.get("converted_from_langgraph"):
        return False
    # Match the prewarm on the key's absence rather than with `exclude`. A queryset `exclude` on a
    # JSON key compares NULL for every row that lacks the key, so it would drop exactly the earlier
    # runs that did hold a chat and report every conversation as new.
    held_a_chat = ~Q(state__has_key="await_user_message") | Q(state__await_user_message=False)
    return (
        not TaskRun.objects.filter(
            task_id=task_run.task_id, team_id=task_run.team_id, created_at__lt=task_run.created_at
        )
        .filter(held_a_chat)
        .exists()
    )


def _capture_terminal_analytics(task_run: TaskRun, input: UpdateTaskRunStatusInput) -> None:
    """Emit the terminal analytics event and token-expenditure metrics.

    This activity performs the DB status transition, so it is the single canonical
    emitter of the terminal analytics events for workflow-driven runs — the workflow
    itself only records metrics and logs for failures. Guarded on the actual
    transition so activity retries and repeat updates don't double-count.
    """
    try:
        marker = TIMED_OUT_INACTIVITY_STATE_KEY if input.timed_out_inactivity else input.timeout_marker
        termination_reason = marker if marker in _TERMINAL_STATE_MARKERS else None
        relay_state = {
            "agent_active_at_termination": input.agent_active_at_termination,
            "end_of_turn_received": input.end_of_turn_received,
            "last_agent_heartbeat_at": input.last_agent_heartbeat_at,
            "seconds_since_last_agent_heartbeat": input.seconds_since_last_agent_heartbeat,
        }
        if input.status == TaskRun.Status.COMPLETED:
            task_run.capture_event(
                "task_run_completed",
                {
                    "duration_seconds": task_run._duration_seconds(),
                    "termination_reason": termination_reason,
                    **relay_state,
                },
            )
        else:
            task_run.capture_event(
                "task_run_failed",
                {
                    "error_message": truncate_error_message(input.error_message or task_run.error_message),
                    "error_type": input.error_type or "unspecified",
                    "duration_seconds": task_run._duration_seconds(),
                    "termination_reason": termination_reason,
                    **relay_state,
                },
            )

        _capture_posthog_ai_chat_analytics(task_run, input, termination_reason=termination_reason)

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
