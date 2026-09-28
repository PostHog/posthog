from collections.abc import Callable
from typing import Any

import psycopg

from posthog.settings import WAREHOUSE_SOURCES_DATABASE_URL

from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.jobs_db import (
    BatchQueue,
    EarlierBatch,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.producer import (
    connect_with_retry,
)


def attempt_run_uuid(workflow_run_id: str, attempt: int) -> str:
    return f"{workflow_run_id}-a{attempt}"


def _connect_to_queue() -> psycopg.Connection[Any]:
    return connect_with_retry(WAREHOUSE_SOURCES_DATABASE_URL)


def find_append_retry_resume(
    schema: ExternalDataSchema,
    *,
    job_id: str,
    workflow_run_id: str | None,
    attempt: int,
    source_is_resumable: bool,
    connect: Callable[[], psycopg.Connection[Any]] = _connect_to_queue,
) -> EarlierBatch | None:
    """The batch a retried append attempt continues after, or None to read from the stored cursor.

    An append writes every row it gets, and the cursor is only committed when the load finishes. So a
    retry that reads from the stored cursor appends again every row an earlier attempt queued, because
    those batches still load. The retry instead reads after the newest batch an earlier attempt queued,
    and runs as a resume, so that attempt's batches stay queued.

    A resumable source is skipped: it continues from its own checkpoint.
    """
    if (
        attempt <= 1
        or not schema.is_append
        or source_is_resumable
        or workflow_run_id is None
        or schema.incremental_field is None
    ):
        return None

    with connect() as conn:
        earlier = BatchQueue.newest_batch_of_earlier_attempts(
            conn, job_id=job_id, current_run_uuid=attempt_run_uuid(workflow_run_id, attempt)
        )
    if earlier is None or earlier.incremental_last_value is None:
        return None
    return earlier
