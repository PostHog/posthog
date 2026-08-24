"""Delivering a run's batches to a Postgres database.

The connection, DDL, introspection and bulk load all come from batch exports'
`PostgreSQLClient`, which is the same client its Postgres destination runs on. This writer adds
only what a warehouse sync needs and a batch export does not:

- A full refresh writes into a per-run staging table and swaps it into place on the final
  batch, so the destination table holds the previous run's data right up to the moment the
  new one is complete. A run that dies half way leaves the live table untouched. A batch
  export commits per interval and has no run that spans many batches.
- An incremental run merges each batch into the destination table on the schema's primary
  keys. `amerge_mutable_tables` updates only where a column increases, which suits person
  tables and not a source table with no monotonic column.
- Column types come from `sql_types`, not `get_postgres_fields_from_record_schema`. That
  mapper raises on any type outside the event and person shapes, and a source table may hold
  dates, decimals, binaries or structs.
- Schema evolution is additive. Batch exports filter incoming data down to the columns the
  destination already has, which silently drops new fields, and a synced table is supposed to
  mirror its source.

Every write is idempotent per batch index, because the consumer re-claims any batch whose
outcome it could not confirm.
"""

from __future__ import annotations

import io
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import ClassVar

import pyarrow as pa
from asgiref.sync import sync_to_async
from psycopg import sql

from posthog.models.integration.postgres import PostgreSQLIntegration

from products.batch_exports.backend.temporal.destinations.postgres_batch_export import Fields, PostgreSQLClient
from products.batch_exports.backend.temporal.pipeline.transformer import CSVStreamTransformer
from products.warehouse_sources.backend.temporal.data_imports.destinations.contracts import (
    BatchWriteOutcome,
    DestinationBatchContext,
    DestinationRunContext,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.destinations_load.writers.sql_types import (
    postgres_type_for,
)

# Marks which batch of a run wrote a staged row, so re-applying a batch can delete exactly
# what its previous attempt wrote instead of the whole staging table.
BATCH_INDEX_COLUMN = "_ph_batch_index"


def staging_table_name(ctx: DestinationRunContext) -> str:
    # Run-scoped, so two runs of the same table never share a staging table. Postgres caps
    # identifiers at 63 bytes, hence the truncated run id.
    return f"{ctx.table_name}__ph_stage_{ctx.run_uuid.replace('-', '')[:12]}"


def _load_integration(integration_id: int, team_id: int):
    from posthog.models.integration import Integration  # noqa: PLC0415 — avoids a model import cycle

    return Integration.objects.get(id=integration_id, team_id=team_id)


_aload_integration = sync_to_async(_load_integration, thread_sensitive=False)


class PostgresDestinationWriter:
    """Writes a run's batches into a Postgres table."""

    holds_sync_lock: ClassVar[bool] = False
    runs_post_load: ClassVar[bool] = False

    def __init__(self, ctx: DestinationRunContext) -> None:
        self._ctx = ctx
        self._schema = (ctx.config or {}).get("schema") or "public"
        self._database = (ctx.config or {}).get("database") or "postgres"

    # --- connection -------------------------------------------------------------------

    def _client_from_integration(self, integration) -> PostgreSQLClient:
        # `from_inputs` accepts anything exposing credentials/authority/tls, which the
        # integration wrapper does, so the batch export path and this one resolve credentials
        # identically.
        return PostgreSQLClient.from_inputs(PostgreSQLIntegration(integration), database=self._database)

    async def _make_client(self) -> PostgreSQLClient:
        if self._ctx.integration_id is None:
            raise ValueError(f"Destination {self._ctx.destination_name} has no integration to connect with")

        integration = await _aload_integration(self._ctx.integration_id, self._ctx.team_id)
        return self._client_from_integration(integration)

    @asynccontextmanager
    async def _client(self) -> AsyncIterator[PostgreSQLClient]:
        client = await self._make_client()
        async with client.connect():
            yield client

    # --- dialect seams ------------------------------------------------------------------
    # Overridden by the SQL destinations that share this writer's shape but not its types.

    @property
    def _batch_index_column(self) -> str:
        return BATCH_INDEX_COLUMN

    def _column_type(self, arrow_type: pa.DataType) -> str:
        return postgres_type_for(arrow_type)

    def _fields_for(self, schema: pa.Schema, *, with_batch_index: bool) -> Fields:
        fields: list[tuple[str, str]] = [(field.name, self._column_type(field.type)) for field in schema]
        if with_batch_index:
            fields.append((self._batch_index_column, "INTEGER"))
        return fields  # ty: ignore[invalid-return-type]

    # --- schema -----------------------------------------------------------------------

    async def _ensure_table(
        self, client: PostgreSQLClient, table: str, schema: pa.Schema, *, with_batch_index: bool
    ) -> None:
        async with client.connection.cursor() as cursor:
            await cursor.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(self._schema)))

        await client.acreate_table(
            self._schema,
            table,
            self._fields_for(schema, with_batch_index=with_batch_index),
            exists_ok=True,
        )

    async def _evolve_table(self, client: PostgreSQLClient, table: str, schema: pa.Schema) -> None:
        """Add columns the source has grown since the destination table was created."""
        existing = set(await client.aget_table_columns(self._schema, table))

        for field in schema:
            if field.name in existing:
                continue
            async with client.connection.cursor() as cursor:
                await cursor.execute(
                    sql.SQL("ALTER TABLE {}.{} ADD COLUMN IF NOT EXISTS {} {}").format(
                        sql.Identifier(self._schema),
                        sql.Identifier(table),
                        sql.Identifier(field.name),
                        sql.SQL(self._column_type(field.type)),  # ty: ignore[invalid-argument-type]
                    )
                )

    # --- writer protocol ----------------------------------------------------------------

    async def prepare_run(self, ctx: DestinationRunContext) -> None:
        # Tables are created from the first batch's schema, once it is known.
        return None

    async def write_batch(
        self, batches: AsyncIterator[pa.RecordBatch], ctx: DestinationBatchContext
    ) -> BatchWriteOutcome:
        run = ctx.run
        full_refresh = run.is_full_refresh
        target = staging_table_name(run) if full_refresh else run.table_name

        rows_written = 0

        async with self._client() as client:
            first = True
            async for batch in batches:
                if first:
                    await self._ensure_table(client, target, batch.schema, with_batch_index=full_refresh)
                    await self._evolve_table(client, target, batch.schema)
                    if full_refresh:
                        # This batch may be a re-apply after a crash, so clear whatever its
                        # previous attempt wrote before writing it again.
                        await self._delete_batch_rows(client, target, ctx.batch_index)
                    first = False

                rows_written += await self._write_record_batch(client, target, batch, ctx, full_refresh=full_refresh)

        return BatchWriteOutcome(rows_written=rows_written)

    async def _delete_batch_rows(self, client: PostgreSQLClient, target: str, batch_index: int) -> None:
        async with client.connection.cursor() as cursor:
            await cursor.execute(
                sql.SQL("DELETE FROM {}.{} WHERE {} = %s").format(
                    sql.Identifier(self._schema),
                    sql.Identifier(target),
                    sql.Identifier(self._batch_index_column),
                ),
                (batch_index,),
            )

    def _tsv_buffer(self, batch: pa.RecordBatch, column_names: list[str]) -> io.BytesIO:
        """Render a record batch as TSV, using the same transformer the batch export uses."""
        transformer = CSVStreamTransformer(field_names=column_names, delimiter="\t")
        return io.BytesIO(transformer.write_record_batch(batch))

    async def _write_record_batch(
        self,
        client: PostgreSQLClient,
        target: str,
        batch: pa.RecordBatch,
        ctx: DestinationBatchContext,
        *,
        full_refresh: bool,
    ) -> int:
        run = ctx.run
        if batch.num_rows == 0:
            return 0

        column_names = list(batch.schema.names)

        if full_refresh:
            stamped = batch.append_column(
                self._batch_index_column,
                pa.array([ctx.batch_index] * batch.num_rows, type=pa.int32()),
            )
            await client.copy_tsv_to_postgres(
                self._tsv_buffer(stamped, [*column_names, self._batch_index_column]),
                self._schema,
                target,
                [*column_names, self._batch_index_column],
            )
            return batch.num_rows

        if run.is_incremental and run.primary_keys:
            return await self._merge_batch(client, target, batch, column_names)

        await client.copy_tsv_to_postgres(self._tsv_buffer(batch, column_names), self._schema, target, column_names)
        return batch.num_rows

    async def _merge_batch(
        self, client: PostgreSQLClient, target: str, batch: pa.RecordBatch, column_names: list[str]
    ) -> int:
        """Upsert a batch on the schema's primary keys, through a short-lived stage table."""
        run = self._ctx
        stage = f"{target}__ph_merge_{run.run_uuid.replace('-', '')[:8]}"

        async with client.managed_table(
            self._schema, stage, self._fields_for(batch.schema, with_batch_index=False), delete=True
        ):
            await client.copy_tsv_to_postgres(self._tsv_buffer(batch, column_names), self._schema, stage, column_names)
            await self._upsert_from_stage(client, target, stage, column_names, list(run.primary_keys))

        return batch.num_rows

    async def _upsert_from_stage(
        self,
        client: PostgreSQLClient,
        target: str,
        stage: str,
        column_names: list[str],
        primary_keys: list[str],
    ) -> None:
        await self._ensure_unique_index(client, target, primary_keys)

        updates = [c for c in column_names if c not in primary_keys]
        set_clause = sql.SQL(", ").join(
            sql.SQL("{col} = EXCLUDED.{col}").format(col=sql.Identifier(c)) for c in updates
        )
        columns = sql.SQL(", ").join(sql.Identifier(c) for c in column_names)
        conflict = sql.SQL(", ").join(sql.Identifier(c) for c in primary_keys)

        statement = sql.SQL(
            "INSERT INTO {schema}.{target} ({columns}) SELECT {columns} FROM {schema}.{stage} "
            "ON CONFLICT ({conflict}) DO {action}"
        ).format(
            schema=sql.Identifier(self._schema),
            target=sql.Identifier(target),
            stage=sql.Identifier(stage),
            columns=columns,
            conflict=conflict,
            action=sql.SQL("UPDATE SET {}").format(set_clause) if updates else sql.SQL("NOTHING"),
        )
        async with client.connection.cursor() as cursor:
            await cursor.execute(statement)

    async def _ensure_unique_index(self, client: PostgreSQLClient, target: str, primary_keys: list[str]) -> None:
        """ON CONFLICT needs a unique constraint on the merge keys."""
        index_name = f"{target}__ph_pk"
        async with client.connection.cursor() as cursor:
            await cursor.execute(
                sql.SQL("CREATE UNIQUE INDEX IF NOT EXISTS {} ON {}.{} ({})").format(
                    sql.Identifier(index_name),
                    sql.Identifier(self._schema),
                    sql.Identifier(target),
                    sql.SQL(", ").join(sql.Identifier(c) for c in primary_keys),
                )
            )

    async def finalize_run(self, ctx: DestinationRunContext) -> None:
        """Publish a full refresh by swapping the staging table into place."""
        if not ctx.is_full_refresh:
            return

        staging = staging_table_name(ctx)

        async with self._client() as client:
            if not await self._table_exists(client, staging):
                # Already swapped by an earlier attempt at this same final batch.
                return

            async with client.connection.cursor() as cursor:
                await cursor.execute(
                    sql.SQL("ALTER TABLE {}.{} DROP COLUMN IF EXISTS {}").format(
                        sql.Identifier(self._schema),
                        sql.Identifier(staging),
                        sql.Identifier(self._batch_index_column),
                    )
                )

            async with client.connection.transaction():
                async with client.connection.cursor() as cursor:
                    await cursor.execute("SET TRANSACTION READ WRITE")
                    await cursor.execute(
                        sql.SQL("DROP TABLE IF EXISTS {}.{}").format(
                            sql.Identifier(self._schema), sql.Identifier(ctx.table_name)
                        )
                    )
                    await cursor.execute(
                        sql.SQL("ALTER TABLE {}.{} RENAME TO {}").format(
                            sql.Identifier(self._schema),
                            sql.Identifier(staging),
                            sql.Identifier(ctx.table_name),
                        )
                    )

    async def _table_exists(self, client: PostgreSQLClient, table: str) -> bool:
        async with client.connection.cursor() as cursor:
            await cursor.execute(
                "SELECT 1 FROM information_schema.tables WHERE table_schema = %s AND table_name = %s",
                (self._schema, table),
            )
            return await cursor.fetchone() is not None

    async def abort_run(self, ctx: DestinationRunContext) -> None:
        """Drop whatever a run that will not finish left staged."""
        async with self._client() as client:
            await client.adelete_table(self._schema, staging_table_name(ctx), not_found_ok=True)
