from uuid import UUID

from django.db import transaction

from products.tasks.backend.facade import contracts
from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.visibility import task_control_q


def retry_failed_task(
    task_id: str | UUID, team_id: int, user_id: int, *, validated_data: dict
) -> contracts.TaskRunResult | None:
    """Retry a failed task once, or reuse the run another retry already started.

    The task row lock serializes callers that observed the same failed run. Standard run
    creation applies ownership checks and defers workflow dispatch until the lock commits.
    """
    from products.tasks.backend.facade import api  # noqa: PLC0415 -- api re-exports this operation

    with transaction.atomic():
        task = (
            Task.objects.select_for_update(of=("self",))
            .filter(id=task_id, team_id=team_id, deleted=False)
            .filter(task_control_q(user_id))
            .first()
        )
        if task is None:
            return None
        latest = task.latest_run
        if latest is not None and latest.status == TaskRun.Status.FAILED:
            return api.run_task(task.id, team_id, user_id, validated_data=validated_data)
        return contracts.TaskRunResult(task=api.get_task_detail(task.id, team_id, user_id))
