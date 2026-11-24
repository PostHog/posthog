"""Delivering a run's batches to MotherDuck.

MotherDuck is DuckDB served from the cloud, so this writer drives the ordinary `duckdb` package
through the connection helper the MotherDuck source already uses. Batches never pass through a
file: each record batch is registered on the connection as an Arrow view, and DuckDB reads it
straight from memory.

The shape follows the other SQL writers:

- A full refresh writes into a per-run staging table and swaps it into place on the final batch,
  so the live table holds the previous run's data until the new one is complete. DuckDB runs DDL
  inside a transaction, so the swap is one atomic step rather than a drop followed by a rename.
- An incremental run merges each batch on the schema's primary keys with `MERGE INTO`, which
  needs no unique index. That lets a sync merge into a table the customer created themselves.
- Column types come from DuckDB's own Arrow mapping, after `duckdb_compatible_batch` replaces the
  two types it cannot take. Schema evolution is additive.

DuckDB is synchronous, so every statement runs in a worker thread on a connection opened for that
one unit of work.
"""

from __future__ import annotations

import re
import asyncio
import functools
import threading
from collections.abc import AsyncIterator, Callable, Iterator
from concurrent.futures import (
    Future,
    TimeoutError as FutureTimeoutError,
)
from contextlib import contextmanager
from typing import ClassVar, TypeVar
from uuid import uuid4

import duckdb
import pyarrow as pa

from posthog.integrations import IntegrationKind, IntegrationManager, IntegrationNotFound
from posthog.models.integration.motherduck import MotherDuckIntegration

from products.warehouse_sources.backend.temporal.data_imports.destinations.contracts import (
    BatchWriteOutcome,
    DestinationBatchContext,
    DestinationRunContext,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.destinations_load.errors import (
    MISSING_INTEGRATION_DETAIL,
    DestinationConfigurationError,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import error_message_matches
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql import AnsiIdentifierQuoter
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.identifiers import (
    InvalidIdentifierError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.motherduck.motherduck import (
    MOTHERDUCK_TRANSIENT_ERRORS,
    build_motherduck_connection_string,
    connect as connect_motherduck,
)

T = TypeVar("T")

# Opens a connection whose current database is the destination's. Tests pass one that opens a
# local DuckDB file.
MotherDuckConnector = Callable[[], duckdb.DuckDBPyConnection]

DEFAULT_SCHEMA = "main"

# The name each record batch is registered under on its connection.
_SOURCE_VIEW = "__ph_source_batch"

# DuckDB has no identifier length limit, but MotherDuck shows names in a UI and other clients
# truncate long ones. Keep the run suffix intact the same way the Postgres writer does.
_MAX_IDENTIFIER_LENGTH = 255

_QUOTER = AnsiIdentifierQuoter()

# Every statement a writer runs gets this long before its connection is interrupted. A stalled
# connection otherwise holds the batch lease forever, so its retries never start.
OPERATION_TIMEOUT_SECONDS = 30 * 60

# Records which record batches of an append run are already in the destination, so a redelivered
# batch is not inserted twice. One row per record batch, written in the insert's own transaction.
RECEIPTS_TABLE = "__ph_sync_receipts"

INVALID_DATABASE_DETAIL = "The database name is missing or not valid. Check the database on the destination."
AUTHENTICATION_FAILED_DETAIL = (
    "MotherDuck refused the access token. Create a new access token in MotherDuck, update the "
    "integration, then run the sync again."
)
UNKNOWN_DATABASE_DETAIL = (
    "The database does not exist in this MotherDuck account. Check the database name on the destination, "
    "then run the sync again."
)
READ_ONLY_DETAIL = (
    "The access token or database cannot be written to. Use a read-write token and a database you own, "
    "not a share, then run the sync again."
)
COMPUTE_LIMIT_DETAIL = (
    "Your MotherDuck plan has reached its compute limit. Upgrade the plan or wait for the limit to reset, "
    "then run the sync again."
)

# Each one fails the same way on every attempt. Matched on the lowercased message, because DuckDB
# gives these no error class of their own. Text that matches none of them is retried.
_CONFIGURATION_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"unauthenticated|invalid token|jwt|authenticat"), AUTHENTICATION_FAILED_DETAIL),
    (re.compile(r"database .*(not found|does not exist)|no database.*found"), UNKNOWN_DATABASE_DETAIL),
    (re.compile(r"read[- ]only|cannot write to a share|permission denied"), READ_ONLY_DETAIL),
    (re.compile(r"compute limit|out of compute"), COMPUTE_LIMIT_DETAIL),
)


class UnrelatedTableExistsError(RuntimeError):
    """A sync would have replaced or mutated a table this writer never created."""


def configuration_error_detail(err: BaseException) -> str | None:
    """What the customer must fix when `err` stops every attempt, or None to retry.

    The source's `connect` replaces the driver's message with its own, so the driver error it
    wraps is read too.
    """
    message = " ".join(str(e) for e in (err, err.__cause__) if e is not None)
    # MotherDuck reports itself unreachable with the same exception class a bad token gets, so its
    # own outage wordings decide first.
    if error_message_matches(message, MOTHERDUCK_TRANSIENT_ERRORS):
        return None
    lowered = message.lower()
    for pattern, detail in _CONFIGURATION_PATTERNS:
        if pattern.search(lowered):
            return detail
    return None


def _duckdb_compatible_type(arrow_type: pa.DataType) -> pa.DataType:
    """The type DuckDB can store for `arrow_type`.

    Two Arrow types do not map:
    - An all-null column becomes INTEGER, so a later batch with text in it could not load. Text
      takes any later value.
    - DuckDB refuses `decimal256`. A precision DuckDB can hold fits `decimal128`; a larger one is
      kept exactly as text.
    """
    if pa.types.is_null(arrow_type):
        return pa.string()
    if pa.types.is_decimal256(arrow_type):
        if arrow_type.precision <= 38:
            return pa.decimal128(arrow_type.precision, arrow_type.scale)
        return pa.string()
    if pa.types.is_list(arrow_type):
        return pa.list_(_duckdb_compatible_field(arrow_type.value_field))
    if pa.types.is_large_list(arrow_type):
        return pa.large_list(_duckdb_compatible_field(arrow_type.value_field))
    if pa.types.is_fixed_size_list(arrow_type):
        return pa.list_(_duckdb_compatible_field(arrow_type.value_field), arrow_type.list_size)
    if pa.types.is_map(arrow_type):
        return pa.map_(_duckdb_compatible_type(arrow_type.key_type), _duckdb_compatible_type(arrow_type.item_type))
    if pa.types.is_struct(arrow_type):
        return pa.struct([_duckdb_compatible_field(arrow_type.field(i)) for i in range(arrow_type.num_fields)])
    return arrow_type


def _duckdb_compatible_field(field: pa.Field) -> pa.Field:
    return field.with_type(_duckdb_compatible_type(field.type))


def duckdb_compatible_batch(batch: pa.RecordBatch) -> pa.RecordBatch:
    """Cast `batch` to types DuckDB stores without loss, or return it unchanged."""
    schema = pa.schema([_duckdb_compatible_field(field) for field in batch.schema])
    if schema.equals(batch.schema):
        return batch
    return batch.cast(schema)


def _scoped_identifier(base: str, suffix: str) -> str:
    return f"{base[: _MAX_IDENTIFIER_LENGTH - len(suffix)]}{suffix}"


def staging_table_name(ctx: DestinationRunContext) -> str:
    return _scoped_identifier(ctx.table_name, f"__ph_stage_{run_scope(ctx.run_uuid)}")


def _quote(identifier: str) -> str:
    return _QUOTER.quote(identifier)


PROBE_TABLE_PREFIX = "posthog_destination_check"

# What `probe_write_access` reports, keyed by the configuration error behind it.
_PROBE_FAILURES: dict[str, str] = {
    AUTHENTICATION_FAILED_DETAIL: "authentication",
    UNKNOWN_DATABASE_DETAIL: "unknown_database",
    READ_ONLY_DETAIL: "missing_privilege",
}


# Probes run in the web process, and a stalled MotherDuck can keep one blocked past its deadline.
# A slot is held until the probe's thread really exits, so stalls cannot pile up threads without
# limit.
MAX_CONCURRENT_PROBES = 4
_PROBE_SLOTS = threading.BoundedSemaphore(MAX_CONCURRENT_PROBES)


def _interrupt(connections: list[duckdb.DuckDBPyConnection]) -> None:
    for connection in connections:
        try:
            connection.interrupt()
        except duckdb.Error:
            pass


def probe_write_access(access_token: str, database: str, schema: str, *, timeout_seconds: float) -> str | None:
    """Check that the token can create tables where the writer will, before any sync runs.

    Creates the schema when it is missing, as the writer does, then creates and drops a scratch
    table with a random name. Returns None on success, or `authentication`, `unknown_database`,
    `missing_privilege`, `unreachable` or `busy`.
    """
    try:
        if not database:
            raise ValueError("Database is missing")
        build_motherduck_connection_string(database, access_token)
        quoted_schema = _quote(schema or DEFAULT_SCHEMA)
    except (ValueError, InvalidIdentifierError):
        return "unknown_database"
    table = f"{quoted_schema}.{_quote(f'{PROBE_TABLE_PREFIX}_{uuid4().hex[:12]}')}"

    if not _PROBE_SLOTS.acquire(blocking=False):
        return "busy"

    future: Future[None] = Future()
    opened: list[duckdb.DuckDBPyConnection] = []

    def probe() -> None:
        try:
            connection = connect_motherduck(access_token, database, read_only=False)
            opened.append(connection)
            try:
                connection.execute(f"CREATE SCHEMA IF NOT EXISTS {quoted_schema}")
                connection.execute(f"CREATE TABLE {table} (id INTEGER)")
                connection.execute(f"DROP TABLE IF EXISTS {table}")
            finally:
                connection.close()
            future.set_result(None)
        except BaseException as error:
            future.set_exception(error)
        finally:
            _PROBE_SLOTS.release()

    try:
        threading.Thread(target=probe, daemon=True, name="motherduck-destination-probe").start()
    except BaseException:
        _PROBE_SLOTS.release()
        raise

    try:
        future.result(timeout=timeout_seconds)
    except FutureTimeoutError:
        # DuckDB's connect takes no timeout, but a statement in flight can be interrupted.
        _interrupt(opened)
        return "unreachable"
    except Exception as error:
        return _PROBE_FAILURES.get(configuration_error_detail(error) or "", "unreachable")
    return None


class MotherDuckDestinationWriter:
    """Writes a run's batches into a MotherDuck table."""

    holds_sync_lock: ClassVar[bool] = False
    runs_post_load: ClassVar[bool] = False

    integration_kind: ClassVar[str] = IntegrationKind.MOTHERDUCK.value

    def __init__(
        self,
        ctx: DestinationRunContext,
        *,
        connector: MotherDuckConnector | None = None,
        operation_timeout_seconds: float = OPERATION_TIMEOUT_SECONDS,
    ) -> None:
        self._ctx = ctx
        config = ctx.config or {}
        self._database: str = str(config.get("database") or "").strip()
        self._schema: str = str(config.get("schema") or "").strip() or DEFAULT_SCHEMA
        self._connector = connector
        self._operation_timeout_seconds = operation_timeout_seconds

    # --- connection -------------------------------------------------------------------

    async def _access_token(self) -> str:
        if self._ctx.integration_id is None:
            raise DestinationConfigurationError(self._ctx.destination_name, MISSING_INTEGRATION_DETAIL)
        try:
            integration = await IntegrationManager.kinds(self.integration_kind).aget(
                self._ctx.team_id, self._ctx.integration_id
            )
        except IntegrationNotFound as err:
            raise DestinationConfigurationError(self._ctx.destination_name, MISSING_INTEGRATION_DETAIL) from err

        token = MotherDuckIntegration(integration).access_token
        if not token:
            raise DestinationConfigurationError(self._ctx.destination_name, MISSING_INTEGRATION_DETAIL)
        return token

    async def _resolve_connector(self) -> MotherDuckConnector:
        if self._connector is not None:
            return self._connector

        token = await self._access_token()
        database = self._database

        def connect() -> duckdb.DuckDBPyConnection:
            # An empty name would open the account-wide `md:` connection, which has no single
            # database to write into, so it is refused here rather than at the first CREATE.
            try:
                if not database:
                    raise ValueError("Database is missing")
                build_motherduck_connection_string(database, token)
            except ValueError as err:
                raise DestinationConfigurationError(self._ctx.destination_name, INVALID_DATABASE_DETAIL) from err
            return connect_motherduck(token, database, read_only=False)

        return connect

    @contextmanager
    def _configuration_errors(self) -> Iterator[None]:
        """Turn an error that no retry can fix into a `DestinationConfigurationError`."""
        try:
            yield
        except DestinationConfigurationError:
            raise
        except Exception as err:
            detail = configuration_error_detail(err)
            if detail is not None:
                raise DestinationConfigurationError(self._ctx.destination_name, detail) from err
            raise

    async def _run(self, work: Callable[[duckdb.DuckDBPyConnection], T]) -> T:
        connector = await self._resolve_connector()
        opened: list[duckdb.DuckDBPyConnection] = []

        def run() -> T:
            with self._configuration_errors():
                connection = connector()
                opened.append(connection)
                try:
                    return work(connection)
                finally:
                    connection.close()

        try:
            return await asyncio.wait_for(asyncio.to_thread(run), timeout=self._operation_timeout_seconds)
        except TimeoutError:
            # The thread keeps running until DuckDB notices the interrupt and rolls back. The
            # batch fails here, so the consumer can retry it.
            _interrupt(opened)
            raise TimeoutError(
                f"MotherDuck did not finish within {self._operation_timeout_seconds:g} seconds"
            ) from None

    # --- statements -------------------------------------------------------------------

    def _qualified(self, table: str) -> str:
        return f"{_quote(self._schema)}.{_quote(table)}"

    def _table_comment(self, connection: duckdb.DuckDBPyConnection, table: str) -> tuple[bool, str | None]:
        """Whether `table` exists in the destination schema, and its comment."""
        row = connection.execute(
            # DuckDB resolves identifiers without regard to case, even quoted ones, so a lookup
            # that compared case would miss the table a statement then acts on.
            "SELECT comment FROM duckdb_tables() WHERE database_name = current_database() "
            "AND lower(schema_name) = lower(?) AND lower(table_name) = lower(?)",
            [self._schema, table],
        ).fetchone()
        if row is None:
            return False, None
        return True, row[0]

    def _set_comment(self, connection: duckdb.DuckDBPyConnection, table: str, comment: str) -> None:
        # `COMMENT ON` only takes a string literal, not a parameter. The comment is built from
        # the schema id and run uuid, never from user input, but it is escaped all the same.
        literal = "'" + comment.replace("'", "''") + "'"
        connection.execute(f"COMMENT ON TABLE {self._qualified(table)} IS {literal}")

    def _ensure_table(self, connection: duckdb.DuckDBPyConnection, table: str) -> None:
        connection.execute(f"CREATE SCHEMA IF NOT EXISTS {_quote(self._schema)}")
        connection.execute(
            f"CREATE TABLE IF NOT EXISTS {self._qualified(table)} AS SELECT * FROM {_quote(_SOURCE_VIEW)} LIMIT 0"
        )

    def _evolve_table(self, connection: duckdb.DuckDBPyConnection, table: str) -> None:
        """Add columns the source has grown. Additive only, same as the other SQL writers."""
        existing = {
            row[0].lower()
            for row in connection.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_catalog = current_database() "
                "AND lower(table_schema) = lower(?) AND lower(table_name) = lower(?)",
                [self._schema, table],
            ).fetchall()
        }
        for name, column_type, *_ in connection.execute(f"DESCRIBE SELECT * FROM {_quote(_SOURCE_VIEW)}").fetchall():
            if name.lower() in existing:
                continue
            connection.execute(
                f"ALTER TABLE {self._qualified(table)} ADD COLUMN IF NOT EXISTS {_quote(name)} {column_type}"
            )

    def _insert(self, connection: duckdb.DuckDBPyConnection, table: str) -> None:
        connection.execute(f"INSERT INTO {self._qualified(table)} BY NAME SELECT * FROM {_quote(_SOURCE_VIEW)}")

    def _merge(self, connection: duckdb.DuckDBPyConnection, table: str, primary_keys: list[str]) -> None:
        source = _quote(_SOURCE_VIEW)
        target = self._qualified(table)
        on = " AND ".join(f"{target}.{_quote(key)} = {source}.{_quote(key)}" for key in primary_keys)
        connection.execute(
            f"MERGE INTO {target} USING {source} ON ({on}) "
            "WHEN MATCHED THEN UPDATE BY NAME WHEN NOT MATCHED THEN INSERT BY NAME"
        )

    # --- writer protocol ----------------------------------------------------------------

    async def prepare_run(self, ctx: DestinationRunContext) -> None:
        # Tables are created from the first batch's schema, once it is known.
        return None

    async def write_batch(
        self, batches: AsyncIterator[pa.RecordBatch], ctx: DestinationBatchContext
    ) -> BatchWriteOutcome:
        outcome = BatchWriteOutcome(rows_written=0, bytes_written=0)
        record_index = 0
        async for batch in batches:
            outcome += await self._run(
                functools.partial(self._write_record_batch, batch=batch, ctx=ctx, record_index=record_index)
            )
            record_index += 1
        return outcome

    def _write_record_batch(
        self,
        connection: duckdb.DuckDBPyConnection,
        batch: pa.RecordBatch,
        ctx: DestinationBatchContext,
        *,
        record_index: int,
    ) -> BatchWriteOutcome:
        run = ctx.run
        full_refresh = run.is_full_refresh
        target = staging_table_name(run) if full_refresh else run.table_name
        merges = run.is_incremental and bool(run.primary_keys)
        if merges and (missing := [key for key in run.primary_keys if key not in batch.schema.names]):
            # Merging on the keys the batch has would match rows on part of the key and overwrite them.
            raise ValueError(f"The batch has no column for primary key {', '.join(missing)}, so it cannot be merged")

        if full_refresh and self._already_published(connection, run):
            # The staging table is gone and the live table carries this run's publish stamp, so
            # the run finished. Building a staging table out of this one batch and swapping it in
            # would replace the whole table with it.
            return BatchWriteOutcome(rows_written=0, bytes_written=0)

        table_existed, comment = self._table_comment(connection, target)
        if table_existed and not is_owned_by(comment, run.schema_id):
            raise UnrelatedTableExistsError(
                f'"{self._schema}"."{target}" already exists and was not created by this sync; '
                + (
                    "refusing to reuse it as a staging table."
                    if full_refresh
                    else "refusing to merge an incremental run's rows into it."
                )
            )

        if full_refresh:
            source = stamp_batch_index(batch, ctx.batch_index)
        elif merges:
            source = dedupe_merge_source(batch, list(run.primary_keys))
        else:
            source = batch
        source = duckdb_compatible_batch(source)

        connection.register(_SOURCE_VIEW, source)
        try:
            connection.begin()
            try:
                self._ensure_table(connection, target)
                self._evolve_table(connection, target)
                if not table_existed:
                    self._set_comment(connection, target, owned_marker(run.schema_id))

                if full_refresh:
                    if record_index == 0:
                        # A re-apply after a crash: clear what this batch's previous attempt wrote.
                        connection.execute(
                            f"DELETE FROM {self._qualified(target)} WHERE {_quote(BATCH_INDEX_COLUMN)} = ?",
                            [ctx.batch_index],
                        )
                    self._insert(connection, target)
                elif merges:
                    self._merge(connection, target, list(run.primary_keys))
                elif self._claim_receipt(connection, run, ctx.batch_index, record_index):
                    self._insert(connection, target)
                else:
                    # An earlier attempt already committed these rows. Its bytes still count,
                    # because that attempt failed on a later chunk and recorded no egress. The
                    # delivery record is unique per batch, so a batch is billed only once.
                    connection.commit()
                    return BatchWriteOutcome(rows_written=0, bytes_written=source.nbytes)
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
        finally:
            connection.unregister(_SOURCE_VIEW)

        # An approximation of the egress. DuckDB ships the registered Arrow data to MotherDuck in
        # its own wire format, which this writer cannot see, so the in-memory Arrow size stands in.
        return BatchWriteOutcome(rows_written=source.num_rows, bytes_written=source.nbytes)

    def _claim_receipt(
        self, connection: duckdb.DuckDBPyConnection, run: DestinationRunContext, batch_index: int, record_index: int
    ) -> bool:
        """Record that this record batch is being appended, or return False when it already was."""
        receipts = self._qualified(RECEIPTS_TABLE)
        connection.execute(
            f"CREATE TABLE IF NOT EXISTS {receipts} "
            "(schema_id VARCHAR, run_uuid VARCHAR, batch_index INTEGER, record_index INTEGER)"
        )
        key = [run.schema_id, run.run_uuid, batch_index, record_index]
        seen = connection.execute(
            f"SELECT 1 FROM {receipts} WHERE schema_id = ? AND run_uuid = ? AND batch_index = ? AND record_index = ?",
            key,
        ).fetchone()
        if seen is not None:
            return False
        connection.execute(f"INSERT INTO {receipts} VALUES (?, ?, ?, ?)", key)
        return True

    def _drop_older_receipts(self, connection: duckdb.DuckDBPyConnection, ctx: DestinationRunContext) -> None:
        """Keep only this run's receipts: no earlier run of the schema can be redelivered any more."""
        exists, _ = self._table_comment(connection, RECEIPTS_TABLE)
        if exists:
            connection.execute(
                f"DELETE FROM {self._qualified(RECEIPTS_TABLE)} WHERE schema_id = ? AND run_uuid <> ?",
                [ctx.schema_id, ctx.run_uuid],
            )

    def _already_published(self, connection: duckdb.DuckDBPyConnection, ctx: DestinationRunContext) -> bool:
        staging_exists, _ = self._table_comment(connection, staging_table_name(ctx))
        if staging_exists:
            return False
        live_exists, comment = self._table_comment(connection, ctx.table_name)
        return live_exists and is_published_by(comment, ctx.schema_id, ctx.run_uuid)

    async def finalize_run(self, ctx: DestinationRunContext) -> None:
        """Publish a full refresh by swapping the staging table into place."""
        if not ctx.is_full_refresh:
            # Other runs write straight into the live table, so they have nothing to publish.
            await self._run(lambda connection: self._drop_older_receipts(connection, ctx))
            return
        await self._run(lambda connection: self._publish(connection, ctx))

    def _publish(self, connection: duckdb.DuckDBPyConnection, ctx: DestinationRunContext) -> None:
        staging = staging_table_name(ctx)
        staging_exists, _ = self._table_comment(connection, staging)
        if not staging_exists:
            # Already swapped by an earlier attempt at this same final batch.
            return

        live_exists, comment = self._table_comment(connection, ctx.table_name)
        if live_exists and not is_owned_by(comment, ctx.schema_id):
            # `table_name` comes from the source's resource name, which a custom-source manifest
            # controls, so a table that predates this sync could be anything the customer had.
            raise UnrelatedTableExistsError(
                f'"{self._schema}"."{ctx.table_name}" already exists and was not created by this sync; '
                "refusing to replace it with the full refresh's staging table."
            )

        connection.begin()
        try:
            connection.execute(
                f"ALTER TABLE {self._qualified(staging)} DROP COLUMN IF EXISTS {_quote(BATCH_INDEX_COLUMN)}"
            )
            connection.execute(f"DROP TABLE IF EXISTS {self._qualified(ctx.table_name)}")
            connection.execute(f"ALTER TABLE {self._qualified(staging)} RENAME TO {_quote(ctx.table_name)}")
            # Stamp the run that published, so a redelivery of the final batch can tell "already
            # published" from "never started" and refuse to rebuild the table.
            self._set_comment(connection, ctx.table_name, published_marker(ctx.schema_id, ctx.run_uuid))
            connection.commit()
        except BaseException:
            connection.rollback()
            raise

    async def abort_run(self, ctx: DestinationRunContext) -> None:
        """Drop whatever a run that will not finish left staged."""
        if not ctx.is_full_refresh:
            return

        def drop(connection: duckdb.DuckDBPyConnection) -> None:
            staging = staging_table_name(ctx)
            exists, comment = self._table_comment(connection, staging)
            # A table under the staging name that this sync did not create stopped the run in the
            # first place. It is the customer's, so it stays.
            if exists and is_owned_by(comment, ctx.schema_id):
                connection.execute(f"DROP TABLE {self._qualified(staging)}")

        await self._run(drop)
