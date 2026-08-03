import logging
from typing import Any, Literal

from django.db import transaction

from temporalio.service import RPCError, RPCStatusCode

from products.notifications.backend.facade.api import (
    NotificationData,
    NotificationType,
    Priority,
    TargetType,
    create_notification,
)
from products.tasks.backend.facade.api import resume_task_run_in_cloud
from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.temporal.client import signal_task_followup_message
from products.tasks.backend.temporal.constants import CHILD_EVENT_MESSAGE_TEMPLATE
from products.tasks.backend.temporal.execute_sandbox.workflow import FOLLOWUP_SOURCE_CHILD

logger = logging.getLogger(__name__)

ChildEvent = Literal["terminal", "pr_merged"]
PENDING_ORCHESTRATION_WAKES_STATE_KEY = "pending_orchestration_wakes"
ORCHESTRATION_RESUME_STATE_KEY = "orchestration_resume"
MAX_ORCHESTRATION_RESUME_ATTEMPTS = 3

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


def _claim_resume(run_id: str) -> tuple[TaskRun | None, list[dict[str, Any]], int]:
    with transaction.atomic():
        run = TaskRun.objects.select_for_update().select_related("task", "task__created_by").get(id=run_id)
        state = dict(run.state or {})
        resume = state.get(ORCHESTRATION_RESUME_STATE_KEY)
        resume = dict(resume) if isinstance(resume, dict) else {}
        if resume.get("in_flight"):
            return None, [], int(resume.get("attempts", 0))
        attempts = int(resume.get("attempts", 0))
        if attempts >= MAX_ORCHESTRATION_RESUME_ATTEMPTS:
            return None, [], attempts
        queued = state.get(PENDING_ORCHESTRATION_WAKES_STATE_KEY)
        wakes = list(queued) if isinstance(queued, list) else []
        if not wakes:
            return None, [], attempts
        state[ORCHESTRATION_RESUME_STATE_KEY] = {"in_flight": True, "attempts": attempts + 1}
        run.state = state
        run.save(update_fields=["state", "updated_at"])
        return run, wakes, attempts + 1


def _release_resume(run_id: str, *, delivered: list[dict[str, Any]], success: bool) -> bool:
    has_pending = False

    def update(state: dict[str, Any]) -> None:
        nonlocal has_pending
        resume = state.get(ORCHESTRATION_RESUME_STATE_KEY)
        resume = dict(resume) if isinstance(resume, dict) else {}
        resume["in_flight"] = False
        if success:
            resume["attempts"] = 0
            queued = state.get(PENDING_ORCHESTRATION_WAKES_STATE_KEY)
            queue = list(queued) if isinstance(queued, list) else []
            remaining = list(queue)
            for entry in delivered:
                if entry in remaining:
                    remaining.remove(entry)
            if remaining:
                state[PENDING_ORCHESTRATION_WAKES_STATE_KEY] = remaining
                has_pending = True
            else:
                state.pop(PENDING_ORCHESTRATION_WAKES_STATE_KEY, None)
        state[ORCHESTRATION_RESUME_STATE_KEY] = resume

    TaskRun.mutate_state_atomic(run_id, update)
    return has_pending


def _notify_resume_exhausted(run: TaskRun) -> None:
    if run.task.created_by_id is None:
        return
    create_notification(
        NotificationData(
            team_id=run.team_id,
            notification_type=NotificationType.PIPELINE_FAILURE,
            priority=Priority.CRITICAL,
            title=f'Could not resume task "{run.task.title}"'[:100],
            body="Automatic resume failed repeatedly. Open the task to retry and review pending child updates.",
            target_type=TargetType.USER,
            target_id=str(run.task.created_by_id),
            resource_type="task",
            resource_id=str(run.task_id),
        )
    )


def resume_parent_with_pending_wakes(run_id: str) -> bool:
    run, wakes, attempt = _claim_resume(run_id)
    if run is None:
        if attempt >= MAX_ORCHESTRATION_RESUME_ATTEMPTS:
            exhausted_run = TaskRun.objects.select_related("task", "task__created_by").get(id=run_id)
            _notify_resume_exhausted(exhausted_run)
        return False

    message = "\n\n".join(str(entry.get("message", "")) for entry in wakes if entry.get("message"))
    try:
        outcome, _, _ = resume_task_run_in_cloud(run.id, run.task_id, run.team_id, run.task.created_by_id)
        if outcome not in {"resumed", "already_active"}:
            raise RuntimeError(f"Cold parent resume failed: {outcome}")
        signal_task_followup_message(run.workflow_id, message, [], source=FOLLOWUP_SOURCE_CHILD)
    except Exception:
        _release_resume(str(run.id), delivered=[], success=False)
        if attempt >= MAX_ORCHESTRATION_RESUME_ATTEMPTS:
            _notify_resume_exhausted(run)
        raise

    has_pending = _release_resume(str(run.id), delivered=wakes, success=True)
    sources = {entry.get("event") for entry in wakes}
    run.capture_event(
        "parent_woken",
        {
            "source": next(iter(sources)) if len(sources) == 1 else "multiple",
            "cold": True,
            "queued_count": len(wakes),
        },
    )
    if has_pending:
        _schedule_cold_resume(str(run.id))
    return True


def _schedule_cold_resume(run_id: str) -> None:
    from products.tasks.backend.facade.tasks import resume_parent_with_pending_wakes_task

    resume_parent_with_pending_wakes_task.delay(run_id)


def notify_parent_of_child_event(child_run: TaskRun | str, event: ChildEvent) -> None:
    if isinstance(child_run, str):
        resolved_child_run = TaskRun.objects.select_related("task").filter(id=child_run).first()
        if resolved_child_run is None:
            return
        child_run = resolved_child_run

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
                _schedule_cold_resume(str(delivery_run.id))
                return
            logger.exception(
                "orchestration_child_wake_signal_failed",
                extra={"child_run_id": str(child_run.id), "parent_run_id": str(live_run.id), "event": event},
            )
            raise
        live_run.capture_event("parent_woken", {"source": event, "cold": False, "queued_count": 0})
        return

    _queue_wake(delivery_run, child_run, event, message)
    _schedule_cold_resume(str(delivery_run.id))


def send_child_message_to_parent(child_run: TaskRun, message: str) -> None:
    state = child_run.state if isinstance(child_run.state, dict) else {}
    parent_task_id = state.get("parent_task_id")
    parent_run_id = state.get("parent_run_id")
    if not parent_task_id or not parent_run_id:
        raise ValueError("Calling run is not an orchestrated child")

    parent_run = (
        TaskRun.objects.filter(id=parent_run_id, task_id=parent_task_id, team_id=child_run.team_id)
        .filter(status__in=_NON_TERMINAL_STATUSES)
        .first()
    )
    if parent_run is None:
        raise ValueError("Parent run is not available")

    signal_task_followup_message(parent_run.workflow_id, message, [], source=FOLLOWUP_SOURCE_CHILD)
