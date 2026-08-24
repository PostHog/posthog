"""Delivering a run's batches to BigQuery.

BigQuery loads Arrow natively, so batches are loaded as parquet rather than turned into INSERT
statements. The shape is otherwise the same as the other SQL destinations:

- A full refresh loads into a per-run staging table and copies it over the live table on the
  final batch. `WRITE_TRUNCATE` on a copy job is atomic, so readers never see a partial run.
- An incremental run loads the batch into a temporary table and runs `MERGE` on the schema's
  primary keys, which is what makes re-applying a batch harmless.
"""

from __future__ import annotations

import io
from collections.abc import AsyncIterator
from typing import ClassVar

import pyarrow as pa
import pyarrow.parquet as pq
from asgiref.sync import sync_to_async
from google.api_core.exceptions import NotFound
from google.cloud import bigquery

from posthog.models.integration.google_cloud import GoogleCloudServiceAccountIntegration

from products.batch_exports.backend.temporal.destinations.bigquery_batch_export import BigQueryClient
from products.warehouse_sources.backend.temporal.data_imports.destinations.contracts import (
    BatchWriteOutcome,
    DestinationBatchContext,
    DestinationRunContext,
)

BATCH_INDEX_COLUMN = "_ph_batch_index"


def staging_table_name(ctx: DestinationRunContext) -> str:
    return f"{ctx.table_name}__ph_stage_{ctx.run_uuid.replace('-', '')[:12]}"


def _backtick(name: str) -> str:
    # BigQuery quoted identifiers cannot contain a backtick at all (there is no escape
    # sequence for one inside backticks), so a name carrying one is rejected rather than
    # silently stripped, which could otherwise let two differently-named source columns
    # collide on the same destination column.
    if "`" in name:
        raise ValueError(f"BigQuery identifier {name!r} cannot contain a backtick")
    return f"`{name}`"


class BigQueryDestinationWriter:
    holds_sync_lock: ClassVar[bool] = False
    runs_post_load: ClassVar[bool] = False

    def __init__(self, ctx: DestinationRunContext) -> None:
        self._ctx = ctx
        config = ctx.config or {}
        self._dataset = config.get("dataset") or config.get("dataset_id") or ""
        self._client: bigquery.Client | None = None
        self._project: str = config.get("project") or config.get("project_id") or ""

    def _get_client(self) -> bigquery.Client:
        """The underlying BigQuery client, resolved the way the batch export resolves it.

        `from_service_account_integration` also covers the case where the integration holds no
        key and PostHog impersonates the service account instead, which hand-building the
        credentials from `sensitive_config` does not.
        """
        if self._client is not None:
            return self._client

        if self._ctx.integration_id is None:
            raise ValueError(f"Destination {self._ctx.destination_name} has no integration to connect with")

        from posthog.models.integration import Integration  # noqa: PLC0415 — avoids a model import cycle

        integration = Integration.objects.get(id=self._ctx.integration_id, team_id=self._ctx.team_id)
        client = BigQueryClient.from_service_account_integration(GoogleCloudServiceAccountIntegration(integration))

        self._client = client.sync_client
        self._project = self._project or self._client.project or ""
        return self._client

    def _table_ref(self, table: str) -> str:
        return f"{self._project}.{self._dataset}.{table}"

    def _quoted_table(self, table: str) -> str:
        return _backtick(self._table_ref(table))

    async def prepare_run(self, ctx: DestinationRunContext) -> None:
        def ensure_dataset() -> None:
            client = self._get_client()
            client.create_dataset(f"{self._project}.{self._dataset}", exists_ok=True)

        await sync_to_async(ensure_dataset, thread_sensitive=False)()

    async def write_batch(
        self, batches: AsyncIterator[pa.RecordBatch], ctx: DestinationBatchContext
    ) -> BatchWriteOutcome:
        rows_written = 0
        chunk = 0

        async for record_batch in batches:
            if record_batch.num_rows == 0:
                continue
            # One load job per record batch. Collecting the whole staged batch first would hold
            # ~200 MiB of Arrow plus its parquet copy in memory, per destination.
            rows_written += await self._write_one(record_batch, ctx, chunk)
            chunk += 1

        return BatchWriteOutcome(rows_written=rows_written)

    async def _write_one(self, record_batch: pa.RecordBatch, ctx: DestinationBatchContext, chunk: int) -> int:
        run = ctx.run
        full_refresh = run.is_full_refresh
        # pq.write_table needs a Table, and one record batch is one load job.
        table = pa.Table.from_batches([record_batch])

        def write() -> int:
            client = self._get_client()

            if full_refresh:
                staging = staging_table_name(run)
                # Batch 0 truncates so a re-run of the whole batch sequence starts clean; later
                # batches append. Re-applying one batch is covered by the apply marker.
                # Only the very first chunk of the very first batch truncates; every later
                # chunk appends, or it would wipe what the chunk before it just loaded.
                disposition = (
                    bigquery.WriteDisposition.WRITE_TRUNCATE
                    if ctx.batch_index == 0 and chunk == 0
                    else bigquery.WriteDisposition.WRITE_APPEND
                )
                self._load(client, staging, table, disposition)
                return table.num_rows

            if run.is_incremental and run.primary_keys:
                temp = f"{run.table_name}__ph_tmp_{run.run_uuid.replace('-', '')[:8]}_{ctx.batch_index}_{chunk}"
                self._load(client, temp, table, bigquery.WriteDisposition.WRITE_TRUNCATE)
                self._merge(client, run.table_name, temp, list(table.schema.names), list(run.primary_keys))
                client.delete_table(self._table_ref(temp), not_found_ok=True)
                return table.num_rows

            self._load(client, run.table_name, table, bigquery.WriteDisposition.WRITE_APPEND)
            return table.num_rows

        return await sync_to_async(write, thread_sensitive=False)()

    def _load(self, client: bigquery.Client, table: str, data: pa.Table, disposition: str) -> None:
        """Load an Arrow table as parquet, letting BigQuery derive and evolve the schema."""
        buffer = io.BytesIO()
        pq.write_table(data, buffer)
        buffer.seek(0)
        job_config = bigquery.LoadJobConfig(
            source_format=bigquery.SourceFormat.PARQUET,
            write_disposition=disposition,
            autodetect=True,
        )
        if disposition == bigquery.WriteDisposition.WRITE_APPEND:
            # Additive evolution: a column the source grew is added rather than rejected.
            # BigQuery rejects this option on a truncating load, which replaces the schema
            # outright and so has nothing to evolve.
            job_config.schema_update_options = [bigquery.SchemaUpdateOption.ALLOW_FIELD_ADDITION]
        client.load_table_from_file(buffer, self._table_ref(table), job_config=job_config).result()

    def _merge(
        self, client: bigquery.Client, target: str, source: str, column_names: list[str], primary_keys: list[str]
    ) -> None:
        on_clause = " AND ".join(f"T.{_backtick(k)} = S.{_backtick(k)}" for k in primary_keys)
        updates = ", ".join(f"T.{_backtick(c)} = S.{_backtick(c)}" for c in column_names if c not in primary_keys)
        columns = ", ".join(_backtick(c) for c in column_names)
        values = ", ".join(f"S.{_backtick(c)}" for c in column_names)
        update_clause = f"WHEN MATCHED THEN UPDATE SET {updates} " if updates else ""
        client.query(
            f"MERGE {self._quoted_table(target)} T USING {self._quoted_table(source)} S ON {on_clause} "
            f"{update_clause}"
            f"WHEN NOT MATCHED THEN INSERT ({columns}) VALUES ({values})"
        ).result()

    async def finalize_run(self, ctx: DestinationRunContext) -> None:
        """Copy a completed full refresh over the live table. Idempotent: no staging table means done."""
        if not ctx.is_full_refresh:
            return

        def publish() -> None:
            client = self._get_client()
            staging = staging_table_name(ctx)
            try:
                client.get_table(self._table_ref(staging))
            except NotFound:
                # No staging table means an earlier attempt already published. Anything else
                # has to propagate: swallowing it would leave the live table on stale data
                # and complete the run anyway.
                return
            client.copy_table(
                self._table_ref(staging),
                self._table_ref(ctx.table_name),
                job_config=bigquery.CopyJobConfig(write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE),
            ).result()
            client.delete_table(self._table_ref(staging), not_found_ok=True)

        await sync_to_async(publish, thread_sensitive=False)()

    async def abort_run(self, ctx: DestinationRunContext) -> None:
        if not ctx.is_full_refresh or self._client is None:
            return

        def drop() -> None:
            try:
                self._get_client().delete_table(self._table_ref(staging_table_name(ctx)), not_found_ok=True)
            except Exception:
                pass

        await sync_to_async(drop, thread_sensitive=False)()
