from collections.abc import Callable, Iterable
from uuid import UUID

from django.db.models.signals import post_save

from products.tasks.backend.models import Task, TaskRun

# Re-exported here so a startup receiver can read it without importing the request facade.
TaskOriginProduct = Task.OriginProduct


def connect_task_run_post_save(receiver: Callable[..., None], *, dispatch_uid: str) -> None:
    post_save.connect(receiver, sender=TaskRun, dispatch_uid=dispatch_uid)


# A guard gets (task_id, team_id, user_id) before a run starts and returns a message to refuse it with, or None.
TaskRunStartGuard = Callable[[str, int, int | None], str | None]
_task_run_start_guards: dict[str, TaskRunStartGuard] = {}


def register_task_run_start_guard(guard: TaskRunStartGuard, *, name: str) -> None:
    _task_run_start_guards[name] = guard


def task_run_start_refusal(task_id: str, team_id: int, user_id: int | None) -> str | None:
    """The first registered guard's reason to refuse starting a run for this task, if any."""
    for guard in _task_run_start_guards.values():
        refusal = guard(task_id, team_id, user_id)
        if refusal is not None:
            return refusal
    return None


# An exclusion gets (team_id, user_id) and returns the ids of tasks this user must not see.
TaskReadExclusion = Callable[[int, int | None], Iterable[UUID]]
_task_read_exclusions: dict[str, TaskReadExclusion] = {}


def register_task_read_exclusion(exclusion: TaskReadExclusion, *, name: str) -> None:
    _task_read_exclusions[name] = exclusion


def hidden_task_ids(team_id: int, user_id: int | None) -> set[UUID]:
    """Every registered product's task ids to hide from this user."""
    return {task_id for exclusion in _task_read_exclusions.values() for task_id in exclusion(team_id, user_id)}
