"""The second job row a `both` schema's run opens for its history table.

Kept apart from the pipeline and the source manager so both can retire one without importing
each other.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.db import transaction
from django.utils import timezone

if TYPE_CHECKING:
    from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema

# On the schema's own job row: the companion job ids this run opened, so the listing proof can
# check them by primary key rather than by an unindexed JSON predicate over the schema's history.
COMPANION_JOB_IDS_KEY = "cdc_companion_job_ids"

COMPANION_RETIRED_ERROR = "Extraction ended before this table's changes were written"


def retire_companion_job(job_id: str) -> None:
    """Take one Running companion job terminal, touching nothing else.

    Written straight onto the row, as the legacy CDC path retires its own companions: the shared
    status helper would repaint the customer's schema FAILED and fire a failure digest for a row
    that is not the schema's own.
    """
    from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob

    ExternalDataJob.objects.filter(id=job_id, status=ExternalDataJob.Status.RUNNING).update(
        status=ExternalDataJob.Status.FAILED,
        latest_error=COMPANION_RETIRED_ERROR,
        finished_at=timezone.now(),
    )


def retire_orphaned_companions(schema: ExternalDataSchema) -> list[str]:
    """Retire this schema's Running companion jobs that no run owns any more.

    A companion is opened by the run that needs it, and that run's `finally` retires it when
    extraction fails — but a hard kill (OOM, SIGKILL) runs no `finally`. Nothing else knows the
    row exists: the loader completes a job only on its final batch, which a dead run never sent;
    the stranded sweep finds runs by their non-terminal batches, and the loader drains those to
    `succeeded`. Left alone the row stays Running for good and blocks every flip and rollback.

    Safe to call once `has_batches_in_flight` is false: no batch of any earlier run can still be
    executing, so nothing is mid-write on a job this retires. That includes a companion an
    earlier attempt of the caller's own job opened — the caller opens its own lazily, after
    this runs, so any Running companion at this point belongs to a run that is gone.
    """
    from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob

    orphans = list(
        ExternalDataJob.objects.filter(
            team_id=schema.team_id,
            pipeline_id=schema.source_id,
            schema_id=schema.id,
            status=ExternalDataJob.Status.RUNNING,
            schema_snapshot__companion_of__isnull=False,
        ).values_list("id", flat=True)
    )
    for job_id in orphans:
        retire_companion_job(str(job_id))
    return [str(j) for j in orphans]


def record_companion_job(parent_job_id: str, team_id: int, companion_job_id: str, *, first_of_attempt: bool) -> None:
    """Add a companion's id to its parent's row, so the parent's completion can vouch for it.

    A new attempt starts the list over: an earlier attempt's companion was retired or drained by
    the time this attempt reads, and leaving it listed would have the listing proof reject this
    run for good.

    Under the row lock, like every writer of this snapshot: the listing stamp shares the JSON,
    and an attempt still alive past its timeout can write it between this read and this write.
    """
    from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob

    with transaction.atomic():
        parent = ExternalDataJob.objects.select_for_update().get(id=parent_job_id, team_id=team_id)
        snapshot = dict(parent.schema_snapshot or {})
        earlier = [] if first_of_attempt else snapshot.get(COMPANION_JOB_IDS_KEY, [])
        snapshot[COMPANION_JOB_IDS_KEY] = [*earlier, companion_job_id]
        ExternalDataJob.objects.filter(id=parent.id).update(schema_snapshot=snapshot)
