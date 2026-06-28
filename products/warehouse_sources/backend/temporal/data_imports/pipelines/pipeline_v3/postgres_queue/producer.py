"""
Postgres-backed batch producer for warehouse source loading.

Drop-in replacement for KafkaBatchProducer: each send_batch_notification
inserts a row into the Postgres batch queue. flush() is a no-op because
inserts are durable on commit — no async delivery pipeline to drain.
"""

from __future__ import annotations

import json
import time
import random
from collections.abc import Callable
from typing import Any, Optional

import psycopg
import structlog
from psycopg.errors import ProtocolViolation
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    PartitionFormat,
    PartitionMode,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.kafka.common import SyncTypeLiteral
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.jobs_db import (
    BATCH_TABLE,
    BatchQueue,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.s3 import BatchWriteResult

logger = structlog.get_logger(__name__)

# When the warehouse_sources queue pool is saturated, PgBouncer cuts off a query that can't
# get a backend connection in time with a query_wait_timeout. It arrives as SQLSTATE 08P01
# (psycopg ProtocolViolation) and PgBouncer disconnects the client, so a retry must reconnect
# rather than reuse the dropped connection. The statement never reached a backend, so re-running
# is safe: the supersede write is idempotent and a retried INSERT only runs when the prior
# attempt never committed.
_POOL_RETRY_MAX_ATTEMPTS = 4
_POOL_RETRY_BASE_SECONDS = 0.2
_POOL_RETRY_MAX_SECONDS = 2.0


class PostgresProducer:
    """Writes batch rows directly into the Postgres queue on each send call."""

    def __init__(
        self,
        database_url: str,
        team_id: int,
        job_id: str,
        schema_id: str,
        source_id: str,
        resource_name: str,
        sync_type: SyncTypeLiteral,
        run_uuid: str,
        logger: FilteringBoundLogger,
        primary_keys: list[str] | None = None,
        is_resume: bool = False,
        partition_count: int | None = None,
        partition_size: int | None = None,
        partition_keys: list[str] | None = None,
        partition_format: PartitionFormat | None = None,
        partition_mode: PartitionMode | None = None,
        is_first_ever_sync: bool = False,
        cdc_write_mode: str | None = None,
        cdc_table_mode: str | None = None,
        workflow_id: str | None = None,
        workflow_run_id: str | None = None,
    ) -> None:
        self._team_id = team_id
        self._job_id = job_id
        self._schema_id = schema_id
        self._source_id = source_id
        self._resource_name = resource_name
        self._sync_type = sync_type
        self._run_uuid = run_uuid
        self._primary_keys = primary_keys
        self._is_resume = is_resume
        self._logger = logger
        self._partition_count = partition_count
        self._partition_size = partition_size
        self._partition_keys = partition_keys
        self._partition_format = partition_format
        self._partition_mode = partition_mode
        self._is_first_ever_sync = is_first_ever_sync
        self._cdc_write_mode = cdc_write_mode
        self._cdc_table_mode = cdc_table_mode
        self._workflow_id = workflow_id
        self._workflow_run_id = workflow_run_id

        self._database_url = database_url
        self._conn = psycopg.Connection.connect(database_url, autocommit=True)
        self._batches_sent = 0

    @property
    def sync_type(self) -> SyncTypeLiteral:
        return self._sync_type

    @property
    def is_first_ever_sync(self) -> bool:
        return self._is_first_ever_sync

    @is_first_ever_sync.setter
    def is_first_ever_sync(self, value: bool) -> None:
        self._is_first_ever_sync = value

    def send_batch_notification(
        self,
        batch_result: BatchWriteResult,
        is_final_batch: bool = False,
        total_batches: Optional[int] = None,
        total_rows: Optional[int] = None,
        data_folder: Optional[str] = None,
        schema_path: Optional[str] = None,
        cumulative_row_count: int = 0,
    ) -> None:
        """Insert a batch row into the Postgres queue."""
        metadata: dict[str, Any] = {}
        if data_folder is not None:
            metadata["data_folder"] = data_folder
        if schema_path is not None:
            metadata["schema_path"] = schema_path
        if self._primary_keys is not None:
            metadata["primary_keys"] = self._primary_keys
        if self._partition_count is not None:
            metadata["partition_count"] = self._partition_count
        if self._partition_size is not None:
            metadata["partition_size"] = self._partition_size
        if self._partition_keys is not None:
            metadata["partition_keys"] = self._partition_keys
        if self._partition_format is not None:
            metadata["partition_format"] = self._partition_format
        if self._partition_mode is not None:
            metadata["partition_mode"] = self._partition_mode
        if self._cdc_write_mode is not None:
            metadata["cdc_write_mode"] = self._cdc_write_mode
        if self._cdc_table_mode is not None:
            metadata["cdc_table_mode"] = self._cdc_table_mode
        # Producer runs inside a Temporal activity; pass ids through so the consumer
        # can bind log context without re-querying ExternalDataJob.
        if self._workflow_id is not None:
            metadata["workflow_id"] = self._workflow_id
        if self._workflow_run_id is not None:
            metadata["workflow_run_id"] = self._workflow_run_id
        metadata["timestamp_ns"] = batch_result.timestamp_ns

        should_supersede = batch_result.batch_index == 0 and not self._is_resume
        insert_params = {
            "team_id": self._team_id,
            "schema_id": self._schema_id,
            "source_id": self._source_id,
            "job_id": self._job_id,
            "run_uuid": self._run_uuid,
            "batch_index": batch_result.batch_index,
            "s3_path": batch_result.s3_path,
            "row_count": batch_result.row_count,
            "byte_size": batch_result.byte_size,
            "is_final_batch": is_final_batch,
            "total_batches": total_batches,
            "total_rows": total_rows,
            "sync_type": self._sync_type,
            "cumulative_row_count": cumulative_row_count,
            "resource_name": self._resource_name,
            "is_resume": self._is_resume,
            "is_first_ever_sync": self._is_first_ever_sync,
            "metadata": json.dumps(metadata),
        }

        def _write() -> None:
            # Supersede + insert run together so a reconnect-and-retry replays both as one
            # idempotent unit: re-superseding is a no-op once old batches are failed, and the
            # INSERT only re-runs when the prior attempt never committed.
            if should_supersede:
                superseded = BatchQueue.supersede_other_runs(
                    self._conn, job_id=self._job_id, current_run_uuid=self._run_uuid
                )
                if superseded > 0:
                    self._logger.info("superseded_old_run_batches", count=superseded)

            self._conn.execute(
                f"""
                INSERT INTO {BATCH_TABLE} (
                    team_id, schema_id, source_id, job_id, run_uuid,
                    batch_index, s3_path, row_count, byte_size, is_final_batch,
                    total_batches, total_rows, sync_type, cumulative_row_count,
                    resource_name, is_resume, is_first_ever_sync, metadata, created_at
                ) VALUES (
                    %(team_id)s, %(schema_id)s, %(source_id)s, %(job_id)s, %(run_uuid)s,
                    %(batch_index)s, %(s3_path)s, %(row_count)s, %(byte_size)s, %(is_final_batch)s,
                    %(total_batches)s, %(total_rows)s, %(sync_type)s, %(cumulative_row_count)s,
                    %(resource_name)s, %(is_resume)s, %(is_first_ever_sync)s, %(metadata)s, now()
                )
                """,
                insert_params,
            )

        self._run_with_pool_retry(_write)

        self._batches_sent += 1
        if is_final_batch:
            self._logger.info(
                "batch_inserted_to_postgres_queue",
                batch_index=batch_result.batch_index,
                is_final_batch=True,
                total_batches=total_batches,
                total_rows=total_rows,
            )
        else:
            self._logger.debug(
                "batch_inserted_to_postgres_queue",
                batch_index=batch_result.batch_index,
                is_final_batch=False,
            )

    def _run_with_pool_retry(self, work: Callable[[], None]) -> None:
        """Run a queue write, retrying transient PgBouncer pool-saturation errors.

        A ``query_wait_timeout`` (psycopg ``ProtocolViolation``) means the pool couldn't hand
        the statement a backend connection, so nothing executed and PgBouncer dropped the
        client. Each retry reconnects before re-running ``work``, which the callers keep
        idempotent so a replay can't double-write. After the final attempt the error is
        re-raised so Temporal can still retry the whole activity.
        """
        for attempt in range(1, _POOL_RETRY_MAX_ATTEMPTS + 1):
            try:
                work()
                return
            except ProtocolViolation as exc:
                if attempt == _POOL_RETRY_MAX_ATTEMPTS:
                    self._logger.warning("postgres_queue_pool_retry_exhausted", attempts=attempt, error=str(exc))
                    raise
                self._logger.warning("postgres_queue_pool_retry", attempt=attempt, error=str(exc))
                self._reconnect()
                backoff = min(_POOL_RETRY_BASE_SECONDS * 2 ** (attempt - 1), _POOL_RETRY_MAX_SECONDS)
                time.sleep(backoff + random.uniform(0, _POOL_RETRY_BASE_SECONDS))

    def _reconnect(self) -> None:
        """Drop the (now disconnected) connection and open a fresh one for the next attempt."""
        try:
            if not self._conn.closed:
                self._conn.close()
        except Exception:
            pass
        self._conn = psycopg.Connection.connect(self._database_url, autocommit=True)

    def flush(self, timeout: Optional[float] = None) -> int:
        """No-op — inserts are durable on commit. Returns count of batches sent since last flush."""
        count = self._batches_sent
        self._batches_sent = 0
        return count

    def close(self) -> None:
        """Close the Postgres connection."""
        if not self._conn.closed:
            self._conn.close()
