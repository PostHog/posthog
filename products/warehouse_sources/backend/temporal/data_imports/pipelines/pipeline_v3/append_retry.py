import time
from collections.abc import Callable
from typing import Any

import psycopg

from posthog.settings import WAREHOUSE_SOURCES_DATABASE_URL

from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.jobs_db import (
    BatchQueue,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.producer import (
    connect_with_retry,
)

SETTLE_POLL_SECONDS = 5.0
# Longer than the queue's recovery sweep takes to release a batch whose loader died mid-write.
SETTLE_TIMEOUT_SECONDS = 20 * 60.0


def attempt_run_uuid(workflow_run_id: str, attempt: int) -> str:
    return f"{workflow_run_id}-a{attempt}"


def _connect_to_queue() -> psycopg.Connection[Any]:
    return connect_with_retry(WAREHOUSE_SOURCES_DATABASE_URL)


def resume_append_retry(
    schema: ExternalDataSchema,
    *,
    job_id: str,
    workflow_run_id: str | None,
    attempt: int,
    source_is_resumable: bool,
    connect: Callable[[], psycopg.Connection[Any]] = _connect_to_queue,
    sleep: Callable[[float], None] = time.sleep,
    poll_seconds: float = SETTLE_POLL_SECONDS,
    timeout_seconds: float = SETTLE_TIMEOUT_SECONDS,
) -> int | None:
    """Make a retried append attempt continue after the rows its earlier attempts loaded.

    An append writes every row it gets, and the cursor is only committed when the load finishes. So
    a retry that reads from the committed cursor appends again every row an earlier attempt loaded.
    This supersedes the earlier attempts' unloaded batches, waits for any batch still being written,
    and moves the committed cursor to the last loaded batch.

    Returns the rows the earlier attempts loaded, or None when the run reads from the stored cursor
    as before. A resumable source is skipped: it continues from its own checkpoint, and its earlier
    batches must still load.
    """
    if (
        attempt <= 1
        or not schema.is_append
        or source_is_resumable
        or workflow_run_id is None
        or schema.incremental_field is None
    ):
        return None

    current_run_uuid = attempt_run_uuid(workflow_run_id, attempt)
    with connect() as conn:
        for _ in range(max(1, int(timeout_seconds / poll_seconds))):
            earlier = BatchQueue.settle_earlier_attempts(conn, job_id=job_id, current_run_uuid=current_run_uuid)
            if earlier.unsettled_batches == 0:
                break
            sleep(poll_seconds)
        else:
            raise TimeoutError(
                f"Earlier attempts of job {job_id} still have unsettled batches after {timeout_seconds}s"
            )

    if earlier.loaded_last_value is None:
        return None

    schema.advance_incremental_field_last_value(earlier.loaded_last_value)
    return earlier.loaded_rows
