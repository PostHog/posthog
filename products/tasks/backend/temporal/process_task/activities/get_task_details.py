from dataclasses import dataclass
from typing import cast

from asgiref.sync import sync_to_async
from temporalio import activity

from products.tasks.backend.models import Task


@dataclass
class TaskDetails:
    task_id: str
    team_id: int
    user_id: int
    github_integration_id: int
    repository: str


@activity.defn
async def get_task_details(task_id: str) -> TaskDetails:
    """Get task details from the database."""
    task = await sync_to_async(Task.objects.select_related("integration").get)(id=task_id)

    task = cast(Task, task)

    return TaskDetails(
        task_id=str(task.id),
        team_id=task.team_id,
        user_id=task.created_by_id,
        github_integration_id=task.integration_id,
        repository=task.integration.config.get("repository", ""),
    )
