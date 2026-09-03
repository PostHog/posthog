from typing import Any
from uuid import UUID

from celery import current_app

from posthog.cdp.workflow_step_resume import WorkflowStepResumeStatus, resume_workflow_step

from products.tasks.backend.models import Task, TaskRun

_STATUS_BY_RUN_STATUS: dict[str, WorkflowStepResumeStatus] = {
    TaskRun.Status.COMPLETED: "completed",
    TaskRun.Status.FAILED: "failed",
    TaskRun.Status.CANCELLED: "cancelled",
}

# The agent's `finish` tool completes the run a few seconds before the event relay persists the
# agent's final message. A completed run without one waits this long for the message to land
# (the relay wakes the step as soon as it does); the deferred wake only fires for a run that
# never gets one.
FINAL_MESSAGE_GRACE_SECONDS = 30

DEFERRED_RESUME_TASK = "products.tasks.backend.tasks.tasks.resume_workflow_step_for_run_deferred"


def _result_for_run(task_run: TaskRun) -> dict[str, Any]:
    output = task_run.output or {}
    return {
        "run_id": str(task_run.id),
        "final_message": output.get("final_message"),
        "pr_urls": output.get("pr_urls") or ([output["pr_url"]] if output.get("pr_url") else None),
        "error_message": task_run.error_message,
    }


def _workflow_origin_key(task_run: TaskRun) -> str | None:
    task = task_run.task
    if task.origin_product != Task.OriginProduct.WORKFLOW or not task.origin_key:
        return None
    return task.origin_key


def _emit(task_run: TaskRun, origin_key: str, status: WorkflowStepResumeStatus) -> None:
    resume_workflow_step(
        team_id=task_run.task.team_id, origin_key=origin_key, status=status, result=_result_for_run(task_run)
    )


def resume_workflow_step_for_run(task_run: TaskRun, *, wait_for_final_message: bool = True) -> None:
    """Wake the workflow step waiting on this run, if a workflow started it. Call once, on the
    actual transition into a terminal status; a repeat is harmless but wasted.

    A completed run whose final message has not landed yet defers the wake instead of sending an
    empty one. The step consumes only the first wake for its key, so whichever of the deferred
    wake and the relay's post-message wake arrives second is dropped."""
    status = _STATUS_BY_RUN_STATUS.get(task_run.status)
    if status is None:
        return
    origin_key = _workflow_origin_key(task_run)
    if origin_key is None:
        return
    if wait_for_final_message and status == "completed" and not (task_run.output or {}).get("final_message"):
        current_app.send_task(DEFERRED_RESUME_TASK, args=[str(task_run.id)], countdown=FINAL_MESSAGE_GRACE_SECONDS)
        return
    _emit(task_run, origin_key, status)


def resume_workflow_step_after_final_message(task_run: TaskRun) -> None:
    """Wake the step once the relay has persisted the agent's final message on a run that is
    already terminal. A run still in progress is woken by its terminal transition instead."""
    status = _STATUS_BY_RUN_STATUS.get(task_run.status)
    if status is None:
        return
    origin_key = _workflow_origin_key(task_run)
    if origin_key is None:
        return
    _emit(task_run, origin_key, status)


def resume_workflow_step_for_run_id(run_id: str | UUID) -> None:
    """Deferred wake: re-reads the run so a final message that landed in the meantime is carried."""
    runs = TaskRun.objects.select_related("task")
    task_run = runs.filter(id=run_id).first()  # nosemgrep: celery-task-team-scope-audit
    if task_run is None:
        return
    resume_workflow_step_for_run(task_run, wait_for_final_message=False)
