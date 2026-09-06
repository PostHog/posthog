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


# Proof this writer created a table, so a sync never drops, merges into, or replaces one the
# customer already had. `table_name` comes from the source's resource name, which a custom-source
# manifest controls, so without it any table sharing that name in the configured role's reach is
# fair game.
#
# Stored as a Snowflake table comment because that survives the `RENAME TO` in `finalize_run`.
# Scoped by schema id because `table_name` collides across sources on purpose and ownership must
# not.
_OWNERSHIP_COMMENT = "posthog-warehouse-sync-owned"


def _owned_marker(schema_id: str) -> str:
    """Ownership marker scoped to the schema whose sync created the table."""
    return f"{_OWNERSHIP_COMMENT}:{schema_id}"


class UnrelatedTableExistsError(RuntimeError):
    """A sync would have replaced or mutated a table this writer never created."""


def _sql_string_literal(value: str) -> str:
    # `ALTER TABLE ... SET COMMENT` is a DDL statement, and the Snowflake connector's bind
    # variables aren't accepted there any more than Postgres's are — so this quotes and escapes
    # the literal itself. `value` is always this module's own marker text built from a schema id
    # and run uuid, never free-form user input.
    return "'" + value.replace("'", "''") + "'"


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

    async def _table_exists(self, client: SnowflakeClient, table: str) -> bool:
        result = await client.execute_async_query(
            "SELECT 1 FROM information_schema.tables WHERE table_schema = %(schema)s AND table_name = %(table)s",
            parameters={"schema": self._schema, "table": table},
            fetch_results=True,
        )
        return bool(_rows_of(result))

    async def _table_comment(self, client: SnowflakeClient, table: str) -> str | None:
        result = await client.execute_async_query(
            "SELECT comment FROM information_schema.tables WHERE table_schema = %(schema)s AND table_name = %(table)s",
            parameters={"schema": self._schema, "table": table},
            fetch_results=True,
        )
        rows = _rows_of(result)
        return rows[0][0] if rows else None

    async def _mark_owned(self, client: SnowflakeClient, table: str, schema_id: str) -> None:
        await client.execute_async_query(
            f"ALTER TABLE {self._qualified(table)} SET COMMENT = {_sql_string_literal(_owned_marker(schema_id))}"
        )

    async def _is_owned(self, client: SnowflakeClient, table: str, schema_id: str) -> bool:
        # Not a plain `startswith`: schema ids are arbitrary strings, and one could be a
        # character-prefix of another ("abc" of "abc123"), which would let a table another
        # schema owns pass as owned here. Split on the marker's own `:` separator instead so the
        # owning schema id is compared for exact equality.
        comment = await self._table_comment(client, table)
        if comment is None:
            return False
        marker, sep, owner = comment.partition(":")
        if marker != _OWNERSHIP_COMMENT or not sep:
            return False
        return owner == schema_id

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
                    # `target` is the live table on an incremental run, and this writer's own
                    # staging table on a full refresh — either way, a table that predates this
                    # sync and merely happens to share the generated name must be refused before
                    # its schema is evolved or a row in it is touched. Reusing an unowned table
                    # would mutate or delete unrelated data and, on a full refresh's final batch,
                    # replace its ownership marker and swap it in under `finalize_run`'s nose.
                    table_existed = await self._table_exists(client, target)
                    if table_existed and not await self._is_owned(client, target, run.schema_id):
                        raise UnrelatedTableExistsError(
                            f'"{self._schema}"."{target}" already exists and was not created by this sync; '
                            + (
                                "refusing to reuse it as a staging table."
                                if full_refresh
                                else "refusing to merge an incremental run's rows into it."
                            )
                        )

                    await self._ensure_table(client, target, stamped.schema, with_batch_index=False)
                    await self._evolve_table(client, target, stamped.schema)
                    if full_refresh:
                        # This batch may be a re-apply, so clear what its previous attempt wrote.
                        await client.execute_async_query(
                            f"DELETE FROM {self._qualified(target)} "
                            f"WHERE {quote_identifier(BATCH_INDEX_COLUMN)} = {int(ctx.batch_index)}"
                        )
                        # Marked on the staging table, not the live one: the comment survives the
                        # rename in `finalize_run`, which is where it gets checked.
                        await self._mark_owned(client, target, run.schema_id)
                    elif not table_existed:
                        # A table this writer just created for an incremental run never gets
                        # renamed, so mark it in place rather than at swap time.
                        await self._mark_owned(client, target, run.schema_id)
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
            if not await self._table_exists(client, staging):
                # Already swapped by an earlier attempt at this same final batch.
                return

            if await self._table_exists(client, ctx.table_name) and not await self._is_owned(
                client, ctx.table_name, ctx.schema_id
            ):
                # A table with this name exists and this writer never created it. Refuse rather
                # than drop it: `table_name` comes from the source's resource name, which a
                # custom-source manifest controls, and a table that predates this sync could be
                # anything the customer already had in this schema.
                raise UnrelatedTableExistsError(
                    f'"{self._schema}"."{ctx.table_name}" already exists and was not created by this sync; '
                    "refusing to replace it with the full refresh's staging table."
                )

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
