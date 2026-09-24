"""Whether the S3 change buffer carries a CDC table's snapshot.

The buffer carries a snapshot when it holds every change since the table's buffer was last
emptied. Replaying an unbroken run of changes over the snapshot, in order, converges on the
source's state even when some of them predate the snapshot, so the hand-over deletes nothing. A
gap breaks that: an older change replayed without the ones after it leaves a stale row.

A marker on the schema records that the buffer carries the current snapshot, and the hand-over
reads it. Kept free of the pipeline imports, so the schema API can call it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from temporalio.service import RPCError, RPCStatusCode

from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import CDC_SNAPSHOT_LANE_KEY
from products.warehouse_sources.backend.temporal.data_imports.cdc.naming import CDC_EXTRACTION_WORKFLOW_ID_PREFIX
from products.warehouse_sources.backend.temporal.data_imports.cdc.types import parse_ingest_mode

if TYPE_CHECKING:
    from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema

BUFFER_LANE = "buffer"


def snapshot_in_buffer(schema: ExternalDataSchema) -> bool:
    """Whether the buffer carries this schema's current snapshot."""
    return (schema.sync_type_config or {}).get(CDC_SNAPSHOT_LANE_KEY) == BUFFER_LANE


def resnapshot_stays_in_buffer(schema: ExternalDataSchema) -> bool:
    """Whether a reset of this schema to snapshot keeps its changes in the buffer.

    True for a table whose buffer already holds an unbroken run of its changes: a streaming table on
    a buffered source with no deferred runs left, or one already snapshotting there. A capture run in
    progress keeps adding to that buffer. Any other table is started by capture, which first empties
    the buffer, because files from before a gap in capture must not be replayed. A source capture
    has not converted yet is one such case: its buffer holds copies of changes the legacy lane
    already delivered.
    """
    if snapshot_in_buffer(schema):
        return True
    return (
        parse_ingest_mode(schema.source.job_inputs) == "buffered"
        and schema.cdc_mode == "streaming"
        and not (schema.sync_type_config or {}).get("cdc_deferred_runs")
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
