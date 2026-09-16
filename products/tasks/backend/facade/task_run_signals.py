from collections.abc import Callable

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
