from typing import Any

from products.tasks.backend.models import Task, TaskRun
from products.workflows.backend.services.step_resume import WorkflowStepResumeStatus, resume_workflow_step

_STATUS_BY_RUN_STATUS: dict[str, WorkflowStepResumeStatus] = {
    TaskRun.Status.COMPLETED: "completed",
    TaskRun.Status.FAILED: "failed",
    TaskRun.Status.CANCELLED: "cancelled",
}


def _result_for_run(task_run: TaskRun) -> dict[str, Any]:
    output = task_run.output or {}
    return {
        "run_id": str(task_run.id),
        "final_message": output.get("final_message"),
        "pr_urls": output.get("pr_urls") or ([output["pr_url"]] if output.get("pr_url") else None),
        "error_message": task_run.error_message,
    }


def resume_workflow_step_for_run(task_run: TaskRun) -> None:
    """Wake the workflow step waiting on this run, if a workflow started it. Call once, on the
    actual transition into a terminal status; a repeat is harmless but wasted."""
    status = _STATUS_BY_RUN_STATUS.get(task_run.status)
    if status is None:
        return
    task = task_run.task
    if task.origin_product != Task.OriginProduct.WORKFLOW or not task.origin_key:
        return
    resume_workflow_step(
        team_id=task.team_id, origin_key=task.origin_key, status=status, result=_result_for_run(task_run)
    )
