from dataclasses import dataclass

from django.core.exceptions import ObjectDoesNotExist

from temporalio import activity

from posthog.temporal.common.utils import asyncify

from products.tasks.backend.models import TaskRun
from products.tasks.backend.temporal.exceptions import TaskInvalidStateError, TaskNotFoundError
from products.tasks.backend.temporal.observability import log_with_activity_context


@dataclass
class TaskDetails:
    task_id: str
    run_id: str
    team_id: int
    github_integration_id: int
    repository: str
    distinct_id: str


@activity.defn
@asyncify
def get_task_details(run_id: str) -> TaskDetails:
    log_with_activity_context("Fetching task details", run_id=run_id)

    try:
        task_run = TaskRun.objects.select_related("task__created_by").get(id=run_id)
    except ObjectDoesNotExist as e:
        raise TaskNotFoundError(f"TaskRun {run_id} not found", {"run_id": run_id}, cause=e)

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
        "Task details retrieved successfully",
        task_id=str(task.id),
        run_id=run_id,
        team_id=task.team_id,
        repository=repository_full_name,
        distinct_id=distinct_id,
    )

    return TaskDetails(
        task_id=str(task.id),
        run_id=run_id,
        team_id=task.team_id,
        github_integration_id=task.github_integration_id,
        repository=repository_full_name,
        distinct_id=distinct_id,
    )
