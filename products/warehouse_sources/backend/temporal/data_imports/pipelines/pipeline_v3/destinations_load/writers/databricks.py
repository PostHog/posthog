"""Delivering a run's batches to Databricks.

Connection handling, OAuth for the service principal, the reachability preflight, the retrying
connect, the statement timeouts, table creation and deletion, and the volume load all come from
batch exports' `DatabricksClient`. Rows load by putting a parquet file into a Databricks volume
and running `COPY INTO`, which is the path Databricks is built for, rather than binding rows one
at a time. Every statement written here goes through the same `handle_common_errors` the client
uses, so a stopped warehouse or a missing privilege is reported as itself rather than as a raw
driver error.

`DatabricksField` is just `(name, type)`, so the client's `acopy_into_table_from_volume` takes
the column types worked out here without going through a table abstraction.

The merge stays local: batch exports decides what to update from a version key, and a synced
source table has no monotonic column, so this matches on primary keys alone. That also means
`amerge_tables` cannot supply the schema evolution its `WITH SCHEMA EVOLUTION` would, so the
final table gains new source columns through `_evolve_table` instead.
"""

from __future__ import annotations

import io
import json
from collections.abc import AsyncIterator
from typing import ClassVar

import pyarrow as pa
import pyarrow.parquet as pq

from posthog.models.integration import Integration
from posthog.models.integration.databricks import DatabricksIntegration

from products.batch_exports.backend.temporal.destinations.databricks_batch_export import (
    FIVE_MINUTES,
    ONE_HOUR,
    ONE_MINUTE,
    DatabricksClient,
    DatabricksField,
    DatabricksIntegrationNotFoundError,
    handle_common_errors,
)
from products.warehouse_sources.backend.temporal.data_imports.destinations.contracts import (
    BatchWriteOutcome,
    DestinationBatchContext,
    DestinationRunContext,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.destinations_load.writers.merge_dedup import (
    dedupe_merge_source,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.destinations_load.writers.run_markers import (
    BATCH_INDEX_COLUMN,
    is_owned_by,
    is_published_by,
    owned_marker,
    published_marker,
    run_scope,
    stamp_batch_index,
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

# Server-side backstop. Every statement below is bounded client-side well within this, so it
# only catches a query the client-side timeout cannot reach, such as one whose connection went
# away, rather than letting it run on the customer's warehouse until something else notices.
STATEMENT_TIMEOUT_SECONDS = ONE_HOUR + ONE_MINUTE


def databricks_type_for(arrow_type: pa.DataType) -> str:
    mapped = _DATABRICKS_BY_ARROW.get(arrow_type)
    if mapped is not None:
        return mapped
    if pa.types.is_timestamp(arrow_type):
        return "TIMESTAMP"
    if pa.types.is_decimal(arrow_type):
        return f"DECIMAL({arrow_type.precision}, {arrow_type.scale})"
    if pa.types.is_nested(arrow_type):
        # Stored as JSON text rather than a typed STRUCT: a nested shape that grows a field
        # would otherwise need a schema change on every source change. `json_encode_nested`
        # is what turns the values into that text before they reach parquet.
        return "STRING"
    return "STRING"


def json_encode_nested(batch: pa.RecordBatch) -> pa.RecordBatch:
    """Render nested columns as the JSON text `databricks_type_for` maps them to.

    Parquet carries a list or a struct in its own shape, so without this the file holds an
    array where the column it is copied into holds a string.
    """
    if not any(pa.types.is_nested(field.type) for field in batch.schema):
        return batch

    columns: list[pa.Array] = []
    fields: list[pa.Field] = []
    for index, field in enumerate(batch.schema):
        column = batch.column(index)
        if pa.types.is_nested(field.type):
            column = pa.array(
                [None if value is None else json.dumps(value, default=str) for value in column.to_pylist()],
                type=pa.string(),
            )
            field = pa.field(field.name, pa.string(), field.nullable)
        columns.append(column)
        fields.append(field)

    return pa.RecordBatch.from_arrays(columns, schema=pa.schema(fields))


def backtick(name: str) -> str:
    escaped = name.replace("`", "``")
    return f"`{escaped}`"


def sql_literal(value: str) -> str:
    escaped = value.replace("'", "''")
    return f"'{escaped}'"


# batch exports' DatabricksClient builds COPY INTO / PUT statements by interpolating the
# table name, volume path and column names it is given with no escaping of its own (a raw
# backtick-wrapped identifier, and a single-quoted path). Batch exports only ever passes it
# names it derived internally, so that was never reachable with attacker-controlled input.
# Here the table name and volume come from a destination's own config and the column names
# come from the source's Arrow schema, both of which a team member (or, through a shared
# source, its schema) controls. Reject anything that could break out of either quoting
# context rather than teach the shared client to escape a case it was never built for.
_UNSAFE_IDENTIFIER_CHARS = ("`", "'", '"', "\\", "\n", "\r", "\x00")


def _assert_safe_identifier(value: str, what: str) -> str:
    if not value or any(ch in value for ch in _UNSAFE_IDENTIFIER_CHARS):
        raise ValueError(f"Unsafe Databricks {what}: {value!r}")
    return value


def staging_table_name(ctx: DestinationRunContext) -> str:
    return f"{ctx.table_name}__ph_stage_{run_scope(ctx.run_uuid)}"


# The ownership and publish markers are stored as Databricks table comments:
# `ALTER TABLE ... RENAME` keeps a table's comment, so the marker set on a full refresh's
# staging table survives into `finalize_run`'s swap.


class UnrelatedTableExistsError(RuntimeError):
    """A sync would have replaced or mutated a table this writer never created."""


def fields_for(schema: pa.Schema, *, with_batch_index: bool) -> list[DatabricksField]:
    # Column names come from the source's own Arrow schema, so they get the same
    # rejection as destination config before reaching the unescaped shared client calls.
    fields: list[DatabricksField] = [
        (_assert_safe_identifier(f.name, "column name"), databricks_type_for(f.type)) for f in schema
    ]
    if with_batch_index:
        fields.append((BATCH_INDEX_COLUMN, "INT"))
    return fields


async def _load_integration(integration_id: int, team_id: int) -> DatabricksIntegration:
    try:
        integration = await Integration.objects.aget(
            id=integration_id, team_id=team_id, kind=Integration.IntegrationKind.DATABRICKS
        )
    except Integration.DoesNotExist:
        raise DatabricksIntegrationNotFoundError(
            f"Databricks integration with ID '{integration_id}' not found for team '{team_id}'"
        )
    return DatabricksIntegration(integration)


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

        creds = await _load_integration(self._ctx.integration_id, self._ctx.team_id)

        return DatabricksClient(
            server_hostname=creds.server_hostname,
            http_path=self._http_path,
            client_id=creds.client_id,
            client_secret=creds.client_secret,
            catalog=self._catalog,
            schema=self._schema,
            statement_timeout_seconds=STATEMENT_TIMEOUT_SECONDS,
        )

    # --- statements -------------------------------------------------------------------

    def _qualified(self, table: str) -> str:
        return f"{backtick(self._catalog)}.{backtick(self._schema)}.{backtick(table)}"

    def _volume_path(self) -> str:
        return f"/Volumes/{self._catalog}/{self._schema}/{self._volume}"

    async def _evolve_table(self, client: DatabricksClient, table: str, fields: list[DatabricksField]) -> None:
        """Add columns the source has grown. Additive only, same as the other SQL writers.

        `COPY INTO` evolves the table it loads into, but the merge path loads into a scratch
        table, so on that path this is the only thing that carries a new source column through
        to the final table.
        """
        existing = {name.lower() for name in await client.aget_table_columns(table)}
        if not existing:
            # No columns means no table, and the caller has just created it.
            return

        missing = [(name, type_name) for name, type_name in fields if name.lower() not in existing]
        if not missing:
            return

        additions = ", ".join(f"{backtick(name)} {type_name}" for name, type_name in missing)
        async with handle_common_errors(f"ALTER TABLE {table} ADD COLUMNS", FIVE_MINUTES):
            await client.execute_query(
                f"ALTER TABLE {self._qualified(table)} ADD COLUMNS ({additions})",
                fetch_results=False,
                timeout=FIVE_MINUTES,
            )

    # --- ownership ----------------------------------------------------------------------

    async def _table_exists(self, client: DatabricksClient, table: str) -> bool:
        # `aget_table_columns` is the existence probe the rest of this file already uses: no
        # columns means no table.
        return bool(await client.aget_table_columns(table))

    async def _table_comment(self, client: DatabricksClient, table: str) -> str | None:
        async with handle_common_errors(f"SELECT comment FOR {table}", ONE_MINUTE):
            # Matched case-insensitively because Unity Catalog stores schema and table names
            # lowercased, while `self._schema` and `table` carry whatever case the destination
            # config and the source's resource name gave them. An exact match would find no row
            # for an uppercase name, so `_is_owned` would report a table this writer created as
            # unowned and every run of it would raise `UnrelatedTableExistsError`. The existence
            # probe next to this one matches case-insensitively already, which is what makes the
            # two disagree.
            rows = await client.execute_query(
                f"SELECT comment FROM {backtick(self._catalog)}.information_schema.tables "
                f"WHERE lower(table_schema) = {sql_literal(self._schema.lower())} "
                f"AND lower(table_name) = {sql_literal(table.lower())}",
                timeout=ONE_MINUTE,
            )
        if not rows:
            return None
        return rows[0][0]

    async def _is_owned(self, client: DatabricksClient, table: str, schema_id: str) -> bool:
        return is_owned_by(await self._table_comment(client, table), schema_id)

    async def _already_published(self, client: DatabricksClient, ctx: DestinationRunContext) -> bool:
        """Whether this run already swapped its staging table into place."""
        if await self._table_exists(client, staging_table_name(ctx)):
            return False
        if not await self._table_exists(client, ctx.table_name):
            return False
        return is_published_by(await self._table_comment(client, ctx.table_name), ctx.schema_id, ctx.run_uuid)

    async def _set_comment(self, client: DatabricksClient, table: str, marker: str) -> None:
        async with handle_common_errors(f"COMMENT ON TABLE {table}", FIVE_MINUTES):
            await client.execute_query(
                f"COMMENT ON TABLE {self._qualified(table)} IS {sql_literal(marker)}",
                fetch_results=False,
                timeout=FIVE_MINUTES,
            )

    async def _mark_owned(self, client: DatabricksClient, table: str, schema_id: str) -> None:
        await self._set_comment(client, table, owned_marker(schema_id))

    async def _claim_table(self, client: DatabricksClient, table: str, schema_id: str) -> bool:
        """Refuse to touch `table` unless this call creates it or a prior one already owns it.

        Returns whether the table is new, so the caller knows to mark it once created.
        """
        existed = await self._table_exists(client, table)
        if existed and not await self._is_owned(client, table, schema_id):
            raise UnrelatedTableExistsError(
                f"'{table}' already exists and was not created by this sync; refusing to write into it."
            )
        return not existed

    # --- writer protocol ----------------------------------------------------------------

    async def prepare_run(self, ctx: DestinationRunContext) -> None:
        return None

    async def write_batch(
        self, batches: AsyncIterator[pa.RecordBatch], ctx: DestinationBatchContext
    ) -> BatchWriteOutcome:
        run = ctx.run
        full_refresh = run.is_full_refresh
        target = _assert_safe_identifier(staging_table_name(run) if full_refresh else run.table_name, "table name")

        client = await self._make_client()
        rows_written = 0

        async with client.connect():
            # The volume is named by the destination's own config, so it may well be one the
            # user already had and holds files this run knows nothing about. It is created if
            # missing and never dropped. Batch exports can drop its volume because it invents a
            # private per-attempt name; a shared, stable one would be pulled out from under
            # another schema's in-flight upload.
            await client.acreate_volume(self._volume)

            if full_refresh and await self._already_published(client, run):
                # This run's staging table is gone and the live table carries this run's publish
                # stamp, so the run finished. Re-creating a staging table from this one batch and
                # swapping it in would replace the whole table with it.
                return BatchWriteOutcome(rows_written=0)

            first = True
            chunk = 0
            async for batch in batches:
                if batch.num_rows == 0:
                    continue

                stamped = stamp_batch_index(batch, ctx.batch_index) if full_refresh else batch
                fields = fields_for(batch.schema, with_batch_index=full_refresh)

                if first:
                    # A table sharing `target`'s name may predate this sync (`target` is
                    # either the destination table itself, or a per-run staging name that
                    # could in principle collide). Refuse to evolve, load into or later drop
                    # one this writer never created.
                    is_new = await self._claim_table(client, target, run.schema_id)
                    await client.acreate_table(table_name=target, fields=fields)
                    await self._evolve_table(client, target, fields)
                    if is_new:
                        await self._mark_owned(client, target, run.schema_id)
                    if full_refresh:
                        # This batch may be a re-apply, so clear what its previous attempt wrote.
                        async with handle_common_errors(f"DELETE FROM {target}", FIVE_MINUTES):
                            await client.execute_query(
                                f"DELETE FROM {self._qualified(target)} "
                                f"WHERE {backtick(BATCH_INDEX_COLUMN)} = {int(ctx.batch_index)}",
                                fetch_results=False,
                                timeout=FIVE_MINUTES,
                            )
                    first = False

                if run.is_incremental and run.primary_keys and not full_refresh:
                    rows_written += await self._merge_chunk(
                        client, target, stamped, fields, list(run.primary_keys), run.run_uuid, ctx.batch_index, chunk
                    )
                else:
                    await self._copy_chunk(client, target, stamped, fields, run.run_uuid, ctx.batch_index, chunk)
                    rows_written += batch.num_rows
                chunk += 1

        return BatchWriteOutcome(rows_written=rows_written)

    async def _copy_chunk(
        self,
        client: DatabricksClient,
        target: str,
        batch: pa.RecordBatch,
        fields: list[DatabricksField],
        run_uuid: str,
        batch_index: int,
        chunk: int,
    ) -> None:
        """PUT one record batch into the volume as parquet, then COPY INTO the table."""
        buffer = io.BytesIO()
        pq.write_table(pa.Table.from_batches([json_encode_nested(batch)]), buffer)
        buffer.seek(0)

        # This writer does not hold the sync lock (`holds_sync_lock` is False), so two runs of
        # the same table's incremental sync_type can be in flight together. Both write into the
        # same `target` (the live table), so without `run_uuid` here their staged files would
        # share one name and one run's rows could be COPY'd by the other, or removed out from
        # under it once loaded.
        file_name = f"ph_{run_scope(run_uuid)}_{batch_index}_{chunk}.parquet"
        volume_path = f"{self._volume_path()}/{target}"

        await client.aput_file_stream_to_volume(buffer, volume_path, file_name)
        await client.acopy_into_table_from_volume(
            target,
            f"{volume_path}/{file_name}",
            fields,
            with_schema_evolution=True,
        )
        await self._remove_staged_file(client, f"{volume_path}/{file_name}")

    async def _remove_staged_file(self, client: DatabricksClient, path: str) -> None:
        """Drop a file whose rows have landed.

        Nothing else clears them: the volume outlives the run. A file left behind costs the
        user storage and nothing else, so a failure here must not fail a batch that loaded.
        """
        try:
            async with handle_common_errors(f"REMOVE '{path}'", ONE_MINUTE):
                await client.execute_query(f"REMOVE '{path}'", fetch_results=False, timeout=ONE_MINUTE)
        except Exception as err:
            client.logger.warning("Could not remove staged file '%s': %s", path, err)

    async def _merge_chunk(
        self,
        client: DatabricksClient,
        target: str,
        batch: pa.RecordBatch,
        fields: list[DatabricksField],
        primary_keys: list[str],
        run_uuid: str,
        batch_index: int,
        chunk: int,
    ) -> int:
        """Upsert on the primary keys, staging the chunk in a scratch table first."""
        # Delta rejects a `MERGE` whose source matches one target row more than once
        # (`DELTA_MULTIPLE_SOURCE_ROW_MATCHING_TARGET_ROW_IN_MERGE`), and it rejects it again on
        # every retry.
        batch = dedupe_merge_source(batch, primary_keys)
        columns = list(batch.schema.names)
        # Run-scoped for the same reason as the staged file in `_copy_chunk`: two overlapping
        # runs of this table must not merge from, or drop, each other's scratch table.
        stage_table = f"{target}__ph_merge_{run_scope(run_uuid)}_{batch_index}_{chunk}"

        async with client.managed_table(stage_table, fields, delete=True):
            await self._copy_chunk(client, stage_table, batch, fields, run_uuid, batch_index, chunk)

            on_clause = " AND ".join(f"target.{backtick(k)} = source.{backtick(k)}" for k in primary_keys)
            updates = [c for c in columns if c not in primary_keys]
            set_clause = ", ".join(f"target.{backtick(c)} = source.{backtick(c)}" for c in updates)
            insert_cols = ", ".join(backtick(c) for c in columns)
            insert_vals = ", ".join(f"source.{backtick(c)}" for c in columns)

            matched = f"WHEN MATCHED THEN UPDATE SET {set_clause} " if updates else ""
            async with handle_common_errors(f"MERGE INTO {target}", ONE_HOUR):
                await client.execute_query(
                    f"MERGE INTO {self._qualified(target)} AS target "
                    f"USING {self._qualified(stage_table)} AS source ON {on_clause} "
                    f"{matched}"
                    f"WHEN NOT MATCHED THEN INSERT ({insert_cols}) VALUES ({insert_vals})",
                    fetch_results=False,
                    timeout=ONE_HOUR,
                )

        return batch.num_rows

    async def finalize_run(self, ctx: DestinationRunContext) -> None:
        """Publish a full refresh by swapping the staging table into place."""
        if not ctx.is_full_refresh:
            return

        _assert_safe_identifier(ctx.table_name, "table name")
        staging = staging_table_name(ctx)
        client = await self._make_client()

        async with client.connect():
            if not await client.aget_table_columns(staging):
                # No columns means no table: already swapped by an earlier attempt at this
                # same final batch.
                return

            if await self._table_exists(client, ctx.table_name) and not await self._is_owned(
                client, ctx.table_name, ctx.schema_id
            ):
                # A table with this name exists and this writer never created it. Refuse
                # rather than drop it: `table_name` comes from the source's resource name,
                # which a custom-source manifest controls, and a table that predates this
                # sync could be anything the customer already had in this schema.
                raise UnrelatedTableExistsError(
                    f"'{ctx.table_name}' already exists and was not created by this sync; "
                    "refusing to replace it with the full refresh's staging table."
                )

            async with handle_common_errors(f"ALTER TABLE {staging} DROP COLUMN", FIVE_MINUTES):
                await client.execute_query(
                    f"ALTER TABLE {self._qualified(staging)} DROP COLUMN IF EXISTS {backtick(BATCH_INDEX_COLUMN)}",
                    fetch_results=False,
                    timeout=FIVE_MINUTES,
                )
            # Stamp the run that published on the staging table, before it swaps into place.
            # The comment survives the rename below, so the table is never visible under its
            # live name without the marker already on it. Stamping after the rename would leave
            # a crash window where the swap completes but the marker never lands, and a
            # redelivered final batch would then rebuild staging from just that batch and
            # publish over the table that already holds the complete data.
            await self._set_comment(client, staging, published_marker(ctx.schema_id, ctx.run_uuid))
            await client.adelete_table(ctx.table_name)
            async with handle_common_errors(f"ALTER TABLE {staging} RENAME TO {ctx.table_name}", FIVE_MINUTES):
                await client.execute_query(
                    f"ALTER TABLE {self._qualified(staging)} RENAME TO {self._qualified(ctx.table_name)}",
                    fetch_results=False,
                    timeout=FIVE_MINUTES,
                )

    async def abort_run(self, ctx: DestinationRunContext) -> None:
        # The next run stages under its own id, so a leftover table costs storage only.
        _assert_safe_identifier(ctx.table_name, "table name")
        client = await self._make_client()
        async with client.connect():
            await client.adelete_table(staging_table_name(ctx))
