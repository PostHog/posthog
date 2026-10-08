"""Test stand-in for the V3 load consumer.

A V3 run only extracts: it writes batches to S3 and queue rows to the Postgres batch table, and
the load consumer loads them later. Tests point the producer at the Django test database, then
replay the queue rows through the consumer's `process_message` so the run finishes in-process.
"""

import json
from typing import Any

from unittest import mock

from django.conf import settings
from django.db import connection as django_conn
from django.test import override_settings

import psycopg
from asgiref.sync import sync_to_async

from products.warehouse_sources.backend.facade.models import ExternalDataJob
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.load.processor import (
    process_message,
)
from products.warehouse_sources.backend.types import ExternalDataJobStatus
from products.warehouse_sources_queue.backend.core.jobs_db import BATCH_TABLE, PendingBatch
from products.warehouse_sources_queue.backend.testing import ensure_queue_tables, get_test_database_url

PRODUCER_DATABASE_URL_PATH = (
    "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.pipeline."
    "WAREHOUSE_SOURCES_DATABASE_URL"
)


class PostgresQueueReplay:
    """Reads batch rows written by PostgresProducer during tests and replays them
    through process_message(), mimicking what the real BatchConsumer does."""

    def __init__(self) -> None:
        self._processed_batches: set[tuple[str, int, str | None]] = set()

    def replay_batches_for_run(self, run_uuid: str) -> None:
        with django_conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT id, team_id, schema_id, source_id, job_id, run_uuid,
                       batch_index, s3_path, row_count, byte_size, is_final_batch,
                       total_batches, total_rows, sync_type, cumulative_row_count,
                       resource_name, is_resume, is_first_ever_sync, metadata, destination_ids
                FROM {BATCH_TABLE}
                WHERE run_uuid = %s
                ORDER BY created_at ASC, batch_index ASC
                """,
                [run_uuid],
            )
            columns = [col.name for col in cur.description]
            rows = [dict(zip(columns, row)) for row in cur.fetchall()]

        if not rows:
            return

        for row in rows:
            if isinstance(row.get("metadata"), str):
                row["metadata"] = json.loads(row["metadata"])
            # Same treatment as metadata: this cursor hands jsonb back as text, and iterating
            # the string would feed "[" to the destination lookup as if it were an id.
            if isinstance(row.get("destination_ids"), str):
                row["destination_ids"] = json.loads(row["destination_ids"])
            batch = PendingBatch(latest_attempt=0, **row)
            try:
                process_message(batch.to_export_signal())
            except Exception:
                pass

    def get_run_uuids_for_job(self, job_id: str) -> list[str]:
        with django_conn.cursor() as cur:
            cur.execute(
                f"SELECT DISTINCT run_uuid FROM {BATCH_TABLE} WHERE job_id = %s ORDER BY run_uuid",
                [job_id],
            )
            return [row[0] for row in cur.fetchall()]

    def mock_idempotency_check(
        self,
        team_id: int,
        schema_id: str,
        run_uuid: str,
        batch_index: int,
        delta_table_ref: Any = None,
        destination_id: str | None = None,
        *,
        is_first_attempt: bool = False,
    ) -> bool:
        # `is_first_attempt` is accepted for signature-compatibility with the real
        # `is_batch_already_processed` (which callers invoke with it as a keyword),
        # but this in-memory replay tracks "already processed" purely by which keys
        # it has already seen, so it doesn't need to branch on it.
        # Keyed by destination as well, mirroring the real check: a batch the warehouse has
        # taken is not yet done for a destination that has not.
        key = (run_uuid, batch_index, destination_id)
        if key in self._processed_batches:
            return True
        self._processed_batches.add(key)
        return False

    def clear(self) -> None:
        self._processed_batches.clear()


def ensure_queue_tables_in_test_database() -> None:
    with psycopg.connect(get_test_database_url(), autocommit=True) as conn:
        ensure_queue_tables(conn)


def patch_producer_to_test_database() -> Any:
    return mock.patch(PRODUCER_DATABASE_URL_PATH, get_test_database_url())


async def replay_v3_consumer(
    replay: PostgresQueueReplay,
    team_id: int,
    schema_id: Any,
    bucket_name: str,
    job_id: str | None = None,
) -> None:
    if not job_id:
        job = await sync_to_async(
            ExternalDataJob.objects.filter(team_id=team_id, schema_id=schema_id).order_by("-created_at").first
        )()
        if not job:
            return
        job_id = str(job.id)
    else:
        job = await sync_to_async(ExternalDataJob.objects.get)(id=job_id)

    # If the workflow already marked the job as COMPLETED (e.g. worker shutdown scenario),
    # the consumer should not replay — the workflow managed the job status itself and
    # S3 files may have been cleaned up.
    if job.status == ExternalDataJobStatus.COMPLETED:
        replay.clear()
        return

    run_uuids = await sync_to_async(replay.get_run_uuids_for_job)(job_id)
    if not run_uuids:
        replay.clear()
        return

    with (
        override_settings(
            BUCKET_URL=f"s3://{bucket_name}",
            BUCKET_PATH=bucket_name,
            DATAWAREHOUSE_LOCAL_ACCESS_KEY=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
            DATAWAREHOUSE_LOCAL_ACCESS_SECRET=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            DATAWAREHOUSE_LOCAL_BUCKET_REGION="us-east-1",
            DATAWAREHOUSE_BUCKET_DOMAIN="objectstorage:19000",
            DATA_WAREHOUSE_REDIS_HOST="localhost",
            DATA_WAREHOUSE_REDIS_PORT="6379",
            DATAWAREHOUSE_BUCKET=bucket_name,
        ),
        mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.load.processor.is_batch_already_processed",
            side_effect=replay.mock_idempotency_check,
        ),
    ):
        for run_uuid in run_uuids:
            await sync_to_async(replay.replay_batches_for_run)(run_uuid)

    replay.clear()
