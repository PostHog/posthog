from typing import Any
from uuid import UUID

from celery import current_app
from jsonschema import ValidationError, validate

from posthog.cdp.workflow_step_resume import WorkflowStepResumeStatus, resume_workflow_step

from products.tasks.backend.models import Task, TaskRun

_STATUS_BY_RUN_STATUS: dict[str, WorkflowStepResumeStatus] = {
    TaskRun.Status.COMPLETED: "completed",
    TaskRun.Status.FAILED: "failed",
    TaskRun.Status.CANCELLED: "cancelled",
}

# The `finish` tool completes a run seconds before the relay saves its final message.
FINAL_MESSAGE_GRACE_SECONDS = 30

DEFERRED_RESUME_TASK = "products.tasks.backend.tasks.tasks.resume_workflow_step_for_run_deferred"


# Keys the tasks product writes into `TaskRun.output` next to the agent's structured output.
_RUN_OUTPUT_BOOKKEEPING_KEYS = frozenset({"final_message", "pr_url", "pr_urls", "commit_push"})


def _structured_output_for_run(task_run: TaskRun) -> tuple[dict[str, Any] | None, list[str]]:
    """The agent's schema-shaped output and the warnings a mismatch produces.

    The structured output sits at the top level of `run.output`, next to bookkeeping the tasks
    product writes there. The schema's `properties` say which keys are the agent's; a schema
    without `properties` falls back to dropping the known bookkeeping keys.
    """
    schema = task_run.task.json_schema
    if not schema:
        return None, []
    output = task_run.output if isinstance(task_run.output, dict) else {}
    properties = schema.get("properties")
    if isinstance(properties, dict):
        structured = {key: output[key] for key in properties if key in output}
    else:
        structured = {key: value for key, value in output.items() if key not in _RUN_OUTPUT_BOOKKEEPING_KEYS}
    if task_run.status != TaskRun.Status.COMPLETED:
        return structured, []
    try:
        validate(instance=structured, schema=schema)
    except ValidationError as error:
        return structured, [f"The task finished, but its output does not match the output variables: {error.message}"]
    return structured, []


def _result_for_run(task_run: TaskRun) -> dict[str, Any]:
    output = task_run.output or {}
    structured, warnings = _structured_output_for_run(task_run)
    # `output` goes first: the byte cap trims later keys first, and prose can lose its tail while
    # a structured field cannot.
    return {
        "run_id": str(task_run.id),
        "output": structured,
        "warnings": warnings or None,
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
    """Wake the step waiting on this run; a completed run without its final message defers the wake."""
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
    """Wake the step once the final message lands on an already terminal run."""
    status = _STATUS_BY_RUN_STATUS.get(task_run.status)
    if status is None:
        return
    origin_key = _workflow_origin_key(task_run)
    if origin_key is None:
        return
    _emit(task_run, origin_key, status)


def resume_workflow_step_for_run_id(run_id: str | UUID) -> None:
    runs = TaskRun.objects.select_related("task")
    task_run = runs.filter(id=run_id).first()  # nosemgrep: celery-task-team-scope-audit
    if task_run is None:
        return
    resume_workflow_step_for_run(task_run, wait_for_final_message=False)
