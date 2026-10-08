from typing import Any
from uuid import UUID

from celery import current_app

from posthog.cdp.workflow_step_resume import (
    RESULT_BYTE_CAP,
    WorkflowStepResumeStatus,
    cap_value,
    emit_workflow_step_resume,
)

from products.tasks.backend.logic.services.workflow_task_output import RUN_OUTPUT_RESERVED_KEYS
from products.tasks.backend.models import Task, TaskRun

_STATUS_BY_RUN_STATUS: dict[str, WorkflowStepResumeStatus] = {
    TaskRun.Status.COMPLETED: "completed",
    TaskRun.Status.FAILED: "failed",
    TaskRun.Status.CANCELLED: "cancelled",
}

# The `finish` tool completes a run seconds before the relay saves its final message.
FINAL_MESSAGE_GRACE_SECONDS = 30

DEFERRED_RESUME_TASK = "products.tasks.backend.tasks.tasks.resume_workflow_step_for_run_deferred"


def _validation_warnings(schema: dict[str, Any], structured: dict[str, Any]) -> list[str]:
    # Deferred: jsonschema is heavy and only a run with a schema needs it.
    from jsonschema import Draft202012Validator, ValidationError  # noqa: PLC0415
    from referencing import Registry  # noqa: PLC0415

    try:
        # An empty registry fails closed on any reference the schema does not carry itself.
        Draft202012Validator(schema, registry=Registry()).validate(structured)
    except ValidationError as error:
        return [f"The task finished, but its output does not match the output variables: {error.message}"]
    except Exception as error:
        return [f"The task finished, but its output could not be checked against the output variables: {error}"]
    return []


def _cut_warnings(structured: dict[str, Any]) -> list[str]:
    capped = cap_value(structured, RESULT_BYTE_CAP)
    cut = [name for name, value in structured.items() if capped.get(name) != value]
    if not cut:
        return []
    return [f"The task's output was cut to fit the step result: {', '.join(cut)}"]


def _structured_output_for_run(task_run: TaskRun) -> tuple[dict[str, Any] | None, list[str]]:
    """The agent's fields from `run.output` and the warnings the step should log.

    The agent's fields sit at the top level of `run.output`, next to bookkeeping the tasks
    product writes there under reserved names.
    """
    schema = task_run.task.json_schema
    if not schema:
        return None, []
    output = task_run.output if isinstance(task_run.output, dict) else {}
    structured = {key: value for key, value in output.items() if key not in RUN_OUTPUT_RESERVED_KEYS}
    if task_run.status != TaskRun.Status.COMPLETED:
        return structured, []
    return structured, _validation_warnings(schema, structured) + _cut_warnings(structured)


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
    emit_workflow_step_resume(
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
