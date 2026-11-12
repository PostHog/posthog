"""Register a prepared data import generation in DuckLake through the organization's Trino catalog.

The Trino connector commits every statement as its own snapshot, so the two renames that the duckgres path runs in
one transaction are not possible here. `publish_as` ends the live table and renames the shadow table to its name in
one snapshot instead.

This module must not import the workflow module: the workflow imports it.
"""

from __future__ import annotations

import re
import datetime as dt
import threading
import contextlib
from collections.abc import Callable, Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from time import monotonic
from typing import IO, TYPE_CHECKING, Any, Protocol
from uuid import UUID

import pyarrow as pa
import structlog
import pyarrow.parquet as pq
from temporalio.exceptions import ApplicationError

from posthog.hogql.escape_sql import escape_trino_identifier, escape_trino_string

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception

from products.managed_warehouse.backend.backfill_trino import _retry_transient
from products.managed_warehouse.backend.trino_connection import connect_managed_warehouse_trino
from products.managed_warehouse.backend.trino_execution import TrinoQueryControl

if TYPE_CHECKING:
    from trino.dbapi import Connection

LOGGER = structlog.get_logger(__name__)

STAGING_TABLE_PREFIX = "__ph_register_"
# One add_files call is one snapshot. The connector accepts 10,000 files, but Trino rejects a statement longer than
# 1,000,000 characters. Fewer files and half the length keep one call short and leave room for the rest of the statement.
ADD_FILES_MAX_FILES = 2_000
ADD_FILES_MAX_CHARACTERS = 500_000
_FOOTER_READ_CONCURRENCY = 16
# The staging table name carries the time the workflow minted it, because information_schema has no creation time
# and the sweep must not drop the staging table of a registration that is still running.
_STAGING_TABLE_PATTERN = re.compile(rf"^{STAGING_TABLE_PREFIX}(\d{{10}})_[0-9a-f]{{16}}$")
# The connector reads a partition key as `transform(column)`, so only a plain identifier names a column.
_PARTITION_COLUMN_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# add_files compares each file's Parquet type with the type DuckLake writes for the column, and never widens.
# Each Arrow type here reads back from a Parquet type that the mapped Trino type writes the same way.
# The view types come only from the Arrow schema that some writers store in the footer. The Parquet column
# under them is the same byte array as for string and binary, so they map to the same Trino type.
_TRINO_TYPES: dict[pa.DataType, str] = {
    pa.string(): "VARCHAR",
    pa.large_string(): "VARCHAR",
    pa.string_view(): "VARCHAR",
    pa.int64(): "BIGINT",
    pa.int32(): "INTEGER",
    pa.int16(): "SMALLINT",
    pa.int8(): "TINYINT",
    pa.float64(): "DOUBLE",
    pa.float32(): "REAL",
    pa.bool_(): "BOOLEAN",
    pa.date32(): "DATE",
    pa.binary(): "VARBINARY",
    pa.large_binary(): "VARBINARY",
    pa.binary_view(): "VARBINARY",
}
_DECIMAL_TYPES = (pa.Decimal32Type, pa.Decimal64Type, pa.Decimal128Type, pa.Decimal256Type)
_TRINO_MAX_DECIMAL_PRECISION = 38


class ParquetFilesystem(Protocol):
    def open(self, path: str, mode: str = "rb") -> IO[bytes]: ...


@frozen
class TrinoRegistrationResult:
    published: bool
    row_count: int


@frozen
class ParquetFooter:
    path: str
    num_rows: int
    schema: pa.Schema


@frozen
class StagingColumn:
    name: str
    trino_type: str


@frozen
class StagingTableSchema:
    columns: tuple[StagingColumn, ...]
    partition_columns: tuple[str, ...]


def _non_retryable(message: str) -> ApplicationError:
    return ApplicationError(message, non_retryable=True)


def trino_type_for_arrow(arrow_type: pa.DataType) -> str | None:
    if isinstance(arrow_type, pa.TimestampType):
        if arrow_type.unit != "us":
            return None
        return "TIMESTAMP(6)" if arrow_type.tz is None else "TIMESTAMP(6) WITH TIME ZONE"
    if isinstance(arrow_type, _DECIMAL_TYPES):
        if (
            not 1 <= arrow_type.precision <= _TRINO_MAX_DECIMAL_PRECISION
            or not 0 <= arrow_type.scale <= arrow_type.precision
        ):
            return None
        return f"DECIMAL({arrow_type.precision}, {arrow_type.scale})"
    return _TRINO_TYPES.get(arrow_type)


def _add_column(columns: dict[str, StagingColumn], column: StagingColumn, path: str) -> None:
    # Trino folds identifiers to lower case, so names that differ only in case would be one column.
    key = column.name.lower()
    existing = columns.get(key)
    if existing is None:
        columns[key] = column
    elif existing.name != column.name:
        raise _non_retryable(
            f"Columns '{existing.name}' and '{column.name}' differ only in case, which Trino cannot tell apart"
        )
    elif existing.trino_type != column.trino_type:
        raise _non_retryable(
            f"Column '{column.name}' is {existing.trino_type} in one file and {column.trino_type} in {path}, "
            "and DuckLake registration through Trino cannot widen either"
        )


def staging_table_schema(footers: Sequence[ParquetFooter], hive_partition_columns: Sequence[str]) -> StagingTableSchema:
    """Union the file columns by name, then append the Hive partition columns as VARCHAR partitions.

    A file may lack a column: add_files reads it as NULL. Partition values come from the paths, as
    `read_parquet(..., hive_partitioning=true)` reads them on the duckgres path.
    """
    columns: dict[str, StagingColumn] = {}
    for footer in footers:
        for field in footer.schema:
            trino_type = trino_type_for_arrow(field.type)
            if trino_type is None:
                raise _non_retryable(
                    f"Column '{field.name}' in {footer.path} has unsupported type {field.type} "
                    "for DuckLake registration through Trino"
                )
            _add_column(columns, StagingColumn(name=field.name, trino_type=trino_type), footer.path)
    for name in hive_partition_columns:
        if not _PARTITION_COLUMN_PATTERN.fullmatch(name):
            raise _non_retryable(f"Hive partition column name '{name}' is not a plain identifier")
        existing = columns.get(name.lower())
        if existing is not None:
            raise _non_retryable(f"Hive partition column '{name}' collides with column '{existing.name}'")
        columns[name.lower()] = StagingColumn(name=name, trino_type="VARCHAR")
    return StagingTableSchema(columns=tuple(columns.values()), partition_columns=tuple(hive_partition_columns))


def read_parquet_footers(filesystem: ParquetFilesystem, paths: Sequence[str]) -> list[ParquetFooter]:
    def read(path: str) -> ParquetFooter:
        with filesystem.open(path, "rb") as file, pq.ParquetFile(file) as parquet_file:
            return ParquetFooter(path=path, num_rows=parquet_file.metadata.num_rows, schema=parquet_file.schema_arrow)

    with ThreadPoolExecutor(max_workers=_FOOTER_READ_CONCURRENCY, thread_name_prefix="ducklake-footer") as executor:
        return list(executor.map(read, paths))


def add_files_batches(
    paths: Sequence[str],
    *,
    max_files: int = ADD_FILES_MAX_FILES,
    max_characters: int = ADD_FILES_MAX_CHARACTERS,
) -> list[list[str]]:
    batches: list[list[str]] = []
    batch: list[str] = []
    characters = 0
    for path in paths:
        # The quoted literal and the ", " that separates it from the next one.
        size = len(escape_trino_string(path)) + 2
        if batch and (len(batch) >= max_files or characters + size > max_characters):
            batches.append(batch)
            batch = []
            characters = 0
        batch.append(path)
        characters += size
    if batch:
        batches.append(batch)
    return batches


def staging_table_name(minted_at: dt.datetime, token: str) -> str:
    return f"{STAGING_TABLE_PREFIX}{int(minted_at.timestamp()):010d}_{token}"


def staging_table_minted_at(table_name: str) -> dt.datetime | None:
    match = _STAGING_TABLE_PATTERN.fullmatch(table_name)
    return None if match is None else dt.datetime.fromtimestamp(int(match.group(1)), tz=dt.UTC)


def stale_staging_tables(
    table_names: Sequence[str], *, now: dt.datetime, min_age: dt.timedelta, limit: int
) -> list[str]:
    cutoff = now - min_age
    stale = [
        name for name in table_names if (minted_at := staging_table_minted_at(name)) is not None and minted_at < cutoff
    ]
    return stale[:limit]


def _principal(team_id: int, suffix: str) -> str:
    return f"posthog:ducklake-register:team:{team_id}:{suffix}"


class _TrinoStatements:
    def __init__(self, connection: Connection, control: TrinoQueryControl | None = None) -> None:
        self._connection = connection
        self._control = control
        self.catalog = connection.catalog

    def qualified(self, schema_name: str, table_name: str | None = None) -> str:
        qualified = f"{escape_trino_identifier(self.catalog)}.{escape_trino_identifier(schema_name)}"
        return qualified if table_name is None else f"{qualified}.{escape_trino_identifier(table_name)}"

    def execute(self, statement: str, *, cancellable: bool = True) -> list[list[Any]]:
        control = self._control if cancellable else None
        # Every call checks the deadline first, so a retry after the deadline raises instead of running the
        # statement again.
        if control is not None:
            control.checkpoint()
        cursor = self._connection.cursor()
        if control is not None:
            control.attach(cursor)
        try:
            cursor.execute(statement)
            return cursor.fetchall()
        finally:
            cursor.close()

    @_retry_transient
    def run(self, statement: str, *, cancellable: bool = True) -> list[list[Any]]:
        return self.execute(statement, cancellable=cancellable)

    def tables_present(self, schema_name: str, table_names: Sequence[str], *, cancellable: bool = True) -> set[str]:
        names = ", ".join(escape_trino_string(name) for name in table_names)
        rows = self.run(
            f"SELECT table_name FROM {escape_trino_identifier(self.catalog)}.information_schema.tables "
            f"WHERE table_schema = {escape_trino_string(schema_name)} AND table_name IN ({names})",
            cancellable=cancellable,
        )
        return {str(row[0]) for row in rows}

    @_retry_transient
    def publish(self, schema_name: str, shadow_name: str, table_name: str) -> None:
        statement = (
            f"ALTER TABLE {self.qualified(schema_name, shadow_name)} "
            f"EXECUTE publish_as(target => {escape_trino_string(table_name)})"
        )
        try:
            self.execute(statement)
        except Exception as error:
            # publish_as is not idempotent. When the shadow table no longer resolves, an earlier attempt whose
            # response was lost already published it. This check is not cancellable, because a deadline cancel can
            # be what interrupted the publish.
            present = self.tables_present(schema_name, [shadow_name, table_name], cancellable=False)
            if shadow_name not in present and table_name in present:
                LOGGER.warning(
                    "The Trino publish succeeded although its response failed",
                    table=table_name,
                    error_name=getattr(error, "error_name", None),
                )
                return
            LOGGER.warning(
                "The Trino publish failed",
                table=table_name,
                error_name=getattr(error, "error_name", None),
            )
            raise


@contextlib.contextmanager
def _registration_statements(
    organization_id: str, *, principal: str, cancel_after_seconds: float | None, canary: bool = False
) -> Iterator[_TrinoStatements]:
    """Connect, and cancel the running statement at the activity deadline.

    The Temporal activity times out without stopping its thread, so a statement still running after the deadline
    would race the cleanup finalizer.
    """
    if cancel_after_seconds is not None and cancel_after_seconds <= 0:
        raise TimeoutError("Trino registration started too close to the Temporal activity deadline")
    with connect_managed_warehouse_trino(organization_id, principal=principal, canary=canary) as connection:
        if cancel_after_seconds is None:
            yield _TrinoStatements(connection)
            return
        control = TrinoQueryControl(query_seconds=cancel_after_seconds)
        timer = threading.Timer(cancel_after_seconds, control.cancel)
        timer.daemon = True
        timer.start()
        try:
            yield _TrinoStatements(connection, control)
        finally:
            timer.cancel()
            control.finished.set()


def _create_table_statement(
    statements: _TrinoStatements, schema_name: str, shadow_name: str, staging_schema: StagingTableSchema
) -> str:
    definitions = ", ".join(
        f"{escape_trino_identifier(column.name)} {column.trino_type}" for column in staging_schema.columns
    )
    statement = f"CREATE TABLE IF NOT EXISTS {statements.qualified(schema_name, shadow_name)} ({definitions})"
    if staging_schema.partition_columns:
        literals = ", ".join(escape_trino_string(column) for column in staging_schema.partition_columns)
        statement += f" WITH (partitioning = ARRAY[{literals}])"
    return statement


def _add_files_statement(
    statements: _TrinoStatements,
    schema_name: str,
    shadow_name: str,
    paths: Sequence[str],
    *,
    import_id: str,
    hive_partitioning: bool,
) -> str:
    files = ", ".join(escape_trino_string(path) for path in paths)
    return (
        f"ALTER TABLE {statements.qualified(schema_name, shadow_name)} EXECUTE add_files("
        f"files => ARRAY[{files}], import_id => {escape_trino_string(import_id)}, allow_missing => true, "
        f"hive_partitioning => {'true' if hive_partitioning else 'false'})"
    )


def register_prepared_files_through_trino(
    *,
    organization_id: str,
    team_id: int,
    schema_id: UUID,
    ducklake_schema: str,
    ducklake_table: str,
    shadow_name: str,
    attempt_token: str,
    landing_paths: Sequence[str],
    hive_partition_columns: Sequence[str],
    filesystem: ParquetFilesystem,
    should_publish: Callable[[], bool],
    before_add_files: Callable[[], None] | None = None,
    deadline_monotonic: float | None = None,
    canary: bool = False,
) -> TrinoRegistrationResult:
    """Create the shadow table, add the copied files to it, check its row count and publish it.

    `landing_paths` are this attempt's copied files. The columns and the expected row count come from their Parquet
    footers, because add_files compares each file's own types exactly. The import ids derive from `attempt_token`,
    so a repeated attempt replays finished batches as no-ops. `deadline_monotonic` is the `time.monotonic()` value
    at which the running statement is cancelled. `before_add_files` runs once before the first add_files statement.
    Until then no table can reference the landing files.
    """
    sorted_paths = sorted(landing_paths)
    # A type error fails here, before any catalog work.
    footers = read_parquet_footers(filesystem, sorted_paths)
    staging_schema = staging_table_schema(footers, hive_partition_columns)
    expected_rows = sum(footer.num_rows for footer in footers)

    # Reading many footers takes time, so the remaining budget is measured after the reads.
    with _registration_statements(
        organization_id,
        principal=_principal(team_id, f"schema:{schema_id}"),
        cancel_after_seconds=None if deadline_monotonic is None else deadline_monotonic - monotonic(),
        canary=canary,
    ) as statements:
        statements.run(f"CREATE SCHEMA IF NOT EXISTS {statements.qualified(ducklake_schema)}")
        statements.run(_create_table_statement(statements, ducklake_schema, shadow_name, staging_schema))
        if before_add_files is not None:
            before_add_files()
        for index, batch in enumerate(add_files_batches(sorted_paths)):
            rows = statements.run(
                _add_files_statement(
                    statements,
                    ducklake_schema,
                    shadow_name,
                    batch,
                    import_id=f"{attempt_token}_{index:05d}",
                    hive_partitioning=bool(staging_schema.partition_columns),
                )
            )
            added = sum(int(row[1]) for row in rows if len(row) > 1 and row[0] == "added_data_files")
            if added not in (len(batch), 0):
                raise ApplicationError(
                    f"Trino registered {added} files for a batch of {len(batch)}", non_retryable=True
                )

        count_rows = statements.run(f"SELECT count(*) FROM {statements.qualified(ducklake_schema, shadow_name)}")
        registered_count = int(count_rows[0][0]) if count_rows else 0
        if registered_count != expected_rows:
            raise ApplicationError(
                "DuckLake prepared-file registration row count mismatch: "
                f"source={expected_rows}, registered={registered_count}",
                non_retryable=True,
            )

        if not should_publish():
            return TrinoRegistrationResult(published=False, row_count=registered_count)
        statements.publish(ducklake_schema, shadow_name, ducklake_table)
        return TrinoRegistrationResult(published=True, row_count=registered_count)


def cleanup_trino_registration_tables(
    *,
    organization_id: str,
    team_id: int,
    schema_name: str,
    table_names: Sequence[str],
    sweep_min_age: dt.timedelta,
    sweep_limit: int,
    cancel_after_seconds: float | None,
    canary: bool = False,
) -> None:
    """Drop the given tables, then drop up to `sweep_limit` registration tables older than `sweep_min_age`."""
    with _registration_statements(
        organization_id,
        principal=_principal(team_id, "cleanup"),
        cancel_after_seconds=cancel_after_seconds,
        canary=canary,
    ) as statements:
        for table_name in table_names:
            statements.run(f"DROP TABLE IF EXISTS {statements.qualified(schema_name, table_name)}")
        LOGGER.info("Cleaned up DuckLake registration tables", table_names=list(table_names))
        try:
            swept = _sweep_stale_tables(statements, schema_name, sweep_min_age, sweep_limit)
        except Exception as error:
            # The sweep is opportunistic: this attempt's own tables are already dropped, and the next run sweeps again.
            LOGGER.warning("Stale registration table sweep failed", error=str(error))
            capture_exception(error)
        else:
            if swept:
                LOGGER.info("Swept stale DuckLake registration tables", table_names=swept)


def _sweep_stale_tables(statements: _TrinoStatements, schema_name: str, min_age: dt.timedelta, limit: int) -> list[str]:
    rows = statements.run(
        f"SELECT table_name FROM {escape_trino_identifier(statements.catalog)}.information_schema.tables "
        f"WHERE table_schema = {escape_trino_string(schema_name)} "
        f"AND starts_with(table_name, {escape_trino_string(STAGING_TABLE_PREFIX)})"
    )
    stale = stale_staging_tables(
        [str(row[0]) for row in rows], now=dt.datetime.now(dt.UTC), min_age=min_age, limit=limit
    )
    for table_name in stale:
        statements.run(f"DROP TABLE IF EXISTS {statements.qualified(schema_name, table_name)}")
    return stale
