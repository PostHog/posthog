"""Delivering a run's batches to Snowflake.

Connection handling, authentication, async query polling, the `PUT` into the table's internal
stage and the `COPY INTO` that follows all come from batch exports' `SnowflakeClient`. The copy
helper is what checks that every file it loaded reported `LOADED`, retries a suspended
warehouse, and turns a server-side timeout, an incompatible schema and a missing privilege into
their own typed errors.

Two pieces of batch exports are deliberately not reused:

- The Arrow to Snowflake type mapping behind `SnowflakeField.from_arrow_field`. Its vocabulary
  has no `DATE`, `TIME` or `NUMBER(p, s)` and it raises on anything else, which is fine for
  events and persons but would silently turn a source date column into a timestamp and a
  decimal into a float. The DDL here keeps those types. The table handed to the shared stage
  helpers carries the Arrow types instead, which is all those helpers read.
- `merge_into_final_from_stage`, which needs a version key to decide what to update. A synced
  source table has no monotonic column, so the merge below matches on primary keys alone.

Snowflake identifiers are case-sensitive once quoted, and unquoted ones fold to upper case.
Everything here is quoted, so a source column named `id` stays `id` rather than becoming `ID`
and breaking a later merge.
"""

from __future__ import annotations

import io
from collections.abc import AsyncIterator
from typing import ClassVar

import pyarrow as pa
import pyarrow.parquet as pq

from products.batch_exports.backend.temporal.destinations.snowflake_batch_export import (
    NamedBytesIO,
    SnowflakeClient,
    SnowflakeField,
    SnowflakeTable,
    SnowflakeType,
    _get_snowflake_integration,
    load_private_key,
)
from products.warehouse_sources.backend.temporal.data_imports.destinations.contracts import (
    BatchWriteOutcome,
    DestinationBatchContext,
    DestinationRunContext,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.destinations_load.writers.sql_types import (
    quote_identifier,
)

_SNOWFLAKE_BY_ARROW = {
    pa.bool_(): "BOOLEAN",
    pa.int8(): "NUMBER(38, 0)",
    pa.int16(): "NUMBER(38, 0)",
    pa.int32(): "NUMBER(38, 0)",
    pa.int64(): "NUMBER(38, 0)",
    pa.uint8(): "NUMBER(38, 0)",
    pa.uint16(): "NUMBER(38, 0)",
    pa.uint32(): "NUMBER(38, 0)",
    pa.uint64(): "NUMBER(38, 0)",
    pa.float16(): "FLOAT",
    pa.float32(): "FLOAT",
    pa.float64(): "FLOAT",
    pa.string(): "VARCHAR",
    pa.large_string(): "VARCHAR",
    pa.binary(): "BINARY",
    pa.large_binary(): "BINARY",
    pa.date32(): "DATE",
    pa.date64(): "DATE",
}

BATCH_INDEX_COLUMN = "_ph_batch_index"

# batch exports' `SnowflakeClient` writes the stage path and the COPY INTO column list by
# interpolating the names it is handed with no escaping of its own: a raw double-quoted
# identifier, inside a single-quoted path. Batch exports only ever passes it names it derived
# internally, so that was never reachable with input a user controls. Here the table name
# carries the destination's configured prefix and the column names come from the source's Arrow
# schema, both of which a team member (or, through a shared source, its schema) controls, so
# anything that could break out of either quoting context is rejected before it reaches the
# shared client. Statements this module writes itself still quote and escape through
# `quote_identifier`.
_UNSAFE_IDENTIFIER_CHARS = ('"', "'", "\\", "\n", "\r", "\x00")


def _assert_safe_identifier(value: str, what: str) -> str:
    if not value or any(ch in value for ch in _UNSAFE_IDENTIFIER_CHARS):
        raise ValueError(f"Unsafe Snowflake {what}: {value!r}")
    return value


# Snowflake polls asynchronously, so these bound how long one statement may take.
COPY_TIMEOUT_SECONDS = 60 * 30
MERGE_TIMEOUT_SECONDS = 60 * 30

# `SnowflakeField` asks for a Snowflake type that the stage helpers never read, see `_stage_table`.
_UNREAD_SNOWFLAKE_TYPE = SnowflakeType(name="STRING", repeated=False)


def snowflake_type_for(arrow_type: pa.DataType) -> str:
    mapped = _SNOWFLAKE_BY_ARROW.get(arrow_type)
    if mapped is not None:
        return mapped
    if pa.types.is_timestamp(arrow_type):
        return "TIMESTAMP_TZ" if arrow_type.tz else "TIMESTAMP_NTZ"
    if pa.types.is_time(arrow_type):
        return "TIME"
    if pa.types.is_decimal(arrow_type):
        return f"NUMBER({arrow_type.precision}, {arrow_type.scale})"
    if (
        pa.types.is_list(arrow_type)
        or pa.types.is_large_list(arrow_type)
        or pa.types.is_struct(arrow_type)
        or pa.types.is_map(arrow_type)
    ):
        # VARIANT keeps semi-structured values whole, so a struct that grows a field keeps
        # loading rather than needing a schema change.
        return "VARIANT"
    return "VARCHAR"


def _stage_table(table: str, schema: pa.Schema, stage_prefix: str) -> SnowflakeTable:
    """The table as batch exports' stage helpers want to see it.

    `remove_internal_stage_files`, `put_file_to_snowflake_table_stage` and
    `copy_loaded_files_to_snowflake_table` read a table's name, its stage prefix, and each
    field's name and Arrow type. They never read the Snowflake type, which is why the column
    types this writer maps (`DATE`, `TIME`, `NUMBER(p, s)`) can stay out of a vocabulary that
    has no room for them, and why the placeholder passed in their place is safe.
    """
    _assert_safe_identifier(table, "table name")
    fields = [
        SnowflakeField(
            _assert_safe_identifier(field.name, "column name"),
            _UNREAD_SNOWFLAKE_TYPE,
            field.type,
            field.nullable,
        )
        for field in schema
    ]
    return SnowflakeTable(name=table, fields=fields, stage_prefix=stage_prefix)


def _rows_of(result) -> list:
    """`execute_async_query` returns (rows, metadata), or None when nothing was fetched."""
    if not result:
        return []
    rows, _metadata = result
    return list(rows)


def staging_table_name(ctx: DestinationRunContext) -> str:
    return f"{ctx.table_name}__PH_STAGE_{ctx.run_uuid.replace('-', '')[:12]}"


class SnowflakeDestinationWriter:
    holds_sync_lock: ClassVar[bool] = False
    runs_post_load: ClassVar[bool] = False

    def __init__(self, ctx: DestinationRunContext) -> None:
        self._ctx = ctx
        config = ctx.config or {}
        self._database = config.get("database") or ""
        self._schema = config.get("schema") or "PUBLIC"
        self._warehouse = config.get("warehouse") or ""
        self._role = config.get("role")

    # --- connection -------------------------------------------------------------------

    async def _make_client(self) -> SnowflakeClient:
        if self._ctx.integration_id is None:
            raise ValueError(f"Destination {self._ctx.destination_name} has no integration to connect with")

        creds = await _get_snowflake_integration(self._ctx.integration_id, self._ctx.team_id)

        private_key: bytes | None = None
        password: str | None = None
        if creds.authentication_type == "keypair":
            if creds.private_key is None:
                raise ValueError(
                    f"Destination {self._ctx.destination_name} has keypair authentication but no private key"
                )
            private_key = load_private_key(creds.private_key, creds.private_key_passphrase)
        else:
            password = creds.password

        return SnowflakeClient(
            user=creds.user,
            account=creds.account,
            warehouse=self._warehouse,
            database=self._database,
            schema=self._schema,
            role=self._role,
            password=password,
            private_key=private_key,
        )

    # --- statements -------------------------------------------------------------------

    def _qualified(self, table: str) -> str:
        return f"{quote_identifier(self._schema)}.{quote_identifier(table)}"

    async def _ensure_table(
        self, client: SnowflakeClient, table: str, schema: pa.Schema, *, with_batch_index: bool
    ) -> None:
        columns = [f"{quote_identifier(f.name)} {snowflake_type_for(f.type)}" for f in schema]
        if with_batch_index:
            columns.append(f"{quote_identifier(BATCH_INDEX_COLUMN)} NUMBER(38, 0)")

        await client.execute_async_query(f"CREATE SCHEMA IF NOT EXISTS {quote_identifier(self._schema)}")
        await client.execute_async_query(f"CREATE TABLE IF NOT EXISTS {self._qualified(table)} ({', '.join(columns)})")

    async def _evolve_table(self, client: SnowflakeClient, table: str, schema: pa.Schema) -> None:
        """Add columns the source has grown. Additive only, same as the other SQL writers."""
        result = await client.execute_async_query(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = %(schema)s AND table_name = %(table)s",
            parameters={"schema": self._schema, "table": table},
            fetch_results=True,
        )
        existing = {row[0] for row in _rows_of(result)}

        for field in schema:
            if field.name in existing or field.name.upper() in existing:
                continue
            await client.execute_async_query(
                f"ALTER TABLE {self._qualified(table)} "
                f"ADD COLUMN IF NOT EXISTS {quote_identifier(field.name)} {snowflake_type_for(field.type)}"
            )

    # --- writer protocol ----------------------------------------------------------------

    async def prepare_run(self, ctx: DestinationRunContext) -> None:
        return None

    async def write_batch(
        self, batches: AsyncIterator[pa.RecordBatch], ctx: DestinationBatchContext
    ) -> BatchWriteOutcome:
        run = ctx.run
        full_refresh = run.is_full_refresh
        target = staging_table_name(run) if full_refresh else run.table_name

        client = await self._make_client()
        rows_written = 0

        async with client.connect():
            first = True
            chunk = 0
            async for batch in batches:
                if batch.num_rows == 0:
                    continue

                stamped = (
                    batch.append_column(
                        BATCH_INDEX_COLUMN,
                        pa.array([ctx.batch_index] * batch.num_rows, type=pa.int32()),
                    )
                    if full_refresh
                    else batch
                )

                if first:
                    await self._ensure_table(client, target, stamped.schema, with_batch_index=False)
                    await self._evolve_table(client, target, stamped.schema)
                    if full_refresh:
                        # This batch may be a re-apply, so clear what its previous attempt wrote.
                        await client.execute_async_query(
                            f"DELETE FROM {self._qualified(target)} "
                            f"WHERE {quote_identifier(BATCH_INDEX_COLUMN)} = {int(ctx.batch_index)}"
                        )
                    first = False

                if run.is_incremental and run.primary_keys and not full_refresh:
                    await self._merge_chunk(client, target, stamped, list(run.primary_keys), ctx.batch_index, chunk)
                else:
                    await self._copy_chunk(client, target, stamped, ctx.batch_index, chunk)

                rows_written += batch.num_rows
                chunk += 1

        return BatchWriteOutcome(rows_written=rows_written)

    def _parquet_file(self, batch: pa.RecordBatch, name: str) -> NamedBytesIO:
        # PUT compresses whatever it does not recognize as already compressed, so a plain
        # `.parquet` name would arrive gzipped. Writing zstd under a `.zst` name is the same
        # shape batch exports uploads through this stage.
        buffer = io.BytesIO()
        pq.write_table(pa.Table.from_batches([batch]), buffer, compression="zstd")
        return NamedBytesIO(buffer.getvalue(), name)

    async def _copy_chunk(
        self, client: SnowflakeClient, target: str, batch: pa.RecordBatch, batch_index: int, chunk: int
    ) -> None:
        prefix = f"ph_{batch_index}_{chunk}"
        table = _stage_table(target, batch.schema, prefix)

        # The stage path is derived from the batch index, so a retry of this chunk lands on the
        # path its previous attempt used. PUT does not overwrite, so without this the upload
        # would be skipped and COPY INTO would load the file the earlier attempt left behind.
        await client.remove_internal_stage_files(table)
        await client.put_file_to_snowflake_table_stage(
            file=self._parquet_file(batch, f"{prefix}.parquet.zst"),
            table=table,
        )
        await client.copy_loaded_files_to_snowflake_table(table, COPY_TIMEOUT_SECONDS)

    async def _merge_chunk(
        self,
        client: SnowflakeClient,
        target: str,
        batch: pa.RecordBatch,
        primary_keys: list[str],
        batch_index: int,
        chunk: int,
    ) -> None:
        """Upsert on the primary keys, staging the chunk in a scratch table first."""
        columns = list(batch.schema.names)
        stage_table = f"{target}__PH_MERGE_{batch_index}_{chunk}"

        await self._ensure_table(client, stage_table, batch.schema, with_batch_index=False)
        try:
            await self._copy_chunk(client, stage_table, batch, batch_index, chunk)

            on_clause = " AND ".join(
                f"target.{quote_identifier(k)} = source.{quote_identifier(k)}" for k in primary_keys
            )
            updates = [c for c in columns if c not in primary_keys]
            set_clause = ", ".join(f"target.{quote_identifier(c)} = source.{quote_identifier(c)}" for c in updates)
            insert_cols = ", ".join(quote_identifier(c) for c in columns)
            insert_vals = ", ".join(f"source.{quote_identifier(c)}" for c in columns)

            matched = f"WHEN MATCHED THEN UPDATE SET {set_clause} " if updates else ""
            await client.execute_async_query(
                f"MERGE INTO {self._qualified(target)} AS target "
                f"USING {self._qualified(stage_table)} AS source ON {on_clause} "
                f"{matched}"
                f"WHEN NOT MATCHED THEN INSERT ({insert_cols}) VALUES ({insert_vals})",
                timeout=MERGE_TIMEOUT_SECONDS,
            )
        finally:
            await client.execute_async_query(f"DROP TABLE IF EXISTS {self._qualified(stage_table)}")

    async def finalize_run(self, ctx: DestinationRunContext) -> None:
        """Publish a full refresh by swapping the staging table into place."""
        if not ctx.is_full_refresh:
            return

        staging = staging_table_name(ctx)
        client = await self._make_client()

        async with client.connect():
            result = await client.execute_async_query(
                "SELECT 1 FROM information_schema.tables WHERE table_schema = %(schema)s AND table_name = %(table)s",
                parameters={"schema": self._schema, "table": staging},
                fetch_results=True,
            )
            if not _rows_of(result):
                # Already swapped by an earlier attempt at this same final batch.
                return

            await client.execute_async_query(
                f"ALTER TABLE {self._qualified(staging)} DROP COLUMN IF EXISTS {quote_identifier(BATCH_INDEX_COLUMN)}"
            )
            await client.execute_async_query(f"DROP TABLE IF EXISTS {self._qualified(ctx.table_name)}")
            await client.execute_async_query(
                f"ALTER TABLE {self._qualified(staging)} RENAME TO {self._qualified(ctx.table_name)}"
            )

    async def abort_run(self, ctx: DestinationRunContext) -> None:
        # The next run stages under its own id, so a leftover table costs storage only.
        client = await self._make_client()
        async with client.connect():
            await client.execute_async_query(f"DROP TABLE IF EXISTS {self._qualified(staging_table_name(ctx))}")
