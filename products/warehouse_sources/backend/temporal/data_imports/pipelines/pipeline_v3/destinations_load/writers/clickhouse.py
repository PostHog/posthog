"""Delivering a run's batches to ClickHouse.

ClickHouse cannot merge a batch into a table in place, so every batch is inserted and the table
engine settles each key:

- With primary keys, the table is a `ReplacingMergeTree` ordered by them and versioned by
  `_ph_synced_at`, the server's insert time. Background merges keep the newest row per key, and
  until they run a reader needs `FINAL`. The version is not derived from the run, because a retried
  attempt numbers its batches from zero again and can carry fresher rows.
- Without primary keys, the table is a `MergeTree` that every batch appends to.

Every insert carries an `insert_deduplication_token` naming its run, batch and chunk, so a
redelivered chunk lands once and identical rows from another batch are not mistaken for one. A
full refresh fills a per-run staging table and swaps it in with `EXCHANGE TABLES`. Whether a run
already published is read from the live table's comment, which moves with it in the exchange.

The connection comes from the ClickHouse source's `_get_client`. Dates outside 1900 to 2299 are
clamped instead of failing the batch, and a cluster that needs `ON CLUSTER` is not supported.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import closing
from typing import ClassVar

import pyarrow as pa
from clickhouse_connect.driver.client import Client as ClickHouseClient
from clickhouse_connect.driver.query import arrow_buffer

from posthog.hogql.escape_sql import backquote_clickhouse_identifier, escape_param_clickhouse

from posthog.dataclasses import frozen
from posthog.models.integration import ClickHouseIntegration, Integration

from products.warehouse_sources.backend.temporal.data_imports.destinations.contracts import (
    BatchWriteOutcome,
    DestinationBatchContext,
    DestinationRunContext,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.destinations_load.writers.merge_dedup import (
    dedupe_merge_source,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.destinations_load.writers.postgres import (
    json_encode_nested_columns,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.destinations_load.writers.run_markers import (
    is_owned_by,
    is_published_by,
    owned_marker,
    published_marker,
    run_scope,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.clickhouse.clickhouse import _get_client

SYNCED_AT_COLUMN = "_ph_synced_at"

# Replicated tables deduplicate inserts by default. A single-node server only does with this set.
DEDUPLICATION_WINDOW = 1000

# A server that does not know this setting falls back to its default instead of refusing to connect.
SESSION_SETTINGS = {"date_time_overflow_behavior": "saturate"}

# Table metadata lives in a file named after the table, and file names stop at 255 bytes.
_MAX_TABLE_NAME_BYTES = 200

_TIMESTAMP_PRECISION = {"s": 0, "ms": 3, "us": 6, "ns": 9}

_MAX_DECIMAL_PRECISION = 76

_CLICKHOUSE_BY_ARROW = {
    pa.bool_(): "Bool",
    pa.int8(): "Int8",
    pa.int16(): "Int16",
    pa.int32(): "Int32",
    pa.int64(): "Int64",
    pa.uint8(): "UInt8",
    pa.uint16(): "UInt16",
    pa.uint32(): "UInt32",
    pa.uint64(): "UInt64",
    pa.float16(): "Float32",
    pa.float32(): "Float32",
    pa.float64(): "Float64",
    pa.string(): "String",
    pa.large_string(): "String",
    pa.string_view(): "String",
    pa.binary(): "String",
    pa.large_binary(): "String",
    pa.binary_view(): "String",
    pa.date32(): "Date32",
    pa.date64(): "Date32",
}


class UnrelatedTableExistsError(RuntimeError):
    """A sync would have replaced or written to a table this writer never created."""


class IncompatibleTableError(RuntimeError):
    """A table this writer created is not keyed on the run's primary keys, so it cannot settle them."""


class ClickHouseIntegrationNotFoundError(RuntimeError):
    """The destination's integration is gone or is not a ClickHouse one."""


@frozen
class _ExistingTable:
    engine: str
    comment: str | None
    columns: frozenset[str]
    sorting_key: frozenset[str]


def clickhouse_type_for(arrow_type: pa.DataType) -> str:
    """The ClickHouse column type for an Arrow type.

    Arrow stores aware and naive timestamps alike as time since the epoch, so UTC keeps both
    readings unchanged. Nested values arrive as JSON text.
    """
    if pa.types.is_dictionary(arrow_type):
        return clickhouse_type_for(arrow_type.value_type)

    mapped = _CLICKHOUSE_BY_ARROW.get(arrow_type)
    if mapped is None:
        if pa.types.is_timestamp(arrow_type):
            mapped = f"DateTime64({_TIMESTAMP_PRECISION[arrow_type.unit]}, 'UTC')"
        elif pa.types.is_decimal(arrow_type) and arrow_type.precision <= _MAX_DECIMAL_PRECISION:
            mapped = f"Decimal({arrow_type.precision}, {arrow_type.scale})"
        elif pa.types.is_duration(arrow_type):
            mapped = "Int64"
        else:
            mapped = "String"
    return f"Nullable({mapped})"


def prepare_for_insert(batch: pa.RecordBatch) -> pa.RecordBatch:
    """Convert the columns ClickHouse's Arrow input cannot take into what `clickhouse_type_for` declared."""
    batch = json_encode_nested_columns(batch)

    for index, field in enumerate(batch.schema):
        column = batch.column(index)
        if isinstance(column, pa.DictionaryArray):
            column = column.dictionary_decode()

        arrow_type = column.type
        if pa.types.is_time(arrow_type) or pa.types.is_null(arrow_type):
            column = column.cast(pa.string())
        elif pa.types.is_duration(arrow_type):
            column = column.cast(pa.int64())
        elif pa.types.is_float16(arrow_type):
            column = column.cast(pa.float32())
        elif pa.types.is_date64(arrow_type):
            column = column.cast(pa.date32())
        elif pa.types.is_decimal(arrow_type) and arrow_type.precision > _MAX_DECIMAL_PRECISION:
            column = column.cast(pa.string())

        if column.type != field.type:
            batch = batch.set_column(index, pa.field(field.name, column.type), column)

    return batch


def staging_table_name(ctx: DestinationRunContext) -> str:
    suffix = f"__ph_stage_{run_scope(ctx.run_uuid)}"
    base = ctx.table_name.encode()[: _MAX_TABLE_NAME_BYTES - len(suffix)].decode(errors="ignore")
    return f"{base}{suffix}"


def deduplication_token(ctx: DestinationBatchContext, chunk: int) -> str:
    return f"{ctx.run.run_uuid}:{ctx.batch_index}:{chunk}"


class ClickHouseDestinationWriter:
    """Writes a run's batches into a ClickHouse table."""

    holds_sync_lock: ClassVar[bool] = False
    runs_post_load: ClassVar[bool] = False

    def __init__(self, ctx: DestinationRunContext) -> None:
        self._ctx = ctx
        self._database = (ctx.config or {}).get("database") or "default"

    async def _make_client(self) -> ClickHouseClient:
        if self._ctx.integration_id is None:
            raise ValueError(f"Destination {self._ctx.destination_name} has no integration to connect with")

        try:
            integration = await Integration.objects.aget(
                id=self._ctx.integration_id,
                team_id=self._ctx.team_id,
                kind=Integration.IntegrationKind.CLICKHOUSE,
            )
        except Integration.DoesNotExist as err:
            raise ClickHouseIntegrationNotFoundError(
                f"ClickHouse integration with id '{self._ctx.integration_id}' not found"
            ) from err

        credentials = ClickHouseIntegration(integration)
        # No default database, because the configured one may not exist until `_ensure_database`.
        return await asyncio.to_thread(
            _get_client,
            host=credentials.host,
            port=credentials.port,
            database="",
            user=credentials.user,
            password=credentials.password,
            secure=True,
            verify=credentials.verify,
            settings=SESSION_SETTINGS,
        )

    def _qualified(self, table: str) -> str:
        return f"{backquote_clickhouse_identifier(self._database)}.{backquote_clickhouse_identifier(table)}"

    def _existing_table(self, client: ClickHouseClient, table: str) -> _ExistingTable | None:
        parameters = {"database": self._database, "table": table}
        tables = client.query(
            "SELECT engine, comment FROM system.tables WHERE database = {database:String} AND name = {table:String}",
            parameters=parameters,
        ).result_rows
        if not tables:
            return None

        columns = client.query(
            "SELECT name, is_in_sorting_key FROM system.columns "
            "WHERE database = {database:String} AND table = {table:String}",
            parameters=parameters,
        ).result_rows
        engine, comment = tables[0]
        return _ExistingTable(
            engine=engine,
            comment=comment or None,
            columns=frozenset(name for name, _ in columns),
            sorting_key=frozenset(name for name, in_sorting_key in columns if in_sorting_key),
        )

    def _ensure_database(self, client: ClickHouseClient) -> None:
        # `CREATE DATABASE IF NOT EXISTS` checks the grant before existence, so it would refuse a
        # user who may use the database but not create one.
        exists = client.query(
            "SELECT 1 FROM system.databases WHERE name = {database:String}",
            parameters={"database": self._database},
        ).result_rows
        if not exists:
            client.command(f"CREATE DATABASE IF NOT EXISTS {backquote_clickhouse_identifier(self._database)}")

    def _create_table(self, client: ClickHouseClient, table: str, schema: pa.Schema, keys: list[str]) -> None:
        columns = [
            f"{backquote_clickhouse_identifier(field.name)} {clickhouse_type_for(field.type)}" for field in schema
        ]
        if keys:
            columns.append(f"{backquote_clickhouse_identifier(SYNCED_AT_COLUMN)} DateTime64(6, 'UTC') DEFAULT now64(6)")
            order_by = ", ".join(backquote_clickhouse_identifier(key) for key in keys)
            # Source primary keys arrive as nullable columns, which a sorting key refuses by default.
            engine = (
                f"ENGINE = ReplacingMergeTree({backquote_clickhouse_identifier(SYNCED_AT_COLUMN)}) ORDER BY ({order_by}) "
                f"SETTINGS allow_nullable_key = 1, non_replicated_deduplication_window = {DEDUPLICATION_WINDOW}"
            )
        else:
            engine = (
                "ENGINE = MergeTree ORDER BY tuple() "
                f"SETTINGS non_replicated_deduplication_window = {DEDUPLICATION_WINDOW}"
            )

        # Marked in the same statement, so a run that stops never leaves a table it cannot claim.
        client.command(
            f"CREATE TABLE IF NOT EXISTS {self._qualified(table)} ({', '.join(columns)}) {engine} "
            f"COMMENT {escape_param_clickhouse(owned_marker(self._ctx.schema_id))}"
        )

    def _ensure_table(self, client: ClickHouseClient, table: str, schema: pa.Schema, keys: list[str]) -> None:
        existing = self._existing_table(client, table)
        if existing is None:
            self._ensure_database(client)
            self._create_table(client, table, schema, keys)
            return

        if not is_owned_by(existing.comment, self._ctx.schema_id):
            raise UnrelatedTableExistsError(
                f"{self._qualified(table)} already exists and was not created by this sync; "
                "refusing to write this sync's rows into it."
            )

        if keys and ("ReplacingMergeTree" not in existing.engine or existing.sorting_key != frozenset(keys)):
            raise IncompatibleTableError(
                f"{self._qualified(table)} is not keyed on {', '.join(keys)}, so rows with the same key would "
                "pile up instead of replacing each other. Drop the table so the next sync recreates it."
            )

        for field in schema:
            if field.name not in existing.columns:
                client.command(
                    f"ALTER TABLE {self._qualified(table)} ADD COLUMN IF NOT EXISTS "
                    f"{backquote_clickhouse_identifier(field.name)} {clickhouse_type_for(field.type)}"
                )

    async def prepare_run(self, ctx: DestinationRunContext) -> None:
        return None

    async def write_batch(
        self, batches: AsyncIterator[pa.RecordBatch], ctx: DestinationBatchContext
    ) -> BatchWriteOutcome:
        run = ctx.run
        target = staging_table_name(run) if run.is_full_refresh else run.table_name
        rows_written = 0
        chunk = 0

        client = await self._make_client()
        with closing(client):
            async for batch in batches:
                if batch.num_rows == 0:
                    continue

                keys = [key for key in run.primary_keys if key in batch.schema.names]
                if chunk == 0:
                    await asyncio.to_thread(self._ensure_table, client, target, batch.schema, keys)

                rows_written += await asyncio.to_thread(self._insert_chunk, client, target, batch, keys, ctx, chunk)
                chunk += 1

        return BatchWriteOutcome(rows_written=rows_written)

    def _insert_chunk(
        self,
        client: ClickHouseClient,
        target: str,
        batch: pa.RecordBatch,
        keys: list[str],
        ctx: DestinationBatchContext,
        chunk: int,
    ) -> int:
        if keys:
            # One insert shares one `_ph_synced_at`, so keep the last copy of a key ourselves.
            batch = dedupe_merge_source(batch, keys)

        rows = prepare_for_insert(batch)

        compression = client.write_compression if client.write_compression in ("zstd", "lz4") else None
        column_names, payload = arrow_buffer(pa.Table.from_batches([rows]), compression)
        # clickhouse-connect passes a name already wrapped in backticks through unescaped, and a
        # source controls its column names, so every name is quoted here instead.
        client.raw_insert(
            self._qualified(target),
            [backquote_clickhouse_identifier(name) for name in column_names],
            payload,
            settings={"insert_deduplication_token": deduplication_token(ctx, chunk)},
            fmt="Arrow",
        )
        return rows.num_rows

    def _drop_if_owned(self, client: ClickHouseClient, table: str, schema_id: str) -> None:
        existing = self._existing_table(client, table)
        if existing is not None and is_owned_by(existing.comment, schema_id):
            client.command(f"DROP TABLE IF EXISTS {self._qualified(table)}")

    async def finalize_run(self, ctx: DestinationRunContext) -> None:
        """Publish a full refresh by exchanging the staging table with the live one."""
        if not ctx.is_full_refresh:
            return

        client = await self._make_client()
        with closing(client):
            await asyncio.to_thread(self._publish, client, ctx)

    def _publish(self, client: ClickHouseClient, ctx: DestinationRunContext) -> None:
        staging = staging_table_name(ctx)
        live = self._existing_table(client, ctx.table_name)

        if live is not None and is_published_by(live.comment, ctx.schema_id, ctx.run_uuid):
            # Already published. A replayed final batch staged its rows again, or an earlier attempt
            # stopped between the exchange and the drop, which left the old data under this name.
            self._drop_if_owned(client, staging, ctx.schema_id)
            return

        if self._existing_table(client, staging) is None:
            # The run delivered no rows. The live table keeps the previous run, as elsewhere.
            return

        if live is not None and not is_owned_by(live.comment, ctx.schema_id):
            raise UnrelatedTableExistsError(
                f"{self._qualified(ctx.table_name)} already exists and was not created by this sync; "
                "refusing to replace it with the full refresh's staging table."
            )

        client.command(
            f"ALTER TABLE {self._qualified(staging)} "
            f"MODIFY COMMENT {escape_param_clickhouse(published_marker(ctx.schema_id, ctx.run_uuid))}"
        )
        if live is None:
            client.command(f"RENAME TABLE {self._qualified(staging)} TO {self._qualified(ctx.table_name)}")
            return

        client.command(f"EXCHANGE TABLES {self._qualified(ctx.table_name)} AND {self._qualified(staging)}")
        self._drop_if_owned(client, staging, ctx.schema_id)

    async def abort_run(self, ctx: DestinationRunContext) -> None:
        """Drop the staging table of a full refresh that will not finish."""
        if not ctx.is_full_refresh:
            return

        client = await self._make_client()
        with closing(client):
            await asyncio.to_thread(self._drop_if_owned, client, staging_table_name(ctx), ctx.schema_id)
