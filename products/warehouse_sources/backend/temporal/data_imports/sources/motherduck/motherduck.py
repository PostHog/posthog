"""MotherDuck transport: connection building, schema discovery, and the sync pipeline source.

MotherDuck is DuckDB as a service — the `duckdb` Python driver dials it with an `md:`
connection string and runs hybrid execution, so part of every query executes in-process.
Two connection-string guards matter because of that in-process half:

- ``saas_mode=true`` disables local filesystem access and extension installation, so a
  query can never read files off the PostHog worker.
- ``read_only=True`` (sync reads and direct queries never need writes) makes DuckDB
  reject every write statement engine-side, independent of the token's grants.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from urllib.parse import quote

import duckdb
import pyarrow as pa
import structlog

from products.warehouse_sources.backend.models.util import normalize_duckdb_type
from products.warehouse_sources.backend.temporal.data_imports.pipelines.helpers import incremental_type_to_operator
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import log_connection_open
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.types import IncrementalFieldType

logger = structlog.get_logger(__name__)

# Databases MotherDuck attaches for its own bookkeeping — never user data.
SYSTEM_DATABASES = frozenset({"md_information_schema", "system", "temp", "_duckdb_ui"})
SYSTEM_SCHEMAS = frozenset({"information_schema", "pg_catalog"})

DEFAULT_SYNC_CHUNK_SIZE = 10_000

_INCREMENTAL_TYPES: dict[str, IncrementalFieldType] = {
    "date": IncrementalFieldType.Date,
    "timestamp": IncrementalFieldType.DateTime,
    "datetime": IncrementalFieldType.DateTime,
    "timestamp with time zone": IncrementalFieldType.DateTime,
    "timestamptz": IncrementalFieldType.DateTime,
    "timestamp_s": IncrementalFieldType.DateTime,
    "timestamp_ms": IncrementalFieldType.DateTime,
    "timestamp_ns": IncrementalFieldType.DateTime,
    "tinyint": IncrementalFieldType.Integer,
    "smallint": IncrementalFieldType.Integer,
    "integer": IncrementalFieldType.Integer,
    "int": IncrementalFieldType.Integer,
    "bigint": IncrementalFieldType.Integer,
    "hugeint": IncrementalFieldType.Integer,
    "utinyint": IncrementalFieldType.Integer,
    "usmallint": IncrementalFieldType.Integer,
    "uinteger": IncrementalFieldType.Integer,
    "ubigint": IncrementalFieldType.Integer,
}


class MotherDuckConnectionError(Exception):
    pass


def build_connection_string(token: str, database: str | None = None) -> str:
    """`md:` connection string pinned to SaaS mode (no local filesystem, no extension installs)."""
    return f"md:{quote(database or '', safe='')}?motherduck_token={quote(token, safe='')}&saas_mode=true"


def connect(token: str, database: str | None = None, *, read_only: bool = True) -> duckdb.DuckDBPyConnection:
    """Open a MotherDuck connection, translating driver errors to `MotherDuckConnectionError`."""
    log_connection_open(db_host="motherduck", via="websocket")
    try:
        return duckdb.connect(build_connection_string(token, database), read_only=read_only)
    except duckdb.Error as e:
        raise MotherDuckConnectionError(translate_motherduck_error(e)) from e


def translate_motherduck_error(error: Exception) -> str:
    message = str(error)
    lowered = message.lower()
    if "unauthenticated" in lowered or "invalid token" in lowered or "jwt" in lowered or "authenticat" in lowered:
        return "Invalid MotherDuck token. Generate a new access token in MotherDuck settings and try again."
    if "database" in lowered and ("not found" in lowered or "does not exist" in lowered):
        return "Database not found. Check the database name, or leave it blank to connect to all databases."
    if "compute limit" in lowered or "out of compute" in lowered:
        return (
            "Your MotherDuck plan has reached its compute limit. Queries may be slow or fail until the "
            "limit resets. Upgrade your MotherDuck plan for more capacity."
        )
    # First line only: DuckDB appends multi-line candidate/hint blocks.
    return message.splitlines()[0] if message.strip() else "Could not connect to MotherDuck."


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def qualified_table_name(database: str, schema: str, table: str) -> str:
    return f"{_quote_identifier(database)}.{_quote_identifier(schema)}.{_quote_identifier(table)}"


def display_table_name(database: str, schema: str, table: str, *, configured_database: str | None) -> str:
    """The warehouse-facing schema row name. Stays `schema.table` when the source is pinned to
    one database; grows the database prefix when discovering across all of them."""
    if configured_database:
        return f"{schema}.{table}"
    return f"{database}.{schema}.{table}"


def get_schemas(
    connection: duckdb.DuckDBPyConnection,
    database: str | None,
    *,
    names: list[str] | None = None,
    with_counts: bool = False,
) -> dict[str, dict[str, Any]]:
    """Discover tables (and views) with their columns.

    Returns display name -> {"database", "schema", "table", "columns": [(name, type, nullable)],
    "row_count"} across every non-system database, or just the configured one.
    """
    # MotherDuck attaches every database in the workspace even when the connection string
    # names one (the named database only becomes the *current* one), and DuckDB's
    # information_schema spans all attached catalogs. A pinned database therefore has to be
    # enforced as a predicate, or discovery leaks the whole workspace and same-named tables
    # from other databases collide under one display name.
    columns_query = """
        SELECT table_catalog, table_schema, table_name, column_name, data_type, is_nullable
        FROM information_schema.columns
        {where}
        ORDER BY table_catalog, table_schema, table_name, ordinal_position
        """
    params: dict[str, Any] | None = None
    if database:
        columns_query = columns_query.format(where="WHERE lower(table_catalog) = lower($database)")
        params = {"database": database}
    else:
        columns_query = columns_query.format(where="")
    rows = connection.execute(columns_query, params).fetchall()

    estimated_sizes: dict[tuple[str, str, str], int] = {}
    if with_counts:
        sizes_query = "SELECT database_name, schema_name, table_name, estimated_size FROM duckdb_tables()"
        if database:
            sizes_query += " WHERE lower(database_name) = lower($database)"
        try:
            size_rows = connection.execute(sizes_query, params).fetchall()
            estimated_sizes = {
                (str(db), str(schema), str(table)): int(size)
                for db, schema, table, size in size_rows
                if size is not None
            }
        except duckdb.Error:
            logger.warning("motherduck.get_schemas.estimated_sizes_failed", exc_info=True)

    schemas: dict[str, dict[str, Any]] = {}
    for table_catalog, table_schema, table_name, column_name, data_type, is_nullable in rows:
        if str(table_catalog).lower() in SYSTEM_DATABASES or str(table_schema).lower() in SYSTEM_SCHEMAS:
            continue
        display_name = display_table_name(
            str(table_catalog), str(table_schema), str(table_name), configured_database=database
        )
        if names is not None and display_name not in names:
            continue
        entry = schemas.setdefault(
            display_name,
            {
                "database": str(table_catalog),
                "schema": str(table_schema),
                "table": str(table_name),
                "columns": [],
                "row_count": estimated_sizes.get((str(table_catalog), str(table_schema), str(table_name))),
            },
        )
        entry["columns"].append((str(column_name), str(data_type), str(is_nullable).upper() == "YES"))

    return schemas


def filter_motherduck_incremental_fields(
    columns: list[tuple[str, str, bool]],
) -> list[tuple[str, IncrementalFieldType]]:
    results: list[tuple[str, IncrementalFieldType]] = []
    for column_name, duckdb_type, _nullable in columns:
        field_type = _INCREMENTAL_TYPES.get(normalize_duckdb_type(duckdb_type))
        if field_type is not None:
            results.append((column_name, field_type))
    return results


def get_connection_metadata(token: str, database: str | None) -> dict[str, Any]:
    with closing_connection(token, database) as connection:
        row = connection.execute("SELECT version(), current_database()").fetchone()
    version = str(row[0]) if row and row[0] is not None else ""
    current_database = str(row[1]) if row and row[1] is not None else (database or "")
    return {
        "database": current_database,
        "version": version,
        "engine": "motherduck",
    }


class closing_connection:
    """Context manager yielding a fresh read-only MotherDuck connection, closed on exit."""

    def __init__(self, token: str, database: str | None = None) -> None:
        self._token = token
        self._database = database
        self._connection: duckdb.DuckDBPyConnection | None = None

    def __enter__(self) -> duckdb.DuckDBPyConnection:
        self._connection = connect(self._token, self._database)
        return self._connection

    def __exit__(self, *args: object) -> None:
        if self._connection is not None:
            self._connection.close()


def _build_sync_query(
    location: tuple[str, str, str],
    *,
    should_use_incremental_field: bool,
    incremental_field: str | None,
    incremental_field_type: IncrementalFieldType | None,
    db_incremental_field_last_value: Any,
    projected_columns: list[str] | None = None,
) -> tuple[str, dict[str, Any]]:
    database, schema, table = location
    if projected_columns is None:
        select_list = "*"
    else:
        select_list = ", ".join(_quote_identifier(column) for column in projected_columns)
    query = f"SELECT {select_list} FROM {qualified_table_name(database, schema, table)}"
    params: dict[str, Any] = {}
    if should_use_incremental_field and incremental_field is not None:
        if db_incremental_field_last_value is not None:
            # Without a field type (legacy rows) fall back to `>=`: it only re-ships the
            # boundary row, which the incremental merge dedupes by primary key.
            operator = incremental_type_to_operator(incremental_field_type) if incremental_field_type else ">="
            query += f" WHERE {_quote_identifier(incremental_field)} {operator} $incremental_last_value"
            params["incremental_last_value"] = db_incremental_field_last_value
        query += f" ORDER BY {_quote_identifier(incremental_field)} ASC"
    return query, params


# Bounded duplicate-primary-key probe: DuckDB constraints are the only *proven* unique keys,
# but the effective key can be user-overridden, so mirror the ClickHouse source's prefix probe
# rather than scanning the whole (compute-metered) table every sync.
DUPLICATE_PK_CHECK_ROW_BUDGET = 1_000_000


def check_duplicate_primary_keys(
    connection: duckdb.DuckDBPyConnection,
    location: tuple[str, str, str],
    primary_keys: list[str],
) -> bool | None:
    """Whether the effective primary key shows duplicates within a bounded table prefix.

    Returns None when the probe itself fails, so the caller doesn't block a sync on a
    diagnostic query."""
    quoted_keys = ", ".join(_quote_identifier(key) for key in primary_keys)
    database, schema, table = location
    query = (
        f"SELECT 1 FROM (SELECT {quoted_keys} FROM {qualified_table_name(database, schema, table)}"
        f" LIMIT {DUPLICATE_PK_CHECK_ROW_BUDGET})"
        f" GROUP BY {quoted_keys} HAVING count(*) > 1 LIMIT 1"
    )
    try:
        row = connection.execute(query).fetchone()
    except duckdb.Error:
        logger.warning("motherduck.check_duplicate_primary_keys_failed", exc_info=True)
        return None
    return row is not None


def motherduck_source(
    *,
    token: str,
    database: str | None,
    display_name: str,
    location: tuple[str, str, str],
    primary_keys: list[str] | None,
    should_use_incremental_field: bool = False,
    incremental_field: str | None = None,
    incremental_field_type: IncrementalFieldType | None = None,
    db_incremental_field_last_value: Any = None,
    projected_columns: list[str] | None = None,
    has_duplicate_primary_keys: bool | None = None,
    chunk_size: int = DEFAULT_SYNC_CHUNK_SIZE,
) -> SourceResponse:
    query, params = _build_sync_query(
        location,
        should_use_incremental_field=should_use_incremental_field,
        incremental_field=incremental_field,
        incremental_field_type=incremental_field_type,
        db_incremental_field_last_value=db_incremental_field_last_value,
        projected_columns=projected_columns,
    )

    def get_rows() -> Iterator[pa.Table]:
        with closing_connection(token, database) as connection:
            connection.execute(query, params or None)
            reader = connection.fetch_record_batch(rows_per_batch=chunk_size)
            for batch in reader:
                yield pa.Table.from_batches([batch])

    return SourceResponse(
        name=display_name,
        items=get_rows,
        primary_keys=primary_keys,
        has_duplicate_primary_keys=has_duplicate_primary_keys,
        sort_mode="asc",
    )


def get_primary_keys(
    connection: duckdb.DuckDBPyConnection,
    locations: list[tuple[str, str, str]],
) -> dict[tuple[str, str, str], list[str]]:
    """Primary-key columns per (database, schema, table), from duckdb_constraints()."""
    if not locations:
        return {}
    results: dict[tuple[str, str, str], list[str]] = {}
    try:
        rows = connection.execute(
            """
            SELECT database_name, schema_name, table_name, constraint_column_names
            FROM duckdb_constraints()
            WHERE constraint_type = 'PRIMARY KEY'
            """
        ).fetchall()
    except duckdb.Error:
        logger.warning("motherduck.get_primary_keys_failed", exc_info=True)
        return {}
    wanted = set(locations)
    for db, schema, table, column_names in rows:
        location = (str(db), str(schema), str(table))
        if location in wanted and isinstance(column_names, list) and column_names:
            results[location] = [str(name) for name in column_names]
    return results
