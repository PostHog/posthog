"""Which lane carries a CDC table's changes while it takes a snapshot on a buffered source.

The buffer can carry them only when it holds every change since the table's buffer was last
emptied. Replaying an unbroken run of changes over the snapshot, in order, converges on the
source's state even when some of them predate the snapshot, so the hand-over deletes nothing. A
gap breaks that: an older change replayed without the ones after it leaves a stale row.

A marker on the schema records that the buffer carries the current snapshot. Routing and the
hand-over read the marker, never the flag, so one snapshot never splits between the buffer and
legacy deferred runs when the flag flips or its evaluation fails. Kept free of the pipeline
imports, so the schema API can call it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import posthoganalytics
from structlog.types import FilteringBoundLogger
from temporalio.service import RPCError, RPCStatusCode

from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import CDC_SNAPSHOT_LANE_KEY
from products.warehouse_sources.backend.temporal.data_imports.cdc.naming import CDC_EXTRACTION_WORKFLOW_ID_PREFIX
from products.warehouse_sources.backend.temporal.data_imports.cdc.types import parse_ingest_mode

if TYPE_CHECKING:
    from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema

# Gates starting a snapshot in the buffer. Turned on once no worker runs the previous release: an
# older worker ignores the marker, so it would defer that table's changes or purge its buffer.
BUFFERED_SNAPSHOT_FLAG = "dwh-cdc-buffered-snapshot"
BUFFER_LANE = "buffer"


def team_flag_enabled(flag: str, team_id: int, logger: FilteringBoundLogger) -> bool:
    """Evaluate a per-team warehouse flag. Never raises: a flag-service failure reads as off."""
    from posthog.models.team import Team

    try:
        team = Team.objects.get(pk=team_id)
        return bool(
            posthoganalytics.feature_enabled(
                flag,
                str(team.uuid),
                groups={"organization": str(team.organization_id), "project": str(team.id)},
                # team_id drives the release conditions (the warehouse convention for
                # per-team rollouts); the group context is passed for consistency with
                # the other warehouse flags and for org-wide kill switches.
                person_properties={"team_id": str(team.id)},
                group_properties={
                    "organization": {"id": str(team.organization_id)},
                    "project": {"id": str(team.id)},
                },
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception:
        logger.warning("cdc_flag_check_failed", flag=flag, team_id=team_id, exc_info=True)
        return False


def is_buffered_snapshot_enabled(team_id: int, logger: FilteringBoundLogger) -> bool:
    return team_flag_enabled(BUFFERED_SNAPSHOT_FLAG, team_id, logger)


def snapshot_in_buffer(schema: ExternalDataSchema) -> bool:
    """Whether the buffer carries this schema's current snapshot."""
    return (schema.sync_type_config or {}).get(CDC_SNAPSHOT_LANE_KEY) == BUFFER_LANE


def resnapshot_stays_in_buffer(schema: ExternalDataSchema, logger: FilteringBoundLogger) -> bool:
    """Whether a reset of this schema to snapshot keeps its changes in the buffer.

    True for a table whose changes already go to the buffer: a streaming table on a buffered source
    with no deferred runs left, or one already snapshotting there. Its buffer holds an unbroken run
    of changes up to the reset, and a capture run in progress keeps adding to it. Any other table is
    decided by capture, which first empties the buffer, because files from before a gap in capture
    must not be replayed.
    """
    if snapshot_in_buffer(schema):
        return True
    return (
        parse_ingest_mode(schema.source.job_inputs) == "buffered"
        and schema.cdc_mode == "streaming"
        and schema.initial_sync_complete
        and not (schema.sync_type_config or {}).get("cdc_deferred_runs")
        and is_buffered_snapshot_enabled(schema.team_id, logger)
    )


def cancel_running_sync(schema: ExternalDataSchema) -> str | None:
    """Cancel the table's running scheduled sync, so a snapshot begun before a reset cannot hand over.

    Returns the workflow id it cancelled. A workflow that already finished counts as cancelled. Any
    other failure raises, so the caller stops before it changes the table.
    """
    # Deferred: data_load.service participates in the CDC schedule<->workflow import cycle.
    from products.data_warehouse.backend.facade.api import cancel_external_data_workflow  # noqa: PLC0415

    job = (
        ExternalDataJob.objects.filter(
            team_id=schema.team_id, schema_id=schema.id, status=ExternalDataJob.Status.RUNNING
        )
        .exclude(workflow_id__isnull=True)
        .exclude(workflow_id__startswith=CDC_EXTRACTION_WORKFLOW_ID_PREFIX)
        .order_by("-created_at")
        .first()
    )
    if job is None or not job.workflow_id:
        return None
    try:
        cancel_external_data_workflow(job.workflow_id)
    except RPCError as e:
        if e.status != RPCStatusCode.NOT_FOUND:
            raise
    return job.workflow_id
