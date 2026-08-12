"""Reconciliation sweep for loop trigger schedules. See products/tasks/docs/LOOPS.md
(Lifecycle and reconciliation).

Schedule sync to Temporal is best-effort: `sync_loop_trigger_schedule` records `pending` or
`failed` on the trigger instead of raising, so a transient Temporal outage during a create or
edit leaves a schedule trigger whose Temporal Schedule was never created or updated. This sweep
re-drives those rows so a trigger never strands unsynced.
"""

import structlog
from celery import shared_task

from posthog.scoping_audit import skip_team_scope_audit

from products.tasks.backend.loop_service import sync_loop_trigger_schedule
from products.tasks.backend.models import LoopTrigger

logger = structlog.get_logger(__name__)

_UNSYNCED_STATUSES = (LoopTrigger.ScheduleSyncStatus.PENDING, LoopTrigger.ScheduleSyncStatus.FAILED)
# After a Temporal outage the whole cross-team backlog goes unsynced at once; each re-sync is a
# Temporal round trip and the Celery task has a 110s soft limit, so cap the batch per sweep and
# let the 10-minute cadence drain the rest.
_RECONCILE_BATCH_SIZE = 200


def reconcile_loop_trigger_schedules() -> int:
    """Re-sync schedule triggers stuck in `pending`/`failed`, oldest first, capped per sweep.
    Returns the count re-synced.

    Cross-team janitor sweep, mirroring `sweep_loop_task_retention`. `sync_loop_trigger_schedule`
    is idempotent and swallows Temporal errors (re-recording `failed`), so a still-down Temporal
    just leaves the row for the next sweep rather than raising.
    """
    triggers = list(
        LoopTrigger.objects.unscoped()
        .filter(
            type=LoopTrigger.TriggerType.SCHEDULE,
            schedule_sync_status__in=_UNSYNCED_STATUSES,
            completed_at__isnull=True,
            # A soft-deleted loop's schedule was torn down on delete; never recreate it here.
            loop__deleted=False,
        )
        .select_related("loop")
        .order_by("updated_at")[:_RECONCILE_BATCH_SIZE]
    )
    for trigger in triggers:
        sync_loop_trigger_schedule(trigger)
    return len(triggers)


@shared_task(ignore_result=True, soft_time_limit=110, time_limit=170)
@skip_team_scope_audit
def reconcile_loop_trigger_schedules_task() -> None:
    reconciled_count = reconcile_loop_trigger_schedules()
    logger.info("loop_reconciliation.swept", reconciled_count=reconciled_count)
