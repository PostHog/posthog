"""
Postgres-backed batch producer for warehouse source loading.

Drop-in replacement for KafkaBatchProducer: each send_batch_notification
inserts a row into the Postgres batch queue. flush() is a no-op because
inserts are durable on commit — no async delivery pipeline to drain.
"""

from __future__ import annotations

import json
import time
from typing import Any, Optional

import psycopg
import structlog
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.messages import SyncTypeLiteral
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.s3 import BatchWriteResult
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import (
    PartitionFormat,
    PartitionMode,
)
from products.warehouse_sources_queue.backend.core.jobs_db import BATCH_TABLE, BatchQueue

logger = structlog.get_logger(__name__)

# PgBouncer occasionally closes a just-opened connection under load or failover ("server
# closed the connection unexpectedly"). A short local retry clears it without failing the
# whole Temporal activity attempt, which would re-run the entire pipeline setup for what is
# usually a one-off blip.
_CONNECT_MAX_ATTEMPTS = 3
_CONNECT_RETRY_BACKOFF_SECONDS = 0.5


def connect_with_retry(database_url: str) -> psycopg.Connection:
    for _ in range(_CONNECT_MAX_ATTEMPTS - 1):
        try:
            return psycopg.Connection.connect(database_url, autocommit=True)
        except psycopg.OperationalError:
            time.sleep(_CONNECT_RETRY_BACKOFF_SECONDS)
    return psycopg.Connection.connect(database_url, autocommit=True)


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
        destination_ids: list[str] | None = None,
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
        self._destination_ids: list[str] = list(destination_ids or [])

        self._conn = connect_with_retry(database_url)
        self._batches_sent = 0
        # The most recent staged batch and its cumulative row count, kept out of the queue until the
        # next batch arrives or the run ends, so the run's last row can carry the final flag itself.
        self._held: tuple[BatchWriteResult, int, Any] | None = None

    @property
    def sync_type(self) -> SyncTypeLiteral:
        return self._sync_type

    @property
    def is_first_ever_sync(self) -> bool:
        return self._is_first_ever_sync

    @is_first_ever_sync.setter
    def is_first_ever_sync(self, value: bool) -> None:
        self._is_first_ever_sync = value

    @property
    def has_held_batch(self) -> bool:
        return self._held is not None

    def hold_batch(
        self, batch_result: BatchWriteResult, *, cumulative_row_count: int, incremental_last_value: Any = None
    ) -> None:
        """Stage a batch's queue row, inserting the previously held one as a non-final row.

        The parquet file is already durable when this is called; only the queue row waits. Holding
        one row back is what lets `send_final_batch` flag the run's last data row as final instead of
        inserting a second row for it, which the loader would have to process twice.

        Superseding runs on the staging of batch 0, not on its insert, so it keeps firing at the
        same point of the run it always has.
        """
        if batch_result.batch_index == 0 and not self._is_resume:
            self._supersede_other_runs()
        previous = self._held
        self._held = (batch_result, cumulative_row_count, incremental_last_value)
        if previous is not None:
            self._insert(
                previous[0],
                is_final_batch=False,
                cumulative_row_count=previous[1],
                incremental_last_value=previous[2],
            )

    def release_held_batch(self) -> bool:
        """Insert the held batch as a non-final row now. Returns whether a row was inserted.

        For a resumable source, whose cursor commit promises that every yielded row is loadable,
        the held row has to be in the queue before that commit lands.
        """
        held = self._held
        if held is None:
            return False
        self._held = None
        self._insert(held[0], is_final_batch=False, cumulative_row_count=held[1], incremental_last_value=held[2])
        return True

    def send_final_batch(
        self,
        last_batch: BatchWriteResult,
        *,
        total_batches: int,
        total_rows: int,
        data_folder: str,
        schema_path: str | None,
    ) -> None:
        """Mark the run complete: the held last batch becomes the final row.

        When nothing is held (a resumable source released it before a cursor commit), the last
        batch is inserted a second time as a final-only marker, which the loader still accepts.
        """
        held = self._held
        self._held = None
        final_batch = last_batch if held is None else held[0]
        self._insert(
            final_batch,
            is_final_batch=True,
            total_batches=total_batches,
            total_rows=total_rows,
            data_folder=data_folder,
            schema_path=schema_path,
            cumulative_row_count=total_rows,
            incremental_last_value=None if held is None else held[2],
        )

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
        """Insert a batch row into the Postgres queue immediately."""
        if batch_result.batch_index == 0 and not self._is_resume:
            self._supersede_other_runs()
        self._insert(
            batch_result,
            is_final_batch=is_final_batch,
            total_batches=total_batches,
            total_rows=total_rows,
            data_folder=data_folder,
            schema_path=schema_path,
            cumulative_row_count=cumulative_row_count,
        )

    def _supersede_other_runs(self) -> None:
        # One-shot, at the start of a fresh (non-resume) run: stalled sibling runs of
        # this job go terminal so their batches can't double-load. Runs the loader is
        # still draining are spared (see supersede_other_runs); a spared run that
        # stalls later is recovered by the reconcile sweep's stranded-run pass.
        #
        # A full_refresh is the exception: this run's batch 0 overwrites the table, so
        # an older attempt's loaded rows are gone either way and sparing it only leaves
        # its batches clogging the serial per-(team, schema) gate. So is an append run that
        # got here: it reads again from the stored cursor, so every spared batch it lets
        # load is appended twice. An append retry that can continue after the older
        # attempt runs as a resume and never reaches this.
        superseded = BatchQueue.supersede_other_runs(
            self._conn,
            job_id=self._job_id,
            current_run_uuid=self._run_uuid,
            spare_runs_with_progress=self._sync_type not in ("full_refresh", "append"),
        )
        if superseded > 0:
            self._logger.info("superseded_old_run_batches", count=superseded)

    def _insert(
        self,
        batch_result: BatchWriteResult,
        *,
        is_final_batch: bool,
        total_batches: Optional[int] = None,
        total_rows: Optional[int] = None,
        data_folder: Optional[str] = None,
        schema_path: Optional[str] = None,
        cumulative_row_count: int = 0,
        incremental_last_value: Any = None,
    ) -> None:
        metadata: dict[str, Any] = {}
        # The cursor through this batch's rows, which the loader commits once the batch loads.
        if incremental_last_value is not None:
            metadata["incremental_last_value"] = incremental_last_value
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

        self._conn.execute(
            f"""
        INSERT INTO {BATCH_TABLE} (
            team_id, schema_id, source_id, job_id, run_uuid,
            batch_index, s3_path, row_count, byte_size, is_final_batch,
            total_batches, total_rows, sync_type, cumulative_row_count,
            resource_name, is_resume, is_first_ever_sync, metadata, destination_ids, created_at
        ) VALUES (
            %(team_id)s, %(schema_id)s, %(source_id)s, %(job_id)s, %(run_uuid)s,
            %(batch_index)s, %(s3_path)s, %(row_count)s, %(byte_size)s, %(is_final_batch)s,
            %(total_batches)s, %(total_rows)s, %(sync_type)s, %(cumulative_row_count)s,
            %(resource_name)s, %(is_resume)s, %(is_first_ever_sync)s, %(metadata)s, %(destination_ids)s, now()
        )
            """,
            {
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
                "destination_ids": json.dumps(self._destination_ids),
            },
        )

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

    def flush(self, timeout: Optional[float] = None) -> int:
        """No-op — inserts are durable on commit. Returns count of batches sent since last flush."""
        count = self._batches_sent
        self._batches_sent = 0
        return count

    def close(self) -> None:
        """Close the Postgres connection."""
        if not self._conn.closed:
            self._conn.close()
