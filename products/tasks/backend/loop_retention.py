"""Retention sweep for loop-spawned tasks. See products/tasks/docs/LOOPS.md (Run: Cleanup).

Keeps the newest 200 tasks per loop and soft-deletes the rest, skipping any task
with a non-terminal TaskRun regardless of age.
"""

from uuid import UUID

import structlog
from celery import shared_task

from posthog.scoping_audit import skip_team_scope_audit

from products.tasks.backend.models import Task, TaskRun

logger = structlog.get_logger(__name__)

LOOP_TASK_RETENTION_LIMIT = 200

_NON_TERMINAL_TASK_RUN_STATUSES = (TaskRun.Status.NOT_STARTED, TaskRun.Status.QUEUED, TaskRun.Status.IN_PROGRESS)


def sweep_loop_task_retention(retention_limit: int = LOOP_TASK_RETENTION_LIMIT) -> int:
    """Soft-delete loop-spawned tasks beyond the newest `retention_limit` per loop.

    Returns the number of tasks soft-deleted. Intentionally cross-team: this is a
    janitor sweep with no team context, mirroring `kill_stale_queued_task_runs`.
    """
    stale_task_ids = _stale_loop_task_ids(retention_limit)
    if not stale_task_ids:
        return 0

    non_terminal_task_ids = set(
        TaskRun.objects.filter(  # nosemgrep: celery-task-team-scope-audit
            task_id__in=stale_task_ids, status__in=_NON_TERMINAL_TASK_RUN_STATUSES
        ).values_list("task_id", flat=True)
    )
    deletable_task_ids = [task_id for task_id in stale_task_ids if task_id not in non_terminal_task_ids]
    if not deletable_task_ids:
        return 0

    deleted_count = 0
    for task in Task.objects.filter(  # nosemgrep: celery-task-team-scope-audit
        id__in=deletable_task_ids, deleted=False
    ):
        task.soft_delete()
        deleted_count += 1
    return deleted_count


def _stale_loop_task_ids(retention_limit: int) -> list[UUID]:
    """Ids of loop-spawned tasks beyond `retention_limit`, ranked newest-first per loop.

    Ordering by loop then -created_at at the DB layer means each loop's tasks arrive
    already newest-first and contiguous, so no re-sort is needed while grouping.
    """
    tasks_by_loop: dict[UUID, list[UUID]] = {}
    for task_id, loop_id in (
        Task.objects.filter(loop__isnull=False, deleted=False)  # nosemgrep: celery-task-team-scope-audit
        .order_by("loop_id", "-created_at", "-id")
        .values_list("id", "loop_id")
    ):
        tasks_by_loop.setdefault(loop_id, []).append(task_id)

    stale_task_ids: list[UUID] = []
    for task_ids in tasks_by_loop.values():
        stale_task_ids.extend(task_ids[retention_limit:])
    return stale_task_ids


@shared_task(ignore_result=True, soft_time_limit=110, time_limit=170)
@skip_team_scope_audit
def sweep_loop_task_retention_task() -> None:
    deleted_count = sweep_loop_task_retention()
    logger.info("loop_retention.swept", deleted_count=deleted_count)
