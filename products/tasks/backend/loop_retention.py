"""Retention sweeps for loop bookkeeping. See products/tasks/docs/LOOPS.md (Run: Cleanup).

Keeps the newest 200 tasks per loop and soft-deletes the rest (skipping any task with a
non-terminal TaskRun), and prunes old LoopFire dedup rows so that table doesn't grow unbounded.
"""

from datetime import timedelta
from uuid import UUID

from django.db.models import F, Window
from django.db.models.functions import RowNumber
from django.utils import timezone as django_timezone

import structlog
from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded

from posthog.exceptions_capture import capture_exception
from posthog.ph_client import ph_scoped_capture
from posthog.scoping_audit import skip_team_scope_audit

from products.tasks.backend.models import LoopFire, Task, TaskRun

logger = structlog.get_logger(__name__)

LOOP_TASK_RETENTION_LIMIT = 200
# Well beyond the 24h rate-cap window and any realistic fire retry/redelivery window, so pruning
# never removes a row still needed for dedup or rate-capping.
LOOP_FIRE_RETENTION_DAYS = 7

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
    # ph_scoped_capture: soft_delete emits task_deleted, and the global analytics client
    # silently drops events in Celery workers.
    with ph_scoped_capture() as capture:
        for task in Task.objects.filter(  # nosemgrep: celery-task-team-scope-audit
            id__in=deletable_task_ids, deleted=False
        ):
            try:
                task.soft_delete(capture_fn=capture)
                deleted_count += 1
            except SoftTimeLimitExceeded:
                raise
            except Exception as exc:
                # One bad row must not abort the whole sweep (and block pruning for every later day);
                # capture and move on, mirroring kill_stale_queued_task_runs.
                capture_exception(exc)
                logger.exception("loop_retention.task_soft_delete_failed", task_id=str(task.id))
    return deleted_count


def _stale_loop_task_ids(retention_limit: int) -> list[UUID]:
    """Ids of loop-spawned tasks beyond `retention_limit`, ranked newest-first per loop.

    Ranked server-side with a window function so the sweep only ever materializes the stale
    tail, not every loop-spawned task across every team.
    """
    ranked = Task.objects.filter(loop__isnull=False, deleted=False).annotate(  # nosemgrep: celery-task-team-scope-audit
        newest_first_rank=Window(
            RowNumber(), partition_by=[F("loop_id")], order_by=[F("created_at").desc(), F("id").desc()]
        )
    )
    return list(ranked.filter(newest_first_rank__gt=retention_limit).values_list("id", flat=True))


def prune_loop_fire_records(retention_days: int = LOOP_FIRE_RETENTION_DAYS) -> int:
    """Hard-delete LoopFire dedup rows older than the retention window. Returns the count deleted.

    Cross-team janitor sweep. LoopFire is a pure dedup/rate-cap ledger, so rows outside every
    window that reads them (24h rate cap, retry/redelivery) carry no value.
    """
    cutoff = django_timezone.now() - timedelta(days=retention_days)
    deleted, _ = LoopFire.objects.unscoped().filter(created_at__lt=cutoff).delete()
    return deleted


@shared_task(ignore_result=True, soft_time_limit=110, time_limit=170)
@skip_team_scope_audit
def sweep_loop_task_retention_task() -> None:
    # Prune the LoopFire ledger even if the task sweep raises: the two are independent janitors and a
    # failure in one must not permanently starve the other.
    deleted_count = 0
    try:
        deleted_count = sweep_loop_task_retention()
    except SoftTimeLimitExceeded:
        raise
    except Exception as exc:
        capture_exception(exc)
        logger.exception("loop_retention.task_sweep_failed")
    pruned_fires = prune_loop_fire_records()
    logger.info("loop_retention.swept", deleted_count=deleted_count, pruned_fires=pruned_fires)
