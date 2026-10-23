from datetime import datetime
from uuid import UUID

from django.core.cache import BaseCache

from products.tasks.backend import push_dispatcher
from products.tasks.backend.models import TaskArtifact, TaskPresence, TaskRun
from products.tasks.backend.push_dispatcher import notify_task_pull_request_outcome
from products.tasks.backend.redis import get_tasks_cache

__all__ = [
    "create_task_artifact",
    "create_task_presence",
    "notify_task_pull_request_outcome",
    "notify_task_run_awaiting_input",
    "notify_task_run_cancelled",
    "notify_task_run_completed",
    "notify_task_run_failed",
    "notify_task_run_turn_completed",
    "tasks_cache",
]


def create_task_artifact(*, team_id: int, task_id: UUID, task_run_id: UUID, name: str) -> UUID:
    return (
        TaskArtifact.objects.for_team(team_id)
        .create(
            team_id=team_id,
            task_id=task_id,
            task_run_id=task_run_id,
            name=name,
            artifact_type=TaskArtifact.ArtifactType.DOCUMENT,
            adapter=TaskArtifact.Adapter.DOCUMENT_CONNECTOR,
        )
        .id
    )


def create_task_presence(
    *, team_id: int, task_id: UUID, user_id: int, push_token_id: UUID, expires_at: datetime
) -> UUID:
    return (
        TaskPresence.objects.for_team(team_id)
        .create(
            team_id=team_id,
            task_id=task_id,
            user_id=user_id,
            push_token_id=push_token_id,
            expires_at=expires_at,
        )
        .id
    )


def _task_run(task_run_id: str, team_id: int) -> TaskRun:
    return TaskRun.objects.select_related("task").get(id=task_run_id, team_id=team_id)


def notify_task_run_completed(*, task_run_id: str, team_id: int) -> None:
    push_dispatcher.notify_task_run_completed(_task_run(task_run_id, team_id))


def notify_task_run_failed(*, task_run_id: str, team_id: int) -> None:
    push_dispatcher.notify_task_run_failed(_task_run(task_run_id, team_id))


def notify_task_run_cancelled(*, task_run_id: str, team_id: int) -> None:
    push_dispatcher.notify_task_run_cancelled(_task_run(task_run_id, team_id))


def notify_task_run_awaiting_input(*, task_run_id: str, team_id: int) -> None:
    push_dispatcher.notify_task_run_awaiting_input(_task_run(task_run_id, team_id))


def notify_task_run_turn_completed(*, task_run_id: str, team_id: int) -> None:
    push_dispatcher.notify_task_run_turn_completed(_task_run(task_run_id, team_id))


def tasks_cache() -> BaseCache:
    return get_tasks_cache()
