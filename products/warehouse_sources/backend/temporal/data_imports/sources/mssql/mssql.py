"""MSSQL driver for PostHog's data-warehouse import pipeline.

Everything MSSQL-specific — connection lifecycle (with SSH tunnel),
schema listing, per-cursor metadata for the streaming sync, the dlt
pipeline build, type conversions — lives on `MSSQLImplementation`.
The source-class `MSSQLSource` is a thin PostHog-layer wrapper that
just holds an instance and validates credentials.
"""

from __future__ import annotations

import time
import collections
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from typing import Any, TypeVar

import pyarrow as pa
import pymssql
import structlog
from structlog.types import FilteringBoundLogger

from posthog.exceptions_capture import capture_exception

from products.warehouse_sources.backend.temporal.data_imports.pipelines.helpers import (
    incremental_type_to_initial_value,
    incremental_type_to_operator,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    SourceInputs,
    SourceResponse,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.utils import (
    DEFAULT_NUMERIC_PRECISION,
    DEFAULT_NUMERIC_SCALE,
    build_pyarrow_decimal_type,
    table_from_iterator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import open_ssh_tunnel
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql import (
    BracketIdentifierQuoter,
    Column,
    Table,
    ValidatedRowFilter,
    compute_projected_columns,
    format_projected_select_clause,
    project_arrow_columns,
    render_named_conditions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.implementation import (
    SourceMetadata,
    SQLSourceImplementation,
    TableStats,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.incremental import (
    IncrementalFieldFilter,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.location import (
    normalize_namespace,
    resolve_source_location,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import MSSQLSourceConfig
from products.warehouse_sources.backend.types import IncrementalFieldType

__all__ = [
    "MSSQLColumn",
    "MSSQLImplementation",
    "filter_mssql_incremental_fields",
]

_IDENTIFIER_QUOTER = BracketIdentifierQuoter()

# Schemas every MSSQL database ships with that never hold user tables. `db_*` covers the
# fixed database roles (db_owner, db_datareader, …), which also surface as schemas.
SYSTEM_MSSQL_SCHEMAS = ("sys", "guest", "INFORMATION_SCHEMA")

_T = TypeVar("_T")

# DB-Lib error 20047 — "DBPROCESS is dead or not enabled". The TDS connection died mid-stream (an
# idle cull, a failover, a brief network blip), leaving pymssql's dbprocess dead so the in-flight
# fetch raises. A fresh connection recovers, so this is transient rather than a config error.
_TRANSIENT_CONNECTION_ERROR = "DBPROCESS is dead or not enabled"
_MAX_DISCOVERY_CONNECTION_ATTEMPTS = 5

# SQL Server error 1205 — this session was picked as the deadlock victim and its transaction was
# rolled back to break a lock cycle with a concurrent process. SQL Server's own guidance is to
# rerun the transaction: lock contention is momentary, so re-running the identical query usually
# succeeds. Transient lock contention, not a config or data problem.
_DEADLOCK_VICTIM_ERROR = "was deadlocked on lock resources"
_MAX_DEADLOCK_ATTEMPTS = 5

# paramiko raises a bare, message-less EOFError from `start_client` when the SSH gateway accepts
# the TCP connection but closes it during the SSH handshake — a non-SSH service on the port, a
# bastion refusing PostHog's IPs, or a proxy that resets the stream. sshtunnel doesn't wrap it, so
# it escapes as an EOFError whose `str()` is empty, matching no non-retryable rule and retrying
# forever. `connect` translates it into this stable, classifiable message (see
# `MSSQLSource.get_non_retryable_errors`) — same gateway-config class as a wrapped tunnel failure.
_SSH_HANDSHAKE_EOF_ERROR = "SSH gateway closed the connection during the SSH handshake"

# Raised by `get_table_metadata` when INFORMATION_SCHEMA.COLUMNS returns no rows for a table we
# were asked to sync — the table was dropped or renamed at the source after schema discovery (or
# its schema/name no longer matches under the server's collation). Unlike a live SELECT against a
# missing object (SQL Server error 208, "Invalid object name"), this metadata lookup returns an
# empty result set rather than erroring, so this guard fires first. Retrying replays the identical
# lookup and gets the same empty result, so it's classified non-retryable (see
# `MSSQLSource.get_non_retryable_errors`). Kept as a stable prefix so the match stays clear of the
# volatile schema/table name that follows it.
_TABLE_NOT_FOUND_ERROR = "Table not found when reading column metadata"


def _is_transient_connection_error(error: BaseException) -> bool:
    """True for a mid-stream TDS connection death that a fresh connection recovers from."""
    message = " ".join(str(arg) for arg in error.args) if error.args else str(error)
    return _TRANSIENT_CONNECTION_ERROR in message


def _is_deadlock_victim_error(error: BaseException) -> bool:
    """True for a SQL Server 1205 deadlock-victim error that a rerun recovers from."""
    message = " ".join(str(arg) for arg in error.args) if error.args else str(error)
    return _DEADLOCK_VICTIM_ERROR in message


def retry_on_transient_connection_error(
    operation: Callable[[], _T],
    *,
    max_attempts: int = _MAX_DISCOVERY_CONNECTION_ATTEMPTS,
) -> _T:
    """Run `operation`, retrying a transient MSSQL connection death with bounded backoff.

    Mirrors the in-process discovery retry the Postgres and MySQL sources use: a momentary
    connection death recovers on a fresh connect-and-discover cycle, so retry it here instead of
    failing schema discovery on the first blip and surfacing it as captured error-tracking noise.
    Permanent errors re-raise immediately — `_is_transient_connection_error` only matches the
    transient mid-stream drop.
    """
    attempt = 0
    while True:
        try:
            return operation()
        except pymssql.Error as e:
            attempt += 1
            if attempt >= max_attempts or not _is_transient_connection_error(e):
                raise
            structlog.get_logger().warning(
                "Transient MSSQL connection death during schema discovery; retrying",
                attempt=attempt,
                max_attempts=max_attempts,
                exc_info=e,
            )
            time.sleep(min(2 * attempt, 30))


def retry_on_deadlock(
    operation: Callable[[], _T],
    *,
    max_attempts: int = _MAX_DEADLOCK_ATTEMPTS,
    logger: FilteringBoundLogger | None = None,
) -> _T:
    """Run `operation`, rerunning it with bounded backoff when SQL Server picks us as the deadlock victim.

    A 1205 rolls back our transaction to break the lock cycle, so rerunning the identical query is
    safe and usually succeeds once the contending process releases its locks. Used around the read
    query before any rows are streamed — retrying mid-stream would re-yield already-emitted rows.
    Anything other than a deadlock victim re-raises immediately.
    """
    attempt = 0
    while True:
        try:
            return operation()
        except pymssql.Error as e:
            attempt += 1
            if attempt >= max_attempts or not _is_deadlock_victim_error(e):
                raise
            (logger or structlog.get_logger()).warning(
                "MSSQL query chosen as deadlock victim; rerunning",
                attempt=attempt,
                max_attempts=max_attempts,
                exc_info=e,
            )
            time.sleep(min(2 * attempt, 30))


def _non_system_schema_clause(column: str) -> tuple[str, dict[str, str]]:
    """Predicate excluding MSSQL system schemas + the fixed `db_*` database roles.

    `db[_]%` brackets the `_` so it matches literally (it is a LIKE wildcard otherwise);
    `%%` survives pymssql's pyformat paramstyle since a params dict is always passed.
    """
    params = {f"sys_schema_{index}": name for index, name in enumerate(SYSTEM_MSSQL_SCHEMAS)}
    placeholders = ", ".join(f"%(sys_schema_{index})s" for index in range(len(SYSTEM_MSSQL_SCHEMAS)))
    clause = f"{column} NOT IN ({placeholders}) AND {column} NOT LIKE 'db[_]%%'"
    return clause, params


def _unqualified_table(display: str) -> str:
    """The table part of a qualified `schema.table` (or the whole name if unqualified)."""
    return display.partition(".")[2] or display


def _filter_qualified_tables(
    all_tables: dict[str, list[tuple[str, str, bool]]], names: list[str]
) -> dict[str, list[tuple[str, str, bool]]]:
    """Keep only the requested tables from a qualified (`schema.table`) discovery.

    Matches a qualified name directly; a legacy bare `table` (a pre-migration row whose
    name isn't qualified yet) matches every discovered `*.table`.
    """
    filtered: dict[str, list[tuple[str, str, bool]]] = {}
    for name in names:
        if name in all_tables:
            filtered[name] = all_tables[name]
            continue
        if "." not in name:
            for display, columns in all_tables.items():
                if display.partition(".")[2] == name:
                    filtered[display] = columns
    return filtered


def filter_mssql_incremental_fields(
    columns: list[tuple[str, str, bool]],
) -> list[tuple[str, IncrementalFieldType, bool]]:
    results: list[tuple[str, IncrementalFieldType, bool]] = []
    for column_name, type, nullable in columns:
        type = type.lower()
        if type == "date":
            results.append((column_name, IncrementalFieldType.Date, nullable))
        elif type == "datetime" or type == "datetime2" or type == "smalldatetime":
            results.append((column_name, IncrementalFieldType.DateTime, nullable))
        elif type == "tinyint" or type == "smallint" or type == "int" or type == "bigint":
            results.append((column_name, IncrementalFieldType.Integer, nullable))

    return results


def _build_query(
    schema: str,
    table_name: str,
    should_use_incremental_field: bool,
    incremental_field: str | None,
    incremental_field_type: IncrementalFieldType | None,
    db_incremental_field_last_value: Any | None,
    add_limit: bool = False,
    enabled_columns: list[str] | None = None,
    primary_keys: list[str] | None = None,
    row_filters: list[ValidatedRowFilter] | None = None,
) -> tuple[str, dict[str, Any]]:
    # Every identifier interpolated below is validated by the bracket
    # quoter — bad input (`;`, `]`, whitespace, etc.) raises before any
    # SQL is built. Parameter values still flow through pymssql binding.
    qualified_table = _IDENTIFIER_QUOTER.quote_qualified(schema, table_name)
    top = "TOP 100 " if add_limit else ""
    projected = compute_projected_columns(enabled_columns, primary_keys, incremental_field)
    select_clause = format_projected_select_clause(projected, _IDENTIFIER_QUOTER)
    base_query = f"SELECT {top}{select_clause} FROM {qualified_table}"

    filter_conditions, filter_params = render_named_conditions(row_filters or [], _IDENTIFIER_QUOTER)

    if not should_use_incremental_field:
        if filter_conditions:
            return f"{base_query} WHERE {' AND '.join(filter_conditions)}", filter_params
        return base_query, {}

    if incremental_field is None or incremental_field_type is None:
        raise ValueError("incremental_field and incremental_field_type can't be None")

    if db_incremental_field_last_value is None:
        db_incremental_field_last_value = incremental_type_to_initial_value(incremental_field_type)

    operator = incremental_type_to_operator(incremental_field_type)
    quoted_incremental = _IDENTIFIER_QUOTER.quote(incremental_field)
    conditions = [f"{quoted_incremental} {operator} %(incremental_value)s", *filter_conditions]
    query = f"{base_query} WHERE {' AND '.join(conditions)}"
    # it is only safe to have this order by nested in a CTE if TOP is also specified
    # ordering for incremental sync purposes where TOP is not specified is handled in get_rows()
    if add_limit:
        query = f"{query} ORDER BY {quoted_incremental} ASC"

    return query, {"incremental_value": db_incremental_field_last_value, **filter_params}


class MSSQLColumn(Column):
    """Implementation of the `Column` protocol for a MSSQL source.

    Attributes:
        name: The column's name.
        data_type: The name of the column's data type as described in
            https://learn.microsoft.com/en-us/sql/t-sql/data-types/data-types-transact-sql.
        nullable: Whether the column is nullable or not.
        numeric_precision: The number of significant digits. Only used with
            numeric `data_type`s, otherwise `None`.
        numeric_scale: The number of significant digits to the right of
            decimal point. Only used with numeric `data_type`s, otherwise
            `None`.
    """

    def __init__(
        self,
        name: str,
        data_type: str,
        nullable: bool,
        numeric_precision: int | None = None,
        numeric_scale: int | None = None,
    ) -> None:
        self.name = name
        self.data_type = data_type
        self.nullable = nullable
        self.numeric_precision = numeric_precision
        self.numeric_scale = numeric_scale

    def to_arrow_field(self) -> pa.Field[pa.DataType]:
        """Return a `pyarrow.Field` that closely matches this column."""
        arrow_type: pa.DataType

        match self.data_type:
            case "bigint":
                arrow_type = pa.int64()
            case "int" | "integer":
                arrow_type = pa.int32()
            case "smallint":
                arrow_type = pa.int16()
            case "tinyint":
                arrow_type = pa.int8()
            case "decimal" | "numeric" | "money":
                if not self.numeric_precision or not self.numeric_scale:
                    raise TypeError("expected `numeric_precision` and `numeric_scale` to be `int`, got `NoneType`")

                arrow_type = build_pyarrow_decimal_type(self.numeric_precision, self.numeric_scale)
            case "float" | "real":
                arrow_type = pa.float64()
            case "varchar" | "char" | "text" | "nchar" | "nvarchar" | "ntext":
                arrow_type = pa.string()
            case "date":
                arrow_type = pa.date32()
            case "datetime" | "datetime2" | "smalldatetime" | "datetimeoffset":
                arrow_type = pa.timestamp("us")
            case "time":
                arrow_type = pa.time64("us")
            case "bit" | "boolean" | "bool":
                arrow_type = pa.bool_()
            case "binary" | "varbinary" | "image":
                arrow_type = pa.binary()
            case "json":
                arrow_type = pa.string()
            case _:
                arrow_type = pa.string()

        return pa.field(self.name, arrow_type, nullable=self.nullable)


class MSSQLImplementation(SQLSourceImplementation[MSSQLSourceConfig, pymssql.Connection, pymssql.Cursor]):  # ty: ignore[invalid-type-arguments]
    """MSSQL driver implementation paired with `MSSQLSource`.

    One class owns everything MSSQL-specific: the SSH tunnel + pymssql
    connection lifecycle, `information_schema` / `sys.*` batch queries
    used during schema listing, per-cursor metadata used during the
    streaming sync (primary keys, column types, row counts,
    partition/chunk sizing), and the dlt pipeline factory
    (`build_pipeline`).
    """

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    @contextmanager
    def connect(self, config: MSSQLSourceConfig) -> Iterator[pymssql.Connection]:
        """Open a pymssql connection for the duration of the context.

        Opens the SSH tunnel (if configured) once, then connects with the
        MSSQL-wide conventions: 5s login timeout.
        """
        with self._ssh_tunnel_endpoint(config) as (host, port):
            with pymssql.connect(
                server=host,
                # pymssql requires port to be str
                port=str(port),
                database=config.database,
                user=config.user,
                password=config.password,
                login_timeout=5,
            ) as conn:
                yield conn

    @contextmanager
    def _ssh_tunnel_endpoint(self, config: MSSQLSourceConfig) -> Iterator[tuple[str, int]]:
        """Yield the `(host, port)` to connect to, going through the SSH tunnel if configured.

        Translates a bare paramiko handshake `EOFError` into `_SSH_HANDSHAKE_EOF_ERROR`. The
        `yield` sits outside the `except` so a failure raised by the connection body can never be
        misattributed to the tunnel handshake.
        """
        with ExitStack() as stack:
            try:
                host, port = stack.enter_context(open_ssh_tunnel(config))
            except EOFError as e:
                raise Exception(_SSH_HANDSHAKE_EOF_ERROR) from e
            yield host, port

    # ------------------------------------------------------------------
    # Listing — batch queries run once during `get_schemas`
    # ------------------------------------------------------------------

    def get_columns(
        self,
        conn: pymssql.Connection,
        config: MSSQLSourceConfig,
        names: list[str] | None,
    ) -> dict[str, list[tuple[str, str, bool]]]:
        """Discover columns per table.

        With a namespace set, lists that one schema and keys by bare table name (the
        single-schema fast path). With a blank namespace, lists every non-system schema
        and keys by qualified `schema.table` so duplicate table names stay distinct.
        """
        selected_schema = normalize_namespace(config.schema)
        qualify = selected_schema is None

        params: dict[str, Any] = {}
        if selected_schema is not None:
            schema_clause = "table_schema = %(schema)s"
            params["schema"] = selected_schema
        else:
            schema_clause, sys_params = _non_system_schema_clause("table_schema")
            params.update(sys_params)

        # Single-schema names are bare and can be pushed into SQL; multi-schema names arrive
        # qualified (`schema.table`), so they're filtered in Python after discovery.
        names_filter = ""
        if names and not qualify:
            params["names"] = tuple(names)
            names_filter = "AND table_name IN %(names)s"

        with conn.cursor(as_dict=False) as cursor:
            cursor.execute(
                "SELECT table_schema, table_name, column_name, data_type, is_nullable"
                " FROM information_schema.columns"
                f" WHERE {schema_clause} {names_filter}"
                " ORDER BY table_schema ASC, table_name ASC",
                params,
            )

            schema_list: dict[str, list[tuple[str, str, bool]]] = collections.defaultdict(list)

            for row in cursor:
                if not row:
                    continue
                table_schema, table_name, column_name, data_type, is_nullable = row
                display = f"{table_schema}.{table_name}" if qualify else table_name
                schema_list[display].append((column_name, data_type, is_nullable == "YES"))

        columns_by_table = dict(schema_list)
        if names and qualify:
            return _filter_qualified_tables(columns_by_table, names)
        return columns_by_table

    def get_primary_keys(
        self,
        conn: pymssql.Connection,
        config: MSSQLSourceConfig,
        tables: list[str],
    ) -> dict[str, list[str] | None]:
        """Detect primary keys for all tables in a single query.

        Permission-sensitive — some MSSQL deployments restrict access to
        `sys.indexes` / `sys.tables`. Swallow and log any failure so
        schema discovery keeps working without PKs. With a blank namespace,
        scans every non-system schema and keys by qualified `schema.table`.
        """
        result: dict[str, list[str] | None] = dict.fromkeys(tables)
        if not tables:
            return result

        selected_schema = normalize_namespace(config.schema)
        base_query = """
            SELECT s.name AS schema_name, t.name AS table_name, c.name AS column_name
            FROM sys.indexes i
            JOIN sys.index_columns ic ON i.object_id = ic.object_id AND i.index_id = ic.index_id
            JOIN sys.columns c ON ic.object_id = c.object_id AND ic.column_id = c.column_id
            JOIN sys.tables t ON i.object_id = t.object_id
            JOIN sys.schemas s ON t.schema_id = s.schema_id
            WHERE i.is_primary_key = 1
        """
        # Bound the scan by table name server-side even in multi-schema mode (where two
        # schemas can share a name → false positives the `if display in result` guard drops).
        params: dict[str, Any] = {}
        if selected_schema is not None:
            schema_clause = "s.name = %(schema)s"
            params["schema"] = selected_schema
            params["names"] = tuple(tables)
        else:
            schema_clause, sys_params = _non_system_schema_clause("s.name")
            params.update(sys_params)
            params["names"] = tuple({_unqualified_table(table) for table in tables})
        query = base_query + f" AND {schema_clause} AND t.name IN %(names)s ORDER BY s.name, t.name, ic.key_ordinal"

        try:
            with conn.cursor(as_dict=False) as cursor:
                cursor.execute(query, params)
                rows = cursor.fetchall()
        except Exception as e:
            structlog.get_logger().warning("Failed to detect primary keys for MSSQL schemas", exc_info=e)
            return result

        pks: dict[str, list[str]] = collections.defaultdict(list)
        for schema_name, table_name, column_name in rows or []:
            display = f"{schema_name}.{table_name}" if selected_schema is None else table_name
            if display in result:
                pks[display].append(column_name)
        for display, pk_cols in pks.items():
            result[display] = pk_cols
        return result

    def get_incremental_filter(self) -> IncrementalFieldFilter:
        return filter_mssql_incremental_fields

    def get_source_metadata(
        self,
        conn: pymssql.Connection,
        config: MSSQLSourceConfig,
        tables: list[str],
    ) -> SourceMetadata:
        """Per-table catalog/schema/table-name overrides for the qualified display names.

        `catalog` is the connected database (display only); `schema` is the source
        namespace; `table` is unqualified. Persisted into `schema_metadata` so per-row
        sync routes to the right namespace without re-querying the catalog.
        """
        selected_schema = normalize_namespace(config.schema)
        catalog_by_table: dict[str, str | None] = {}
        schema_by_table: dict[str, str | None] = {}
        table_name_by_table: dict[str, str | None] = {}
        for display in tables:
            schema: str | None
            if selected_schema is None and "." in display:
                schema, _, table = display.partition(".")
            else:
                schema = selected_schema
                table = display
            catalog_by_table[display] = config.database
            schema_by_table[display] = schema
            table_name_by_table[display] = table
        return SourceMetadata(
            catalog_by_table=catalog_by_table,
            schema_by_table=schema_by_table,
            table_name_by_table=table_name_by_table,
        )

    def get_leading_index_columns(
        self,
        conn: pymssql.Connection,
        config: MSSQLSourceConfig,
        tables: list[str],
    ) -> dict[str, set[str]] | None:
        """Return the leading column of each index per table.

        `sys.index_columns.key_ordinal = 1` identifies the first key column of an
        index. `is_included_column = 0` excludes columns that are only payload of
        a covering index — those don't accelerate `WHERE col >= …` predicates.
        `i.has_filter = 0` excludes filtered indexes for the same reason Postgres
        excludes partial indexes: a filtered index only accelerates queries whose
        predicate the planner can prove implies the index filter, which the
        incremental sync's `WHERE col >= last_max` generally won't satisfy. Crediting
        the leading column would suppress a warning the user genuinely needs.
        `i.is_disabled = 0` excludes disabled indexes (the planner won't use them).
        Heap tables (no clustered index) and tables with no indexes return an empty
        set so the UI warning fires for them.

        Returns None when discovery fails.
        """
        if not tables:
            return {}

        result: dict[str, set[str]] = {table: set() for table in tables}

        selected_schema = normalize_namespace(config.schema)
        base_query = """
            SELECT s.name AS schema_name, t.name AS table_name, c.name AS column_name
            FROM sys.indexes i
            JOIN sys.index_columns ic ON i.object_id = ic.object_id AND i.index_id = ic.index_id
            JOIN sys.columns c ON ic.object_id = c.object_id AND ic.column_id = c.column_id
            JOIN sys.tables t ON i.object_id = t.object_id
            JOIN sys.schemas s ON t.schema_id = s.schema_id
            WHERE ic.key_ordinal = 1
              AND ic.is_included_column = 0
              AND i.has_filter = 0
              AND i.is_disabled = 0
        """
        # Bound the scan by table name server-side even in multi-schema mode; the
        # `if display in result` guard drops any same-name false positives.
        params: dict[str, Any] = {}
        if selected_schema is not None:
            schema_clause = "s.name = %(schema)s"
            params["schema"] = selected_schema
            params["names"] = tuple(tables)
        else:
            schema_clause, sys_params = _non_system_schema_clause("s.name")
            params.update(sys_params)
            params["names"] = tuple({_unqualified_table(table) for table in tables})
        query = base_query + f" AND {schema_clause} AND t.name IN %(names)s"

        try:
            with conn.cursor(as_dict=False) as cursor:
                cursor.execute(query, params)
                for schema_name, table_name, column_name in cursor.fetchall() or []:
                    display = f"{schema_name}.{table_name}" if selected_schema is None else table_name
                    if display in result:
                        result[display].add(column_name)
        except Exception as e:
            structlog.get_logger().warning("Failed to detect leading index columns for MSSQL schemas", exc_info=e)
            return None

        return result

    # ------------------------------------------------------------------
    # Per-cursor metadata — used during `build_pipeline`
    # ------------------------------------------------------------------

    def get_primary_keys_for_table(self, cursor: pymssql.Cursor, schema: str, table_name: str) -> list[str] | None:
        """Return the primary-key column names for a single table, or None."""
        query = """
            SELECT c.name AS column_name
            FROM sys.indexes i
            JOIN sys.index_columns ic ON i.object_id = ic.object_id AND i.index_id = ic.index_id
            JOIN sys.columns c ON ic.object_id = c.object_id AND ic.column_id = c.column_id
            JOIN sys.tables t ON i.object_id = t.object_id
            JOIN sys.schemas s ON t.schema_id = s.schema_id
            WHERE i.is_primary_key = 1
            AND s.name = %(schema)s
            AND t.name = %(table_name)s
            ORDER BY ic.key_ordinal"""

        cursor.execute(
            query,
            {
                "schema": schema,
                "table_name": table_name,
            },
        )
        rows = cursor.fetchall()
        if not rows:
            return None

        return [row[0] for row in rows]

    def get_table_metadata(self, cursor: pymssql.Cursor, schema: str, table_name: str) -> Table[MSSQLColumn]:
        """Return rich column metadata for building a PyArrow schema."""
        query = """
            SELECT
                COLUMN_NAME,
                DATA_TYPE,
                CASE IS_NULLABLE WHEN 'YES' THEN 1 ELSE 0 END as IS_NULLABLE,
                NUMERIC_PRECISION,
                NUMERIC_SCALE
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = %(schema)s
            AND TABLE_NAME = %(table_name)s
            ORDER BY ORDINAL_POSITION"""

        cursor.execute(
            query,
            {
                "schema": schema,
                "table_name": table_name,
            },
        )

        numeric_data_types = {"numeric", "decimal", "money"}
        columns = []
        for row in cursor:
            if row is None:
                break

            name, data_type, nullable, numeric_precision_candidate, numeric_scale_candidate = row
            if data_type in numeric_data_types:
                numeric_precision = numeric_precision_candidate or DEFAULT_NUMERIC_PRECISION
                numeric_scale = numeric_scale_candidate or DEFAULT_NUMERIC_SCALE
            else:
                numeric_precision = None
                numeric_scale = None

            columns.append(
                MSSQLColumn(
                    name=name,
                    data_type=data_type,
                    nullable=nullable,
                    numeric_precision=numeric_precision,
                    numeric_scale=numeric_scale,
                )
            )

        if not columns:
            raise ValueError(f"{_TABLE_NOT_FOUND_ERROR}: {schema}.{table_name}")

        return Table(
            name=table_name,
            parents=(schema,),
            columns=columns,
        )

    def fetch_table_stats(
        self,
        cursor: pymssql.Cursor,
        schema: str,
        table_name: str,
        logger: FilteringBoundLogger,
    ) -> TableStats | None:
        """Return table size + row count from `sp_spaceused`.

        Uses sp_spaceused which is the official way to get accurate table size and row count.
        Falls back to the older single-arg form for SQL Server versions before 2012.
        Returns `None` on any failure so the base class falls back to safe defaults.
        """
        # `sp_spaceused` receives the qualified name as a *parameter* (not
        # interpolated), but validate it through the quoter anyway so an
        # injection attempt in `schema` / `table_name` is rejected at the
        # boundary rather than leaning on driver parameter binding.
        full_table_name = _IDENTIFIER_QUOTER.quote_qualified(schema, table_name)
        try:
            try:
                cursor.execute(
                    "EXEC sp_spaceused %(full_table_name)s, @updateusage = 'TRUE'", {"full_table_name": full_table_name}
                )
            except Exception:
                # If @updateusage parameter fails, try the older version
                cursor.execute("EXEC sp_spaceused %(full_table_name)s", {"full_table_name": full_table_name})

            result = cursor.fetchone()
            if result is None:
                logger.debug("fetch_table_stats: sp_spaceused returned no results")
                return None

            # sp_spaceused returns: name, rows, reserved, data, index_size, unused
            _, total_rows, _, data_size, _, _ = result

            # Views (and other storage-less objects) return NULL for rows/data
            # from sp_spaceused. Treat that as "no stats available" and fall
            # back to safe defaults rather than crashing on int(None).
            if total_rows is None or data_size is None:
                logger.debug("fetch_table_stats: sp_spaceused returned NULL row count or data size")
                return None

            total_rows = int(total_rows)

            # Parse size with unit (e.g. "1024.45 MB" -> 1024.45, "MB")
            size_parts = data_size.strip().split(" ")
            if len(size_parts) != 2:
                logger.debug(f"fetch_table_stats: Invalid sp_spaceused result: expected 2 parts, got {len(size_parts)}")
                return None

            size_value = float(size_parts[0])
            unit = size_parts[1].upper()

            multiplier = {
                "KB": 1024,
                "MB": 1024 * 1024,
                "GB": 1024 * 1024 * 1024,
                "TB": 1024 * 1024 * 1024 * 1024,
            }.get(unit)
            if multiplier is None:
                logger.debug(f"fetch_table_stats: Unexpected unit '{unit}' in sp_spaceused result")
                return None

            total_bytes = int(size_value * multiplier)
            return TableStats(table_size_bytes=total_bytes, row_count=total_rows)
        except Exception as e:
            logger.debug(f"fetch_table_stats: Error: {e}. Returning None", exc_info=e)
            capture_exception(e)
            return None

    def fetch_average_row_size(
        self,
        cursor: pymssql.Cursor,
        schema: str,
        table_name: str,
        inner_query: str,
        inner_query_args: Any,
        logger: FilteringBoundLogger,
    ) -> int | None:
        """Sample `DATALENGTH(col)` across columns on a `SELECT TOP 100` query.

        Unlike other drivers, MSSQL uses an unconditional `SELECT TOP 100 *`
        rather than the live `inner_query`. MSSQL has no `LIMIT N` keyword,
        and wrapping the incremental query in a sub-select for size sampling
        adds complexity without meaningfully improving the estimate (row sizes
        don't vary much across time windows). `inner_query` and
        `inner_query_args` are accepted for API parity with the base class but
        are intentionally ignored.
        """
        try:
            # `inner_query` / `inner_query_args` accepted for API parity only.
            del inner_query, inner_query_args

            # Get column names from the table
            cursor.execute(
                "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = %(schema)s AND TABLE_NAME = %(table)s ORDER BY ORDINAL_POSITION",
                {"schema": schema, "table": table_name},
            )
            rows = cursor.fetchall()
            if not rows:
                logger.debug("fetch_average_row_size: No columns found.")
                return None

            columns = [row[0] for row in rows]
            # Column names come from INFORMATION_SCHEMA but must still be
            # validated before SQL interpolation — `DATALENGTH(...)` has no
            # parameterized form.
            datalength_sum = " + ".join(f"DATALENGTH({_IDENTIFIER_QUOTER.quote(col)})" for col in columns)

            sample_query = f"SELECT TOP 100 * FROM {_IDENTIFIER_QUOTER.quote_qualified(schema, table_name)}"
            size_query = f"SELECT AVG({datalength_sum}) as avg_row_size FROM ({sample_query}) as t"

            cursor.execute(size_query)
            row = cursor.fetchone()

            if row is None or row[0] is None:
                logger.debug("fetch_average_row_size: No results returned.")
                return None

            row_size_bytes = max(row[0] or 0, 1)
            return int(row_size_bytes)
        except Exception as e:
            logger.debug(f"fetch_average_row_size: Error: {e}.", exc_info=e)
            capture_exception(e)
            return None

    # ------------------------------------------------------------------
    # Pipeline build — the dlt `SourceResponse` for a single table
    # ------------------------------------------------------------------

    def build_pipeline(self, config: MSSQLSourceConfig, inputs: SourceInputs) -> SourceResponse:
        # Resolve the per-row namespace + table from `schema_metadata` (multi-schema) or the
        # config namespace (legacy single-schema). `response_name` keeps the legacy Delta path.
        # No fallback namespace: every real source either has a config schema or carries
        # per-row metadata, so a missing schema means a genuinely broken row — fail loudly
        # rather than guess a namespace and sync the wrong table.
        location = resolve_source_location(inputs, config_namespace=config.schema)
        schema = location.schema
        table_name = location.table_name
        if not table_name:
            raise ValueError("Table name is missing")
        if not schema:
            raise ValueError("Schema is missing")

        logger = inputs.logger
        should_use_incremental_field = inputs.should_use_incremental_field
        incremental_field = inputs.incremental_field
        incremental_field_type = inputs.incremental_field_type
        db_incremental_field_last_value = inputs.db_incremental_field_last_value
        enabled_columns = inputs.enabled_columns
        row_filters = inputs.row_filters

        with self.connect(config) as connection:
            with connection.cursor() as cursor:
                primary_keys = self.get_primary_keys_for_table(cursor, schema, table_name)
                full_table = self.get_table_metadata(cursor, schema, table_name)

                # Resolve PKs before projection so SELECT and Arrow schema agree.
                if primary_keys is None and "id" in full_table:
                    primary_keys = ["id"]

                projected = compute_projected_columns(enabled_columns, primary_keys, incremental_field)
                table = project_arrow_columns(full_table, projected)
                arrow_schema = table.to_arrow_schema()
                logger.debug(f"Source schema: {arrow_schema}")

                inner_query, inner_query_args = _build_query(
                    schema,
                    table_name,
                    should_use_incremental_field,
                    incremental_field,
                    incremental_field_type,
                    db_incremental_field_last_value,
                    enabled_columns=enabled_columns,
                    primary_keys=primary_keys,
                    row_filters=row_filters,
                )

                rows_to_sync = self.get_rows_to_sync(cursor, inner_query, inner_query_args, logger)
                chunk_size = self.get_chunk_size(cursor, schema, table_name, inner_query, inner_query_args, logger)
                partition_settings = (
                    self.get_partition_settings(cursor, schema, table_name, logger)
                    if should_use_incremental_field
                    else None
                )

        def get_rows() -> Iterator[Any]:
            with self.connect(config) as streaming_connection:
                with streaming_connection.cursor() as cursor:
                    query, args = _build_query(
                        schema,
                        table_name,
                        should_use_incremental_field,
                        incremental_field,
                        incremental_field_type,
                        db_incremental_field_last_value,
                        enabled_columns=enabled_columns,
                        primary_keys=primary_keys,
                        row_filters=row_filters,
                    )
                    if incremental_field:
                        query = f"{query} ORDER BY {_IDENTIFIER_QUOTER.quote(incremental_field)} ASC"

                    logger.debug(f"MS SQL query: {query} with args: {args}")

                    retry_on_deadlock(lambda: cursor.execute(query, args), logger=logger)

                    column_names = [column[0] for column in cursor.description or []]

                    while True:
                        rows = cursor.fetchmany(chunk_size)
                        if not rows:
                            break

                        yield table_from_iterator((dict(zip(column_names, row)) for row in rows), arrow_schema)

        return SourceResponse(
            name=location.response_name,
            items=get_rows,
            primary_keys=primary_keys,
            partition_count=partition_settings.partition_count if partition_settings else None,
            partition_size=partition_settings.partition_size if partition_settings else None,
            rows_to_sync=rows_to_sync,
        )
