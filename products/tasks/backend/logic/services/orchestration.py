import logging
from typing import Any, Literal

from temporalio.service import RPCError, RPCStatusCode

from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.temporal.client import signal_task_followup_message
from products.tasks.backend.temporal.constants import CHILD_EVENT_MESSAGE_TEMPLATE
from products.tasks.backend.temporal.execute_sandbox.workflow import FOLLOWUP_SOURCE_CHILD

logger = logging.getLogger(__name__)

ChildEvent = Literal["terminal", "pr_merged"]
PENDING_ORCHESTRATION_WAKES_STATE_KEY = "pending_orchestration_wakes"

_NON_TERMINAL_STATUSES = (TaskRun.Status.NOT_STARTED, TaskRun.Status.QUEUED, TaskRun.Status.IN_PROGRESS)


def _build_child_event_message(child_run: TaskRun, event: ChildEvent) -> str:
    output = child_run.output if isinstance(child_run.output, dict) else {}
    pr_url = output.get("pr_url")
    error_line = (
        f"\nError: {child_run.error_message}"
        if child_run.status == TaskRun.Status.FAILED and child_run.error_message
        else ""
    )
    pr_line = f"\nPull request: {pr_url}" if isinstance(pr_url, str) and pr_url else ""
    task_number = child_run.task.task_number if child_run.task.task_number is not None else "unknown"
    return CHILD_EVENT_MESSAGE_TEMPLATE.format(
        task_number=task_number,
        title=child_run.task.title,
        event=event.replace("_", " "),
        status=child_run.status,
        error_line=error_line,
        pr_line=pr_line,
    )


def _queue_wake(parent_run: TaskRun, child_run: TaskRun, event: ChildEvent, message: str) -> None:
    entry: dict[str, Any] = {
        "message": message,
        "artifact_ids": [],
        "source": FOLLOWUP_SOURCE_CHILD,
        "event": event,
        "child_run_id": str(child_run.id),
    }

    def append_wake(state: dict[str, Any]) -> None:
        pending = state.get(PENDING_ORCHESTRATION_WAKES_STATE_KEY)
        queue = list(pending) if isinstance(pending, list) else []
        queue.append(entry)
        state[PENDING_ORCHESTRATION_WAKES_STATE_KEY] = queue

    TaskRun.mutate_state_atomic(parent_run.id, append_wake)


def notify_parent_of_child_event(child_run: TaskRun | str, event: ChildEvent) -> None:
    if isinstance(child_run, str):
        child_run = TaskRun.objects.select_related("task").filter(id=child_run).first()
        if child_run is None:
            return

    state = child_run.state if isinstance(child_run.state, dict) else {}
    parent_task_id = state.get("parent_task_id")
    if not parent_task_id:
        return

    parent_task = Task.objects.filter(id=parent_task_id, team_id=child_run.team_id).first()
    if parent_task is None:
        return

    most_recent_run = parent_task.runs.order_by("-created_at", "-id").first()
    if most_recent_run is None:
        return

    live_run = parent_task.runs.filter(status__in=_NON_TERMINAL_STATUSES).order_by("-created_at", "-id").first()
    delivery_run = live_run or most_recent_run
    message = _build_child_event_message(child_run, event)

    if live_run is not None:
        try:
            signal_task_followup_message(
                live_run.workflow_id,
                message,
                [],
                source=FOLLOWUP_SOURCE_CHILD,
            )
        except RPCError as error:
            if error.status == RPCStatusCode.NOT_FOUND:
                _queue_wake(delivery_run, child_run, event, message)
                return
            logger.exception(
                "orchestration_child_wake_signal_failed",
                extra={"child_run_id": str(child_run.id), "parent_run_id": str(live_run.id), "event": event},
            )
            raise
        return

    _queue_wake(delivery_run, child_run, event, message)
