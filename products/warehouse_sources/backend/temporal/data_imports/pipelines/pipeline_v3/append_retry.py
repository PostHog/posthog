import time
from collections.abc import Callable
from typing import Any, cast

import psycopg
import pyarrow as pa
import pyarrow.compute as pc

from posthog.settings import WAREHOUSE_SOURCES_DATABASE_URL

from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.producer import (
    connect_with_retry,
)
from products.warehouse_sources_queue.backend.core.jobs_db import BatchQueue

SETTLE_POLL_SECONDS = 5.0
# Longer than the queue's recovery sweep takes to release a batch whose loader died mid-write.
SETTLE_TIMEOUT_SECONDS = 20 * 60.0


def attempt_run_uuid(workflow_run_id: str, attempt: int) -> str:
    return f"{workflow_run_id}-a{attempt}"


def split_trailing_cursor_ties(table: pa.Table, cursor_column: str) -> tuple[pa.Table, pa.Table]:
    """Split off the rows that share the table's highest cursor value.

    The source returns rows sorted by the cursor, so these rows are the table's tail, and the next
    table can hold more rows with the same value.
    """
    cursor = table[cursor_column]
    highest = cast(pa.Scalar, pc.max(cursor))
    at_highest = cast(pa.ChunkedArray, pc.equal(cursor, highest))
    at_highest = cast(pa.ChunkedArray, pc.fill_null(at_highest, pa.scalar(False)))
    return table.filter(cast(pa.ChunkedArray, pc.invert(at_highest))), table.filter(at_highest)


def _connect_to_queue() -> psycopg.Connection[Any]:
    return connect_with_retry(WAREHOUSE_SOURCES_DATABASE_URL)


def settle_append_retry(
    schema: ExternalDataSchema,
    *,
    team_id: int,
    source_id: str,
    job_id: str,
    workflow_run_id: str | None,
    attempt: int,
    rows_ordered_by_cursor: bool,
    connect: Callable[[], psycopg.Connection[Any]] = _connect_to_queue,
    sleep: Callable[[float], None] = time.sleep,
    poll_seconds: float = SETTLE_POLL_SECONDS,
    timeout_seconds: float = SETTLE_TIMEOUT_SECONDS,
) -> int | None:
    """Make a retried append attempt continue after exactly the rows its earlier attempts loaded.

    An append writes every row it gets, and the cursor is only committed when the load finishes. So a
    retry that reads from the committed cursor appends again every row an earlier attempt loaded. This
    fences the earlier attempts, supersedes their unloaded batches, waits for any batch still being
    written, and commits the cursor of the last loaded batch.

    Returns the rows the earlier attempts loaded, or None when the run reads from the stored cursor as
    before. Only a source that returns rows sorted by the cursor can resume: its batches never split a
    cursor value (see `PipelineV3._process_batch`), so resuming strictly after one skips and repeats
    nothing.
    """
    if (
        attempt <= 1
        or not rows_ordered_by_cursor
        or not schema.is_append
        or workflow_run_id is None
        or schema.incremental_field is None
    ):
        return None

    earlier_run_uuids = [attempt_run_uuid(workflow_run_id, earlier) for earlier in range(1, attempt)]
    current_run_uuid = attempt_run_uuid(workflow_run_id, attempt)
    with connect() as conn:
        # Fence first, so an earlier attempt that is still running cannot get a batch loaded later.
        BatchQueue.fence_runs(
            conn,
            run_uuids=earlier_run_uuids,
            team_id=team_id,
            schema_id=str(schema.id),
            source_id=source_id,
            job_id=job_id,
            resource_name=schema.name,
            sync_type="append",
        )
        for _ in range(max(1, int(timeout_seconds / poll_seconds))):
            earlier = BatchQueue.settle_earlier_attempts(conn, job_id=job_id, current_run_uuid=current_run_uuid)
            if earlier.unsettled_batches == 0:
                break
            sleep(poll_seconds)
        else:
            raise TimeoutError(
                f"Earlier attempts of job {job_id} still have unsettled batches after {timeout_seconds}s"
            )

    if earlier.loaded_rows == 0:
        return 0
    if earlier.loaded_last_value is None:
        # Batches queued without a cursor, by a build from before cursors were recorded.
        return None

    schema.advance_incremental_field_last_value(earlier.loaded_last_value)
    return earlier.loaded_rows
