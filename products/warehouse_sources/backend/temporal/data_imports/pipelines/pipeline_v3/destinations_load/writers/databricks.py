"""Delivering a run's batches to Databricks.

Connection handling, OAuth for the service principal, the reachability preflight, the retrying
connect and the statement timeouts all come from batch exports' `DatabricksClient`. Rows load
by putting a parquet file into a Databricks volume and running `COPY INTO`, which is the path
Databricks is built for, rather than binding rows one at a time.

`DatabricksField` is just `(name, type)`, so the client's `acopy_into_table_from_volume` takes
the column types worked out here without going through a table abstraction.

The merge stays local: batch exports decides what to update from a version key, and a synced
source table has no monotonic column, so this matches on primary keys alone.
"""

from __future__ import annotations

import io
from collections.abc import AsyncIterator
from typing import ClassVar

import pyarrow as pa
import pyarrow.parquet as pq
from asgiref.sync import sync_to_async

from posthog.models.integration.databricks import DatabricksIntegration

from products.batch_exports.backend.temporal.destinations.databricks_batch_export import (
    DatabricksClient,
    DatabricksField,
)
from products.warehouse_sources.backend.temporal.data_imports.destinations.contracts import (
    BatchWriteOutcome,
    DestinationBatchContext,
    DestinationRunContext,
)

_DATABRICKS_BY_ARROW = {
    pa.bool_(): "BOOLEAN",
    pa.int8(): "TINYINT",
    pa.int16(): "SMALLINT",
    pa.int32(): "INT",
    pa.int64(): "BIGINT",
    pa.uint8(): "SMALLINT",
    pa.uint16(): "INT",
    pa.uint32(): "BIGINT",
    pa.uint64(): "DECIMAL(20, 0)",
    pa.float16(): "FLOAT",
    pa.float32(): "FLOAT",
    pa.float64(): "DOUBLE",
    pa.string(): "STRING",
    pa.large_string(): "STRING",
    pa.binary(): "BINARY",
    pa.large_binary(): "BINARY",
    pa.date32(): "DATE",
    pa.date64(): "DATE",
}

BATCH_INDEX_COLUMN = "_ph_batch_index"


def databricks_type_for(arrow_type: pa.DataType) -> str:
    mapped = _DATABRICKS_BY_ARROW.get(arrow_type)
    if mapped is not None:
        return mapped
    if pa.types.is_timestamp(arrow_type):
        return "TIMESTAMP"
    if pa.types.is_decimal(arrow_type):
        return f"DECIMAL({arrow_type.precision}, {arrow_type.scale})"
    if (
        pa.types.is_list(arrow_type)
        or pa.types.is_large_list(arrow_type)
        or pa.types.is_struct(arrow_type)
        or pa.types.is_map(arrow_type)
    ):
        # Stored as JSON text rather than a typed STRUCT: a nested shape that grows a field
        # would otherwise need a schema change on every source change.
        return "STRING"
    return "STRING"


def backtick(name: str) -> str:
    escaped = name.replace("`", "``")
    return f"`{escaped}`"


# batch exports' DatabricksClient builds COPY INTO / PUT statements by interpolating the
# table name, volume path and column names it is given with no escaping of its own (a raw
# backtick-wrapped identifier, and a single-quoted path). Batch exports only ever passes it
# names it derived internally, so that was never reachable with attacker-controlled input.
# Here the table name and volume come from a destination's own config and the column names
# come from the source's Arrow schema, both of which a team member (or, through a shared
# source, its schema) controls. Reject anything that could break out of either quoting
# context rather than teach the shared client to escape a case it was never built for.
_UNSAFE_IDENTIFIER_CHARS = ('`', "'", '"', "\\", "\n", "\r", "\x00")


def _assert_safe_identifier(value: str, what: str) -> str:
    if not value or any(ch in value for ch in _UNSAFE_IDENTIFIER_CHARS):
        raise ValueError(f"Unsafe Databricks {what}: {value!r}")
    return value


def staging_table_name(ctx: DestinationRunContext) -> str:
    return f"{ctx.table_name}__ph_stage_{ctx.run_uuid.replace('-', '')[:12]}"


def fields_for(schema: pa.Schema, *, with_batch_index: bool) -> list[DatabricksField]:
    # Column names come from the source's own Arrow schema, so they get the same
    # rejection as destination config before reaching the unescaped shared client calls.
    fields: list[DatabricksField] = [
        (_assert_safe_identifier(f.name, "column name"), databricks_type_for(f.type)) for f in schema
    ]
    if with_batch_index:
        fields.append((BATCH_INDEX_COLUMN, "INT"))
    return fields


def _load_integration(integration_id: int, team_id: int):
    from posthog.models.integration import Integration  # noqa: PLC0415 — avoids a model import cycle

    return Integration.objects.get(id=integration_id, team_id=team_id)


_aload_integration = sync_to_async(_load_integration, thread_sensitive=False)


class DatabricksDestinationWriter:
    holds_sync_lock: ClassVar[bool] = False
    runs_post_load: ClassVar[bool] = False

    def __init__(self, ctx: DestinationRunContext) -> None:
        self._ctx = ctx
        config = ctx.config or {}
        self._catalog = _assert_safe_identifier(config.get("catalog") or "main", "catalog")
        self._schema = _assert_safe_identifier(config.get("schema") or "default", "schema")
        self._http_path = config.get("http_path") or ""
        self._volume = _assert_safe_identifier(config.get("volume") or "posthog_warehouse_sync", "volume")

    # --- connection -------------------------------------------------------------------

    async def _make_client(self) -> DatabricksClient:
        if self._ctx.integration_id is None:
            raise ValueError(f"Destination {self._ctx.destination_name} has no integration to connect with")

        integration = await _aload_integration(self._ctx.integration_id, self._ctx.team_id)
        creds = DatabricksIntegration(integration)

        return DatabricksClient(
            server_hostname=creds.server_hostname,
            http_path=self._http_path,
            client_id=creds.client_id,
            client_secret=creds.client_secret,
            catalog=self._catalog,
            schema=self._schema,
        )

    # --- statements -------------------------------------------------------------------

    def _qualified(self, table: str) -> str:
        return f"{backtick(self._catalog)}.{backtick(self._schema)}.{backtick(table)}"

    def _volume_path(self) -> str:
        return f"/Volumes/{self._catalog}/{self._schema}/{self._volume}"

    async def _ensure_table(self, client: DatabricksClient, table: str, fields: list[DatabricksField]) -> None:
        columns = ", ".join(f"{backtick(name)} {type_name}" for name, type_name in fields)
        await client.execute_query(f"CREATE TABLE IF NOT EXISTS {self._qualified(table)} ({columns}) USING DELTA")

    # --- writer protocol ----------------------------------------------------------------

    async def prepare_run(self, ctx: DestinationRunContext) -> None:
        return None

    async def write_batch(
        self, batches: AsyncIterator[pa.RecordBatch], ctx: DestinationBatchContext
    ) -> BatchWriteOutcome:
        run = ctx.run
        full_refresh = run.is_full_refresh
        target = _assert_safe_identifier(
            staging_table_name(run) if full_refresh else run.table_name, "table name"
        )

        client = await self._make_client()
        rows_written = 0

        async with client.connect():
            async with client.managed_volume(self._volume):
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
                    fields = fields_for(batch.schema, with_batch_index=full_refresh)

                    if first:
                        await self._ensure_table(client, target, fields)
                        if full_refresh:
                            # This batch may be a re-apply, so clear what its previous attempt wrote.
                            await client.execute_query(
                                f"DELETE FROM {self._qualified(target)} "
                                f"WHERE {backtick(BATCH_INDEX_COLUMN)} = {int(ctx.batch_index)}"
                            )
                        first = False

                    if run.is_incremental and run.primary_keys and not full_refresh:
                        await self._merge_chunk(
                            client, target, stamped, fields, list(run.primary_keys), ctx.batch_index, chunk
                        )
                    else:
                        await self._copy_chunk(client, target, stamped, fields, ctx.batch_index, chunk)

                    rows_written += batch.num_rows
                    chunk += 1

        return BatchWriteOutcome(rows_written=rows_written)

    async def _copy_chunk(
        self,
        client: DatabricksClient,
        target: str,
        batch: pa.RecordBatch,
        fields: list[DatabricksField],
        batch_index: int,
        chunk: int,
    ) -> None:
        """PUT one record batch into the volume as parquet, then COPY INTO the table."""
        buffer = io.BytesIO()
        pq.write_table(pa.Table.from_batches([batch]), buffer)
        buffer.seek(0)

        file_name = f"ph_{batch_index}_{chunk}.parquet"
        volume_path = f"{self._volume_path()}/{target}"

        await client.aput_file_stream_to_volume(buffer, volume_path, file_name)
        await client.acopy_into_table_from_volume(
            target,
            f"{volume_path}/{file_name}",
            fields,
            with_schema_evolution=True,
        )

    async def _merge_chunk(
        self,
        client: DatabricksClient,
        target: str,
        batch: pa.RecordBatch,
        fields: list[DatabricksField],
        primary_keys: list[str],
        batch_index: int,
        chunk: int,
    ) -> None:
        """Upsert on the primary keys, staging the chunk in a scratch table first."""
        columns = list(batch.schema.names)
        stage_table = f"{target}__ph_merge_{batch_index}_{chunk}"

        await self._ensure_table(client, stage_table, fields)
        try:
            await self._copy_chunk(client, stage_table, batch, fields, batch_index, chunk)

            on_clause = " AND ".join(f"target.{backtick(k)} = source.{backtick(k)}" for k in primary_keys)
            updates = [c for c in columns if c not in primary_keys]
            set_clause = ", ".join(f"target.{backtick(c)} = source.{backtick(c)}" for c in updates)
            insert_cols = ", ".join(backtick(c) for c in columns)
            insert_vals = ", ".join(f"source.{backtick(c)}" for c in columns)

            matched = f"WHEN MATCHED THEN UPDATE SET {set_clause} " if updates else ""
            await client.execute_query(
                f"MERGE INTO {self._qualified(target)} AS target "
                f"USING {self._qualified(stage_table)} AS source ON {on_clause} "
                f"{matched}"
                f"WHEN NOT MATCHED THEN INSERT ({insert_cols}) VALUES ({insert_vals})"
            )
        finally:
            await client.adelete_table(stage_table)

    async def finalize_run(self, ctx: DestinationRunContext) -> None:
        """Publish a full refresh by swapping the staging table into place."""
        if not ctx.is_full_refresh:
            return

        _assert_safe_identifier(ctx.table_name, "table name")
        staging = staging_table_name(ctx)
        client = await self._make_client()

        async with client.connect():
            # `LIKE` takes a string literal, not an identifier, so `staging` is validated
            # above rather than backtick-escaped here.
            rows = await client.execute_query(
                f"SHOW TABLES IN {backtick(self._catalog)}.{backtick(self._schema)} LIKE '{staging}'",
            )
            if not rows:
                # Already swapped by an earlier attempt at this same final batch.
                return

            await client.execute_query(
                f"ALTER TABLE {self._qualified(staging)} DROP COLUMN IF EXISTS {backtick(BATCH_INDEX_COLUMN)}"
            )
            await client.execute_query(f"DROP TABLE IF EXISTS {self._qualified(ctx.table_name)}")
            await client.execute_query(
                f"ALTER TABLE {self._qualified(staging)} RENAME TO {self._qualified(ctx.table_name)}"
            )

    async def abort_run(self, ctx: DestinationRunContext) -> None:
        # The next run stages under its own id, so a leftover table costs storage only.
        _assert_safe_identifier(ctx.table_name, "table name")
        client = await self._make_client()
        async with client.connect():
            await client.adelete_table(staging_table_name(ctx))
