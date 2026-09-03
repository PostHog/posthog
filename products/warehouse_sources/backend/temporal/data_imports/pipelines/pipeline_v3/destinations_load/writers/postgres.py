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
  tables and not a source table with no monotonic column. (Redshift's `amerge_tables` puts no
  such condition on a merge, so the Redshift writer does use it.)
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
import csv
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, ClassVar

import psycopg
import pyarrow as pa
from psycopg import sql

from posthog.models.integration import Integration, PostgreSQLIntegration

from products.batch_exports.backend.temporal.destinations.postgres_batch_export import (
    Fields,
    PostgreSQLClient,
    PostgreSQLIntegrationNotFoundError,
    run_in_retryable_transaction,
)
from products.batch_exports.backend.temporal.pipeline.transformer import CSVStreamTransformer
from products.warehouse_sources.backend.temporal.data_imports.destinations.contracts import (
    BatchWriteOutcome,
    DestinationBatchContext,
    DestinationRunContext,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.destinations_load.writers.sql_types import (
    is_nested_type,
    postgres_type_for,
)

# Marks which batch of a run wrote a staged row, so re-applying a batch can delete exactly
# what its previous attempt wrote instead of the whole staging table.
BATCH_INDEX_COLUMN = "_ph_batch_index"

# Proof this writer created a table, so a sync never drops or merges into one the customer
# already had. `table_name` comes from the source's resource name, which a custom-source
# manifest controls, so without it any table sharing that name is fair game.
#
# Stored as a Postgres comment because those follow the table's OID, surviving the rename in
# `finalize_run`. Scoped by schema id because `table_name` collides across sources on purpose
# and ownership must not.
_OWNERSHIP_COMMENT = "posthog-warehouse-sync-owned"


def _owned_marker(schema_id: str) -> str:
    """Ownership marker scoped to the schema whose sync created the table."""
    return f"{_OWNERSHIP_COMMENT}:{schema_id}"


def _published_comment(schema_id: str, run_uuid: str) -> str:
    """Ownership marker plus the run that last published, so a replay can recognize itself."""
    return f"{_owned_marker(schema_id)}:{run_uuid}"


class UnrelatedTableExistsError(RuntimeError):
    """A sync would have replaced or mutated a table this writer never created."""


# Postgres truncates identifiers past this, dropping the end — which is where our suffixes go.
# A long `table_name` would therefore collapse its staging table, merge stage and index back
# onto the base name. Truncate the base ourselves so the suffix always survives.
_MAX_PG_IDENTIFIER_BYTES = 63


def _scoped_identifier(base: str, suffix: str) -> str:
    """Append `suffix` to `base`, truncating `base` first so `suffix` always survives
    Postgres's own 63-byte identifier truncation."""
    trimmed = base.encode()[: _MAX_PG_IDENTIFIER_BYTES - len(suffix)].decode(errors="ignore")
    return f"{trimmed}{suffix}"


def staging_table_name(ctx: DestinationRunContext) -> str:
    # Run-scoped, so two runs of the same table never share a staging table.
    return _scoped_identifier(ctx.table_name, f"__ph_stage_{ctx.run_uuid.replace('-', '')[:12]}")


def merge_stage_name(target: str, ctx: DestinationRunContext) -> str:
    # `target` is the live table on an incremental run, so it can already be at the identifier
    # limit. Reserve room for the suffix or the stage name truncates onto the live table, and
    # dropping the stage would drop it.
    return _scoped_identifier(target, f"__ph_merge_{ctx.run_uuid.replace('-', '')[:8]}")


def _to_json_text(value: Any, *, from_map: bool) -> str | None:
    if value is None:
        return None
    if from_map:
        # A map column reads back as key/value pairs rather than as a mapping.
        value = dict(value)
    # Dates, decimals and binaries can sit inside a struct, and none of them are JSON types.
    return json.dumps(value, default=str)


def json_encode_nested_columns(batch: pa.RecordBatch) -> pa.RecordBatch:
    """Replace every nested column with its JSON text.

    `sql_types` maps a list, struct or map onto JSONB, but the CSV transformer renders a list
    as a Postgres array literal and a dict as a Python repr, and JSONB accepts neither.
    """
    for index, field in enumerate(batch.schema):
        if not is_nested_type(field.type):
            continue

        encoded = [
            _to_json_text(value, from_map=pa.types.is_map(field.type)) for value in batch.column(index).to_pylist()
        ]
        batch = batch.set_column(index, pa.field(field.name, pa.string()), pa.array(encoded, type=pa.string()))

    return batch


class PostgresDestinationWriter:
    """Writes a run's batches into a Postgres table."""

    holds_sync_lock: ClassVar[bool] = False
    runs_post_load: ClassVar[bool] = False

    # The kind of integration a destination of this type is backed by. Loading any other kind
    # would hand this writer's client the credentials of a different service.
    integration_kind: ClassVar[str] = PostgreSQLIntegration.integration_kind

    def __init__(self, ctx: DestinationRunContext) -> None:
        self._ctx = ctx
        self._schema = (ctx.config or {}).get("schema") or "public"
        self._database = (ctx.config or {}).get("database") or "postgres"

    # --- connection -------------------------------------------------------------------

    def _client_from_integration(self, integration: Integration) -> PostgreSQLClient:
        # `from_inputs` accepts anything exposing credentials/authority/tls, which the
        # integration wrapper does, so the batch export path and this one resolve credentials
        # identically.
        return PostgreSQLClient.from_inputs(PostgreSQLIntegration(integration), database=self._database)

    async def _load_integration(self, integration_id: int) -> Integration:
        try:
            return await Integration.objects.aget(
                id=integration_id, team_id=self._ctx.team_id, kind=self.integration_kind
            )
        except Integration.DoesNotExist as err:
            # The same error batch exports raises, which its destinations never retry: a
            # deleted or re-kinded integration cannot be recovered by trying again.
            raise PostgreSQLIntegrationNotFoundError(
                f"'{self.integration_kind}' integration with id '{integration_id}' not found"
            ) from err

    async def _make_client(self) -> PostgreSQLClient:
        if self._ctx.integration_id is None:
            raise ValueError(f"Destination {self._ctx.destination_name} has no integration to connect with")

        integration = await self._load_integration(self._ctx.integration_id)
        return self._client_from_integration(integration)

    @asynccontextmanager
    async def _client(self) -> AsyncIterator[PostgreSQLClient]:
        client = await self._make_client()
        # `connect()` resolves and dials the integration's hostname with no connection-time
        # address validation or pinning, same as batch exports' own Postgres destination on
        # this same client. An editor-controlled hostname could DNS-rebind to a private address
        # between resolution and connect; closing that needs pinning inside `PostgreSQLClient`
        # itself (posthog#86986 review discussion), which this product can't reach into, so
        # every caller of this shared client is fixed together rather than patched here alone.
        async with client.connect():
            yield client

    @asynccontextmanager
    async def _write_cursor(self, client: PostgreSQLClient) -> AsyncIterator[psycopg.AsyncCursor]:
        """A cursor in a transaction of its own that is declared read-write.

        Every write path in batch exports declares this, because a cluster running with
        `default_transaction_read_only = on` rejects the statement otherwise. Postgres only
        accepts it as the first statement of a transaction, so each write gets its own.
        """
        async with client.connection.transaction():
            async with client.connection.cursor() as cursor:
                await cursor.execute("SET TRANSACTION READ WRITE")
                yield cursor

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
        self,
        client: PostgreSQLClient,
        table: str,
        schema: pa.Schema,
        *,
        with_batch_index: bool,
        primary_keys: list[str] | None = None,
    ) -> None:
        async with self._write_cursor(client) as cursor:
            await cursor.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(self._schema)))

        fields = self._fields_for(schema, with_batch_index=with_batch_index)
        # Declared at creation rather than added later, so the merge target carries its own
        # constraint. `_ensure_unique_index` still covers a table the customer already had,
        # which this never touches.
        key = [(name, type_name) for name, type_name in fields if name in set(primary_keys or ())]

        await client.acreate_table(
            self._schema,
            table,
            fields,
            exists_ok=True,
            primary_key=key or None,
        )

    async def _evolve_table(self, client: PostgreSQLClient, table: str, schema: pa.Schema) -> None:
        """Add columns the source has grown since the destination table was created."""
        existing = set(await client.aget_table_columns(self._schema, table))

        for field in schema:
            if field.name in existing:
                continue
            async with self._write_cursor(client) as cursor:
                await cursor.execute(
                    sql.SQL("ALTER TABLE {}.{} ADD COLUMN IF NOT EXISTS {} {}").format(
                        sql.Identifier(self._schema),
                        sql.Identifier(table),
                        sql.Identifier(field.name),
                        sql.SQL(self._column_type(field.type)),
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
            if full_refresh and await self._already_published(client, run):
                # This run's staging table is gone and the live table carries this run's
                # publish stamp, so the run finished. Re-creating a staging table from this
                # one batch and swapping it in would replace the whole table with it.
                return BatchWriteOutcome(rows_written=0)

            first = True
            async for batch in batches:
                if first:
                    # An incremental run writes straight into the live table, and a full
                    # refresh writes into what it treats as *its own* staging table — either
                    # way, a table that predates this sync and merely happens to share the
                    # generated name must be refused up front, before its schema is evolved or
                    # a row in it is touched. Reusing an unowned table as staging would mutate
                    # or delete unrelated data and, on the final batch, replace its ownership
                    # marker and swap it in under `finalize_run`'s nose. A full refresh's own
                    # table gets one further check at swap time, once the new data is known to
                    # be complete.
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

                    await self._ensure_table(
                        client,
                        target,
                        batch.schema,
                        with_batch_index=full_refresh,
                        primary_keys=list(run.primary_keys) if run.is_incremental and not full_refresh else None,
                    )
                    await self._evolve_table(client, target, batch.schema)
                    if full_refresh:
                        # This batch may be a re-apply after a crash, so clear whatever its
                        # previous attempt wrote before writing it again.
                        await self._delete_batch_rows(client, target, ctx.batch_index)
                        # Marked on the staging table, not the live one: the comment survives
                        # the rename in `finalize_run`, which is where it gets checked.
                        await self._mark_owned(client, target, run.schema_id)
                    elif not table_existed:
                        # A table this writer just created for an incremental run never gets
                        # renamed, so mark it in place rather than at swap time.
                        await self._mark_owned(client, target, run.schema_id)
                    first = False

                rows_written += await self._write_record_batch(client, target, batch, ctx, full_refresh=full_refresh)

        return BatchWriteOutcome(rows_written=rows_written)

    async def _delete_batch_rows(self, client: PostgreSQLClient, target: str, batch_index: int) -> None:
        async with self._write_cursor(client) as cursor:
            await cursor.execute(
                sql.SQL("DELETE FROM {}.{} WHERE {} = %s").format(
                    sql.Identifier(self._schema),
                    sql.Identifier(target),
                    sql.Identifier(self._batch_index_column),
                ),
                (batch_index,),
            )

    def _tsv_buffer(self, batch: pa.RecordBatch, column_names: list[str]) -> io.BytesIO:
        """Render a record batch as TSV, using the same transformer the batch export uses.

        The dialect has to be the one `copy_tsv_to_postgres` names in its COPY statement,
        which is CSV with a tab delimiter. Postgres CSV has no backslash escape, so a value
        holding a tab, a newline or a double quote only survives if the writer quotes it.
        """
        transformer = CSVStreamTransformer(
            field_names=column_names,
            delimiter="\t",
            quote_char='"',
            escape_char=None,
            line_terminator="\n",
            quoting=csv.QUOTE_STRINGS,
            include_inserted_at=False,
        )
        return io.BytesIO(transformer.write_record_batch(json_encode_nested_columns(batch)))

    async def _load_batch(
        self, client: PostgreSQLClient, table: str, batch: pa.RecordBatch, column_names: list[str]
    ) -> None:
        """Put one record batch into a table, whatever the dialect's bulk load is."""
        await client.copy_tsv_to_postgres(self._tsv_buffer(batch, column_names), self._schema, table, column_names)

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
            await self._load_batch(client, target, stamped, [*column_names, self._batch_index_column])
            return batch.num_rows

        if run.is_incremental and run.primary_keys:
            return await self._merge_batch(client, target, batch, column_names)

        await self._load_batch(client, target, batch, column_names)
        return batch.num_rows

    async def _merge_batch(
        self, client: PostgreSQLClient, target: str, batch: pa.RecordBatch, column_names: list[str]
    ) -> int:
        """Upsert a batch on the schema's primary keys, through a stage table."""
        run = self._ctx
        stage = merge_stage_name(target, run)

        await self._ensure_merge_stage(client, stage, batch.schema)
        await self._load_batch(client, stage, batch, column_names)
        await self._upsert_from_stage(client, target, stage, column_names, list(run.primary_keys))

        return batch.num_rows

    async def _ensure_merge_stage(self, client: PostgreSQLClient, stage: str, schema: pa.Schema) -> None:
        """Ready the run's stage table to receive one batch.

        Created once per run and emptied between batches rather than created and dropped per
        batch. A table per batch is not free on someone else's server: each one writes catalog
        rows that later have to be vacuumed, and vacuuming catalog tables can need locks.
        `abort_run` and `finalize_run` drop it.
        """
        await client.acreate_table(
            self._schema, stage, self._fields_for(schema, with_batch_index=False), exists_ok=True
        )
        # The stage outlives the batch that created it, so a column the source grew mid-run has
        # to reach it too, or the COPY names a column the stage does not have.
        await self._evolve_table(client, stage, schema)
        async with self._write_cursor(client) as cursor:
            # Not DELETE: the stage is rewritten wholesale every batch, so truncating skips the
            # dead rows a delete would leave for autovacuum.
            await cursor.execute(
                sql.SQL("TRUNCATE TABLE {}.{}").format(sql.Identifier(self._schema), sql.Identifier(stage))
            )

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

        async def upsert() -> None:
            async with client.connection.cursor() as cursor:
                await cursor.execute("SET TRANSACTION READ WRITE")
                await cursor.execute(statement)

        # A concurrent `INSERT ... ON CONFLICT` is the shape that raises SerializationFailure,
        # and this is the one statement here that two runs of different schemas can contend on.
        await run_in_retryable_transaction(client.connection, upsert)

    async def _ensure_unique_index(self, client: PostgreSQLClient, target: str, primary_keys: list[str]) -> None:
        """`ON CONFLICT` needs a unique constraint on the merge keys.

        A table this writer created already carries one, declared as its primary key. This
        covers the other case: a table the customer already had. `IF NOT EXISTS` matches on
        the index name, not on the columns, so without the check below a table with a primary
        key would carry a second unique index over the same columns and pay for it on every
        write.
        """
        if await self._has_unique_index_on(client, target, primary_keys):
            return

        async with self._write_cursor(client) as cursor:
            await cursor.execute(
                sql.SQL("CREATE UNIQUE INDEX IF NOT EXISTS {} ON {}.{} ({})").format(
                    # Same truncation hazard as the merge stage above: an untruncated suffix
                    # on a `target` already at the byte limit collapses onto `target`'s own
                    # truncated name, and `IF NOT EXISTS` then silently skips creating the
                    # index at all because a relation by that name (the table itself) exists.
                    sql.Identifier(_scoped_identifier(target, "__ph_pk")),
                    sql.Identifier(self._schema),
                    sql.Identifier(target),
                    sql.SQL(", ").join(sql.Identifier(c) for c in primary_keys),
                )
            )

    async def _has_unique_index_on(self, client: PostgreSQLClient, target: str, columns: list[str]) -> bool:
        """Whether some unique index already covers exactly these columns, in any order."""
        async with client.connection.cursor() as cursor:
            await cursor.execute(
                """
                SELECT array_agg(a.attname::text ORDER BY a.attname)
                FROM pg_index i
                JOIN pg_class c ON c.oid = i.indrelid
                JOIN pg_namespace n ON n.oid = c.relnamespace
                JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = ANY (i.indkey)
                WHERE i.indisunique AND c.relname = %(table)s AND n.nspname = %(schema)s
                GROUP BY i.indexrelid
                """,
                {"table": target, "schema": self._schema},
            )
            wanted = sorted(columns)
            return any(sorted(row[0] or []) == wanted for row in await cursor.fetchall())

    async def _mark_owned(self, client: PostgreSQLClient, table: str, schema_id: str) -> None:
        async with self._write_cursor(client) as cursor:
            # `COMMENT ON TABLE ... IS <text>` is a utility statement: Postgres's grammar
            # only accepts a string literal there, not a bind parameter, so this can't go
            # through the usual `%s` placeholder (it fails with a syntax error at `$1`).
            # `schema_id` is the schema's immutable id, never user-editable input, so inlining
            # it as a literal is safe the same way the fixed constant was.
            await cursor.execute(
                sql.SQL("COMMENT ON TABLE {}.{} IS {}").format(
                    sql.Identifier(self._schema), sql.Identifier(table), sql.Literal(_owned_marker(schema_id))
                )
            )

    async def _is_owned(self, client: PostgreSQLClient, table: str, schema_id: str) -> bool:
        # Not a plain `startswith`: schema ids are arbitrary strings, and one could be a
        # character-prefix of another ("abc" of "abc123"), which would let a table another
        # schema owns pass as owned here. Split on the marker's own `:` separators instead so
        # the owning schema id is compared for exact equality; a published table carries the
        # run uuid as a further segment after it, which this ignores.
        comment = await self._table_comment(client, table)
        if comment is None:
            return False
        marker, sep, rest = comment.partition(":")
        if marker != _OWNERSHIP_COMMENT or not sep:
            return False
        owner = rest.split(":", 1)[0]
        return owner == schema_id

    async def _table_comment(self, client: PostgreSQLClient, table: str) -> str | None:
        async with client.connection.cursor() as cursor:
            await cursor.execute(
                """
                SELECT d.description
                FROM pg_catalog.pg_description d
                JOIN pg_catalog.pg_class c ON c.oid = d.objoid AND d.objsubid = 0
                JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
                WHERE c.relname = %(table)s AND n.nspname = %(schema)s
                """,
                {"table": table, "schema": self._schema},
            )
            row = await cursor.fetchone()
            return row[0] if row else None

    async def _already_published(self, client: PostgreSQLClient, ctx: DestinationRunContext) -> bool:
        """Whether this run already swapped its staging table into place."""
        if await self._table_exists(client, staging_table_name(ctx)):
            return False
        if not await self._table_exists(client, ctx.table_name):
            return False
        return await self._table_comment(client, ctx.table_name) == _published_comment(ctx.schema_id, ctx.run_uuid)

    async def finalize_run(self, ctx: DestinationRunContext) -> None:
        """Publish a full refresh by swapping the staging table into place."""
        if not ctx.is_full_refresh:
            # An incremental run publishes as it goes, but its merge stage lives for the whole
            # run, so this is the point where it stops being needed.
            async with self._client() as client:
                await client.adelete_table(self._schema, merge_stage_name(ctx.table_name, ctx), not_found_ok=True)
            return

        staging = staging_table_name(ctx)

        async with self._client() as client:
            if not await self._table_exists(client, staging):
                # Already swapped by an earlier attempt at this same final batch.
                return

            if await self._table_exists(client, ctx.table_name) and not await self._is_owned(
                client, ctx.table_name, ctx.schema_id
            ):
                # A table with this name exists and this writer never created it. Refuse
                # rather than drop it: `table_name` comes from the source's resource name,
                # which a custom-source manifest controls, and a table that predates this
                # sync could be anything the customer already had in this schema.
                raise UnrelatedTableExistsError(
                    f'"{self._schema}"."{ctx.table_name}" already exists and was not created by this sync; '
                    "refusing to replace it with the full refresh's staging table."
                )

            async with self._write_cursor(client) as cursor:
                await cursor.execute(
                    sql.SQL("ALTER TABLE {}.{} DROP COLUMN IF EXISTS {}").format(
                        sql.Identifier(self._schema),
                        sql.Identifier(staging),
                        sql.Identifier(self._batch_index_column),
                    )
                )

            async with self._write_cursor(client) as cursor:
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
                # Stamp the run that published, so a redelivery of the final batch can tell
                # "already published" from "never started" and refuse to rebuild the table.
                await cursor.execute(
                    sql.SQL("COMMENT ON TABLE {}.{} IS {}").format(
                        sql.Identifier(self._schema),
                        sql.Identifier(ctx.table_name),
                        sql.Literal(_published_comment(ctx.schema_id, ctx.run_uuid)),
                    )
                )

    async def _table_exists(self, client: PostgreSQLClient, table: str) -> bool:
        # The probe batch exports uses. `information_schema.tables` would be the obvious
        # query, but it only exists on the leader node of a Redshift cluster, and Redshift
        # inherits this method.
        try:
            await client.aget_table_columns(self._schema, table)
        except psycopg.errors.UndefinedTable:
            return False
        return True

    async def abort_run(self, ctx: DestinationRunContext) -> None:
        """Drop whatever a run that will not finish left staged."""
        async with self._client() as client:
            await self._drop_run_scratch(client, ctx)

    async def _drop_run_scratch(self, client: PostgreSQLClient, ctx: DestinationRunContext) -> None:
        """Drop the scratch tables a run owns, once it can no longer need them."""
        await client.adelete_table(self._schema, staging_table_name(ctx), not_found_ok=True)
        await client.adelete_table(self._schema, merge_stage_name(ctx.table_name, ctx), not_found_ok=True)
