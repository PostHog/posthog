from dataclasses import dataclass

from django.core.exceptions import ObjectDoesNotExist

from temporalio import activity

from posthog.temporal.common.utils import asyncify

from products.tasks.backend.models import TaskRun
from products.tasks.backend.temporal.exceptions import TaskInvalidStateError, TaskNotFoundError
from products.tasks.backend.temporal.observability import emit_agent_log, log_with_activity_context


@dataclass
class GetTaskProcessingContextInput:
    run_id: str
    create_pr: bool = True


@dataclass
class TaskProcessingContext:
    """
    Serializable context object passed to all activities in the task processing workflow.
    Contains all the information needed to execute activities and emit logs.
    """

    task_id: str
    run_id: str
    team_id: int
    github_integration_id: int
    repository: str
    distinct_id: str
    create_pr: bool = True

    def to_log_context(self) -> dict:
        """Return a dict suitable for structured logging."""
        return {
            "task_id": self.task_id,
            "run_id": self.run_id,
            "team_id": self.team_id,
            "repository": self.repository,
            "distinct_id": self.distinct_id,
        }


@activity.defn
@asyncify
def get_task_processing_context(input: GetTaskProcessingContextInput) -> TaskProcessingContext:
    """Fetch task details and create the processing context for the workflow."""
    run_id = input.run_id
    log_with_activity_context("Fetching task processing context", run_id=run_id)

    try:
        task_run = TaskRun.objects.select_related("task__created_by").get(id=run_id)
    except ObjectDoesNotExist as e:
        raise TaskNotFoundError(f"TaskRun {run_id} not found", {"run_id": run_id}, cause=e)

    emit_agent_log(run_id, "info", "Fetching task details")

    task = task_run.task

    if not task.github_integration_id:
        raise TaskInvalidStateError(
            f"Task {task.id} has no GitHub integration",
            {"task_id": str(task.id), "run_id": run_id},
            cause=RuntimeError(f"Task {task.id} missing github_integration_id"),
        )

    if not task.repository:
        raise TaskInvalidStateError(
            f"Task {task.id} has no repository configured",
            {"task_id": str(task.id), "run_id": run_id},
            cause=RuntimeError(f"Task {task.id} missing repository"),
        )

    repository_full_name = task.repository
    if not repository_full_name:
        raise TaskInvalidStateError(
            f"Task {task.id} repository missing value",
            {"task_id": str(task.id), "run_id": run_id},
            cause=RuntimeError(f"Task {task.id} repository field is empty"),
        )

    if not task.created_by:
        raise TaskInvalidStateError(
            f"Task {task.id} has no created_by user",
            {"task_id": str(task.id), "run_id": run_id},
            cause=RuntimeError(f"Task {task.id} missing created_by field"),
        )

    assert task.created_by is not None

    distinct_id = task.created_by.distinct_id or "process_task_workflow"

    log_with_activity_context(
        "Task processing context created",
        task_id=str(task.id),
        run_id=run_id,
        team_id=task.team_id,
        repository=repository_full_name,
        distinct_id=distinct_id,
    )

    return TaskProcessingContext(
        task_id=str(task.id),
        run_id=run_id,
        team_id=task.team_id,
        github_integration_id=task.github_integration_id,
        repository=repository_full_name,
        distinct_id=distinct_id,
        create_pr=input.create_pr,
    )
