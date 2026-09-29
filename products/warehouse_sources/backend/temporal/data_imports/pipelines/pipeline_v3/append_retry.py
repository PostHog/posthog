from collections.abc import Callable
from typing import Any, cast

import psycopg
import pyarrow as pa
import pyarrow.compute as pc

from posthog.dataclasses import frozen
from posthog.settings import WAREHOUSE_SOURCES_DATABASE_URL

from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.producer import (
    connect_with_retry,
)
from products.warehouse_sources_queue.backend.core.jobs_db import BatchQueue


def attempt_run_uuid(workflow_run_id: str, attempt: int) -> str:
    return f"{workflow_run_id}-a{attempt}"


@frozen
class CursorTieSplit:
    kept: pa.Table
    # Rows that share the highest cursor value, which the next table can continue.
    held: pa.Table


def split_trailing_cursor_ties(table: pa.Table, cursor_column: str) -> CursorTieSplit:
    """Split off the rows that share the table's highest cursor value.

    The source returns rows sorted by the cursor, so these rows are the table's tail, and the next
    table can hold more rows with the same value. `kept` is a slice of `table`. `held` is a copy, so it
    does not keep the whole table in memory while it waits for the next one.
    """
    cursor = table[cursor_column]
    highest = cast(pa.Scalar, pc.max(cursor))
    if not highest.is_valid:
        return CursorTieSplit(kept=table, held=table.slice(table.num_rows))
    first_at_highest = cast(pa.Int64Scalar, pc.index(cursor, highest)).as_py()
    held = table.take(pa.array(range(first_at_highest, table.num_rows), pa.int64()))
    return CursorTieSplit(kept=table.slice(0, first_at_highest), held=held)


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
) -> int | None:
    """Make a retried append attempt continue after exactly the rows its earlier attempts loaded.

    The loader commits each loaded batch's cursor as the watermark (see `_commit_loaded_cursor`). This
    fences the earlier attempts, supersedes their unloaded batches, and reloads the watermark. A batch
    the loader is still writing can land after that, and the loader drops its rows from this attempt.

    Returns the rows the earlier attempts loaded, or None when the run reads as it would without
    them. Only a source that returns rows sorted by the cursor can resume: its batches never split a
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
        earlier = BatchQueue.settle_earlier_attempts(conn, job_id=job_id, current_run_uuid=current_run_uuid)

    schema.refresh_from_db(fields=["sync_type_config"])
    # Nothing loaded, or a loader that did not commit the loaded cursor (a build from before this, or a
    # cursor it cannot compare): the retry reads as it would have, so a reset still reads everything.
    if not schema.job_loaded_through(job_id, earlier.loaded_last_value):
        return None
    return earlier.loaded_rows
