"""Ad-hoc Temporal activity that prunes expired snapshots for a full-refresh-append schema.

Snapshot pruning normally happens at the tail of every sync (see `prune_snapshots_if_needed`). Between
syncs — or when a schema is paused, failing, or its retention was tightened — snapshots that have aged
out of the retention window linger ("orphaned"). This activity runs the same prune on demand, without a
source re-pull, so an operator can reclaim that storage from the Django admin. It no-ops when a sync is
already running so it never races the pipeline's own writer against the live Delta table.
"""

import dataclasses

from django.db import close_old_connections

from asgiref.sync import async_to_sync
from structlog.contextvars import bind_contextvars
from temporalio import activity

from posthog.temporal.common.logger import get_logger

from products.data_warehouse.backend.facade.api import unpause_external_data_schedule
from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.delta_table_helper import (
    DeltaTableHelper,
)

LOGGER = get_logger(__name__)


@dataclasses.dataclass
class PruneSnapshotsWorkflowInputs:
    team_id: int
    schema_id: str
    unpause_schedule_after: bool = False


@dataclasses.dataclass
class PruneSnapshotsActivityInputs:
    team_id: int
    schema_id: str


@dataclasses.dataclass
class UnpauseScheduleActivityInputs:
    schema_id: str


@activity.defn
def prune_snapshots_activity(inputs: PruneSnapshotsActivityInputs) -> int:
    """Prune expired snapshots for one schema, returning the number of snapshots deleted.

    Returns 0 (a no-op) when the schema isn't in append mode, has never synced, or a sync is currently
    running — pruning the live table under a concurrent sync could vacuum files that sync still needs.
    """
    bind_contextvars(team_id=inputs.team_id, schema_id=inputs.schema_id)
    close_old_connections()
    logger = LOGGER.bind()

    try:
        schema = ExternalDataSchema.objects.get(id=inputs.schema_id, team_id=inputs.team_id)
    except ExternalDataSchema.DoesNotExist:
        logger.warning("prune_snapshots_activity: schema not found")
        return 0

    if not schema.is_full_refresh_append:
        logger.info("prune_snapshots_activity: schema is not full-refresh-append, nothing to prune")
        return 0

    if ExternalDataJob.objects.filter(schema_id=schema.id, status=ExternalDataJob.Status.RUNNING).exists():
        logger.warning("prune_snapshots_activity: a sync is running, skipping prune to avoid racing the pipeline")
        return 0

    job = ExternalDataJob.objects.filter(schema_id=schema.id).order_by("-created_at").first()
    if job is None:
        logger.info("prune_snapshots_activity: schema has never synced, nothing to prune")
        return 0

    helper = DeltaTableHelper(resource_name=schema.name, job=job, logger=logger)
    pruned = async_to_sync(helper.prune_snapshots)(schema.snapshot_retention_mode, schema.snapshot_retention_value)
    logger.info("prune_snapshots_activity: pruned snapshots", pruned=pruned)
    return pruned


@activity.defn
def unpause_schedule_activity(inputs: UnpauseScheduleActivityInputs) -> None:
    """Best-effort unpause of a schema's sync schedule, run after an admin-triggered prune completes."""
    bind_contextvars(schema_id=inputs.schema_id)
    close_old_connections()
    try:
        unpause_external_data_schedule(inputs.schema_id)
    except Exception:
        LOGGER.bind().exception("unpause_schedule_activity: failed to unpause schedule")
