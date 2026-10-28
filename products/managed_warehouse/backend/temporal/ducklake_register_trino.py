"""Register a prepared Parquet generation in DuckLake through the organization's Trino catalog.

The data-imports registration workflow uses this for warehouses that register without duckgres. Trino has no
`read_parquet`, so the staging table's columns come from the Parquet footers of the copied files, and the
connector's `add_files` and `publish_as` table procedures replace `ducklake_add_data_files` and the rename swap.
"""

from __future__ import annotations

import re
import datetime as dt
import threading
import contextlib
from collections.abc import Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import IO, TYPE_CHECKING, Any, Protocol

import pyarrow as pa
import structlog
import pyarrow.parquet as pq
from temporalio.exceptions import ApplicationError

from posthog.hogql.escape_sql import escape_trino_identifier, escape_trino_string

from posthog.dataclasses import frozen

from products.managed_warehouse.backend.trino_connection import connect_managed_warehouse_trino
from products.managed_warehouse.backend.trino_execution import TrinoQueryControl

if TYPE_CHECKING:
    from trino.dbapi import Connection

LOGGER = structlog.get_logger(__name__)

STAGING_TABLE_PREFIX = "__ph_register_"
# The connector accepts 10,000 files per call. Fewer keeps one call short and its SQL text small.
ADD_FILES_MAX_FILES = 2_000
# Trino rejects statements longer than 1,000,000 characters. Half of that leaves room for the rest of the statement.
ADD_FILES_MAX_CHARACTERS = 500_000
_FOOTER_READ_CONCURRENCY = 16
# The staging table name carries the time the workflow minted it, because information_schema has no creation time
# and the sweep must not drop the staging table of a registration that is still running.
_STAGING_TABLE_PATTERN = re.compile(rf"^{STAGING_TABLE_PREFIX}(\d{{10}})_[0-9a-f]{{16}}$")
# The connector reads a partition key as `transform(column)`, so only a plain identifier names a column.
_PARTITION_COLUMN_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# add_files compares each file's Parquet type with the type DuckLake writes for the column, and never widens.
# Each Arrow type here reads back from a Parquet type that the mapped Trino type writes the same way.
_TRINO_TYPES: dict[pa.DataType, str] = {
    pa.string(): "VARCHAR",
    pa.large_string(): "VARCHAR",
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
}
_DECIMAL_TYPES = (pa.Decimal32Type, pa.Decimal64Type, pa.Decimal128Type, pa.Decimal256Type)
_TRINO_MAX_DECIMAL_PRECISION = 38


class ParquetFilesystem(Protocol):
    def open(self, path: str, mode: str = "rb") -> IO[bytes]: ...


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


def stale_staging_tables(
    table_names: Sequence[str], *, now: dt.datetime, min_age: dt.timedelta, limit: int
) -> list[str]:
    cutoff = (now - min_age).timestamp()
    stale = [
        name
        for name in table_names
        if (match := _STAGING_TABLE_PATTERN.fullmatch(name)) is not None and int(match.group(1)) < cutoff
    ]
    return stale[:limit]


def _procedure_count(rows: list[list[Any]], metric_name: str) -> int:
    return sum(int(row[1]) for row in rows if len(row) > 1 and row[0] == metric_name)


class TrinoRegistrationCatalog:
    """The DuckLake statements of one registration, run in the organization's Trino catalog."""

    def __init__(self, connection: Connection, control: TrinoQueryControl | None = None) -> None:
        self._connection = connection
        self._control = control
        self._catalog = escape_trino_identifier(connection.catalog)

    @classmethod
    @contextlib.contextmanager
    def connect(
        cls, organization_id: str, *, principal: str, cancel_after_seconds: float | None = None
    ) -> Iterator[TrinoRegistrationCatalog]:
        """Connect with a short-lived service credential, and cancel the running statement at the deadline.

        The Temporal activity times out without stopping this thread, so a statement still running after the
        deadline would race the cleanup finalizer.
        """
        if cancel_after_seconds is not None and cancel_after_seconds <= 0:
            raise TimeoutError("Trino registration started too close to the Temporal activity deadline")
        with connect_managed_warehouse_trino(organization_id, principal=principal) as connection:
            if cancel_after_seconds is None:
                yield cls(connection)
                return
            control = TrinoQueryControl(query_seconds=cancel_after_seconds)
            timer = threading.Timer(cancel_after_seconds, control.cancel)
            timer.daemon = True
            timer.start()
            try:
                yield cls(connection, control)
            finally:
                timer.cancel()
                control.finished.set()

    def _schema(self, schema: str) -> str:
        return f"{self._catalog}.{escape_trino_identifier(schema)}"

    def _table(self, schema: str, table: str) -> str:
        return f"{self._schema(schema)}.{escape_trino_identifier(table)}"

    def _run(self, statement: str, *, cancellable: bool = True) -> list[list[Any]]:
        control = self._control if cancellable else None
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

    def create_schema(self, schema: str) -> None:
        self._run(f"CREATE SCHEMA IF NOT EXISTS {self._schema(schema)}")

    def create_staging_table(self, schema: str, table: str, staging_schema: StagingTableSchema) -> None:
        columns = ", ".join(
            f"{escape_trino_identifier(column.name)} {column.trino_type}" for column in staging_schema.columns
        )
        statement = f"CREATE TABLE {self._table(schema, table)} ({columns})"
        if staging_schema.partition_columns:
            partitioning = ", ".join(escape_trino_string(name) for name in staging_schema.partition_columns)
            statement += f" WITH (partitioning = ARRAY[{partitioning}])"
        self._run(statement)

    def register_files(self, schema: str, table: str, paths: Sequence[str], *, generation_token: str) -> int:
        """Add the files in batches. Each batch has a stable import_id, so repeating a batch is a no-op."""
        added = 0
        for index, batch in enumerate(add_files_batches(paths)):
            files = ", ".join(escape_trino_string(path) for path in batch)
            import_id = escape_trino_string(f"{generation_token}-b{index}")
            rows = self._run(
                f"ALTER TABLE {self._table(schema, table)} EXECUTE add_files("
                f"files => ARRAY[{files}], import_id => {import_id}, allow_missing => true, hive_partitioning => true)"
            )
            added += _procedure_count(rows, "added_data_files")
        return added

    def count_rows(self, schema: str, table: str) -> int:
        rows = self._run(f"SELECT count(*) FROM {self._table(schema, table)}")
        return int(rows[0][0]) if rows else 0

    def publish_as(self, schema: str, table: str, *, target: str) -> int | None:
        """Drop `target` if it exists and rename `table` to it, in one DuckLake snapshot.

        Returns the number of replaced tables, or None when the swap committed but its response was lost.
        """
        try:
            rows = self._run(
                f"ALTER TABLE {self._table(schema, table)} EXECUTE publish_as(target => {escape_trino_string(target)})"
            )
        except Exception as error:
            # publish_as is not idempotent. When its response is lost after the commit, the staging table is
            # gone and a client retry fails with TABLE_NOT_FOUND. Only this attempt uses the staging table's
            # name, so a missing staging table next to an existing target means the swap committed.
            if self._publish_committed(schema, table, target):
                LOGGER.warning(
                    "DuckLake publish_as failed after its commit; the staging table is published",
                    error_name=getattr(error, "error_name", None),
                    table_name=f"{schema}.{target}",
                )
                return None
            LOGGER.warning(
                "DuckLake publish_as failed",
                error_name=getattr(error, "error_name", None),
                table_name=f"{schema}.{table}",
                target=target,
            )
            raise
        return _procedure_count(rows, "replaced_tables")

    def _publish_committed(self, schema: str, table: str, target: str) -> bool:
        # Not cancellable, because a deadline cancel can be what interrupted the publish.
        try:
            rows = self._run(
                f"SELECT table_name FROM {self._catalog}.information_schema.tables "
                f"WHERE table_schema = {escape_trino_string(schema)} "
                f"AND table_name IN ({escape_trino_string(table)}, {escape_trino_string(target)})",
                cancellable=False,
            )
        except Exception:
            LOGGER.warning("Could not check whether DuckLake publish_as committed", exc_info=True)
            return False
        tables = {str(row[0]) for row in rows}
        return table not in tables and target in tables

    def drop_table(self, schema: str, table: str) -> None:
        self._run(f"DROP TABLE IF EXISTS {self._table(schema, table)}")

    def drop_table_quietly(self, schema: str, table: str) -> None:
        # Runs while another error may be in flight, and after the deadline cancelled the session, so it ignores
        # the deadline and never raises. The workflow cleanup finalizer drops the table if this fails.
        try:
            self._run(f"DROP TABLE IF EXISTS {self._table(schema, table)}", cancellable=False)
        except Exception:
            LOGGER.warning(
                "Failed to drop DuckLake registration staging table; the workflow cleanup finalizer will retry",
                table_name=f"{schema}.{table}",
                exc_info=True,
            )

    def drop_stale_staging_tables(
        self, schema: str, *, now: dt.datetime, min_age: dt.timedelta, limit: int
    ) -> list[str]:
        rows = self._run(
            f"SELECT table_name FROM {self._catalog}.information_schema.tables "
            f"WHERE table_schema = {escape_trino_string(schema)} "
            f"AND starts_with(table_name, {escape_trino_string(STAGING_TABLE_PREFIX)})"
        )
        stale = stale_staging_tables([str(row[0]) for row in rows], now=now, min_age=min_age, limit=limit)
        for table in stale:
            self.drop_table(schema, table)
        return stale
