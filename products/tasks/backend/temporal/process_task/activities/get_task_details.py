from dataclasses import dataclass

from django.core.exceptions import ObjectDoesNotExist

from temporalio import activity

from posthog.temporal.common.utils import asyncify

from products.tasks.backend.models import Task
from products.tasks.backend.temporal.exceptions import TaskInvalidStateError, TaskNotFoundError
from products.tasks.backend.temporal.observability import log_with_activity_context


@dataclass
class TaskDetails:
    task_id: str
    team_id: int
    github_integration_id: int
    repository: str
    distinct_id: str


@activity.defn
@asyncify
def get_task_details(task_id: str) -> TaskDetails:
    log_with_activity_context("Fetching task details", task_id=task_id)

    try:
        task = Task.objects.select_related("created_by").get(id=task_id)
    except ObjectDoesNotExist:
        raise TaskNotFoundError(f"Task {task_id} not found", {"task_id": task_id})

    if not task.github_integration_id:
        raise TaskInvalidStateError(
            f"Task {task_id} has no GitHub integration",
            {"task_id": task_id},
        )

    if not task.primary_repository:
        raise TaskInvalidStateError(
            f"Task {task_id} has no primary repository configured",
            {"task_id": task_id},
        )

    repository_full_name = task.primary_repository.get("full_name")
    if not repository_full_name:
        raise TaskInvalidStateError(
            f"Task {task_id} primary repository missing full_name",
            {"task_id": task_id},
        )

    if not task.created_by:
        raise TaskInvalidStateError(
            f"Task {task_id} has no created_by user",
            {"task_id": task_id},
        )

    assert task.created_by is not None

    distinct_id = task.created_by.distinct_id or "process_task_workflow"

    log_with_activity_context(
        "Task details retrieved successfully",
        task_id=task_id,
        team_id=task.team_id,
        repository=repository_full_name,
        distinct_id=distinct_id,
    )

    return TaskDetails(
        task_id=str(task.id),
        team_id=task.team_id,
        github_integration_id=task.github_integration_id,
        repository=repository_full_name,
        distinct_id=distinct_id,
    )
