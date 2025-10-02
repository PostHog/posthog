from dataclasses import dataclass

from temporalio import activity

from posthog.temporal.common.utils import asyncify

from products.tasks.backend.models import Task


@dataclass
class TaskDetails:
    task_id: str
    team_id: int
    github_integration_id: int
    repository: str


@activity.defn
@asyncify
def get_task_details(task_id: str) -> TaskDetails:
    task = Task.objects.get(id=task_id)

    return TaskDetails(
        task_id=str(task.id),
        team_id=task.team_id,
        github_integration_id=task.github_integration_id,
        repository=task.primary_repository["full_name"],
    )
