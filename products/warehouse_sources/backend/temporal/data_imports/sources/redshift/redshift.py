"""Redshift driver for PostHog's data-warehouse import pipeline.

Everything Redshift-specific — psycopg connection lifecycle (with SSH
tunnel), schema listing, sortkey discovery, per-cursor metadata for the
streaming sync, and the dlt pipeline build — lives on
`RedshiftImplementation`. The source-class `RedshiftSource` is a thin
PostHog-layer wrapper that just holds an instance and validates
credentials.
"""

from __future__ import annotations

import time
import collections
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import date
from typing import Any, Literal, LiteralString, Optional, TypeVar, cast

import psycopg
import pyarrow as pa
import structlog
from psycopg import pq, sql
from psycopg.adapt import Loader
from psycopg.pq import TransactionStatus
from structlog.types import FilteringBoundLogger

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import (
    DEFAULT_NUMERIC_PRECISION,
    DEFAULT_NUMERIC_SCALE,
    BinaryColumnReporter,
    QueryTimeoutException,
    TemporaryFileSizeExceedsLimitException,
    build_pyarrow_decimal_type,
    table_from_iterator,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.helpers import (
    incremental_type_to_initial_value,
    incremental_type_to_operator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import open_ssh_tunnel
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql import (
    Column,
    Table,
    ValidatedRowFilter,
    compute_projected_columns,
    project_arrow_columns,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.predicates_psycopg import (
    and_join,
    render_psycopg_row_filter_conditions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.redshift import (
    RedshiftSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.util import NonRetryableException
from products.warehouse_sources.backend.types import IncrementalFieldType, PartitionSettings

__all__ = [
    "JsonAsStringLoader",
    "RedshiftColumn",
    "RedshiftImplementation",
    "SafeDateLoader",
    "filter_redshift_incremental_fields",
]


# Shared psycopg.connect kwargs for Redshift. SSL is required; the SSL
# cert paths are intentionally pointed at non-existent files so psycopg
# uses the system default verification without picking up an unintended
# client cert.
#
# TCP keepalives bound a *post-connect* socket stall. `connect_timeout` only
# covers establishing the connection — once connected, a query blocks in
# psycopg's `wait_c` for as long as the socket stays open with no response.
# If the Redshift peer goes away mid-query (cluster pause/resize, network
# drop), that wait would otherwise hang until the Temporal activity hits its
# `start_to_close_timeout` and cancels the worker thread, surfacing a
# misleading `CancelledError` and burning the whole activity budget. With
# keepalives a dead peer is detected in ~30-60s and raised as a fast,
# retryable `OperationalError` instead. These only fire when the peer stops
# responding, so they never interrupt a healthy long-running streaming sync.
_REDSHIFT_CONNECT_OPTS: dict[str, Any] = {
    "sslmode": "require",
    "connect_timeout": 15,
    "keepalives": 1,
    "keepalives_idle": 30,
    "keepalives_interval": 10,
    "keepalives_count": 3,
    "tcp_user_timeout": 60000,  # 60s: force-close if sent data stays unacked
    "sslrootcert": "/tmp/no.txt",
    "sslcert": "/tmp/no.txt",
    "sslkey": "/tmp/no.txt",
    "options": "-c client_encoding=UTF8",
}


# Schemas excluded from blank-namespace (all-schema) discovery. Redshift exposes the Postgres
# system catalogs plus `pg_automv` (auto-materialized views) and per-session `pg_temp_*` schemas.
SYSTEM_REDSHIFT_SCHEMAS = ["pg_catalog", "information_schema", "pg_internal", "pg_automv"]

# Redshift stamps internal bookkeeping columns onto materialized views — e.g.
# `padb_internal_txn_id_col` and `padb_internal_txn_seq_col`. They appear in
# `information_schema.columns` but `SELECT *` never returns them, so leaving them in the
# discovered schema makes the Arrow schema disagree with the streamed rows and
# `pa.Table.from_pydict` raises a `KeyError`. The `padb_internal` prefix is Redshift-reserved.
REDSHIFT_INTERNAL_COLUMN_LIKE = "padb_internal%"

# A single-node Redshift cluster rejects any `FETCH FORWARD` above 1000 rows with
# "Fetch size N exceeds the limit of 1000 for a single node configuration". The limit is fixed by
# the node topology, so a cluster that rejects one fetch rejects every fetch: without a retry at
# this size the server cursor is unreachable on such clusters and every sync degrades to a
# client-side read of the whole table.
REDSHIFT_SINGLE_NODE_FETCH_LIMIT = 1000

# Rows libpq hands over per chunk while streaming. Only the delivery granularity — the server sends
# the result set at its own pace either way — so this trades per-row Python overhead against the
# transient list held between yields. Chunked delivery needs libpq 17; older builds fall back to
# row-at-a-time, which streams just as correctly.
REDSHIFT_STREAM_ROWS_PER_CHUNK = 1000
_LIBPQ_CHUNKED_ROWS_MIN_VERSION = 170000


def _display_name(schema_name: str, table_name: str, *, qualify: bool) -> str:
    """Discovery key for a table: dotted `schema.table` in multi-schema mode, bare table otherwise."""
    return f"{schema_name}.{table_name}" if qualify else table_name


def _split_display_name(display: str, selected_schema: Optional[str]) -> tuple[Optional[str], str]:
    """Inverse of `_display_name` — `(schema, unqualified_table)` for a discovery key.

    With a pinned `selected_schema` the key is the bare table. Otherwise it is the dotted
    `schema.table` that `get_columns` produced; a multi-schema key without a dot isn't expected
    (every multi-schema key is qualified at discovery), so the schema is reported as unknown
    (`None`) rather than guessed from the table name — never invent a schema we'd then query.
    """
    if selected_schema is not None:
        return selected_schema, display
    schema, dot, table = display.partition(".")
    if not dot:
        return None, display
    return schema, table


def _named_placeholders(prefix: str, values: list[str]) -> tuple[str, dict[str, str]]:
    """Render `%(prefix_i)s` placeholders + params for an `IN (...)` list."""
    placeholders: list[str] = []
    params: dict[str, str] = {}
    for index, value in enumerate(values):
        key = f"{prefix}_{index}"
        placeholders.append(f"%({key})s")
        params[key] = value
    return ", ".join(placeholders), params


def filter_redshift_incremental_fields(
    columns: list[tuple[str, str, bool]],
) -> list[tuple[str, IncrementalFieldType, bool]]:
    """Filter columns that can be used as incremental fields for Redshift."""
    results: list[tuple[str, IncrementalFieldType, bool]] = []
    for column_name, type, nullable in columns:
        type = type.lower()
        if type.startswith("timestamp"):
            results.append((column_name, IncrementalFieldType.Timestamp, nullable))
        elif type == "date":
            results.append((column_name, IncrementalFieldType.Date, nullable))
        elif type in ("integer", "smallint", "bigint", "int", "int2", "int4", "int8"):
            results.append((column_name, IncrementalFieldType.Integer, nullable))

    return results


def get_connection_metadata(config: RedshiftSourceConfig) -> dict[str, str | None]:
    """Connection metadata persisted on a direct-query source for the HogQL executor."""
    return {
        "engine": "redshift",
        "database": config.database,
        "schema": config.schema or None,
    }


class JsonAsStringLoader(Loader):
    def load(self, data):
        if data is None:
            return None
        return bytes(data).decode("utf-8")


class SafeDateLoader(Loader):
    """Load Redshift dates, handling edge cases beyond Python's date range.

    Redshift's `date` range (4713 BC to 294276 AD) is far wider than Python's `datetime.date`
    (year 1 to year 9999). psycopg's default loader raises `DataError` on anything outside that
    range — including a bare `0000-01-01` — which aborts the whole table sync. We clamp
    out-of-range values to `date.min`/`date.max` instead, mirroring the equivalent Postgres fix.

    A value we genuinely cannot parse raises rather than being clamped: silently mapping it onto
    date.max fabricates a real-looking 9999-12-31 and corrupts the whole column, which is far
    worse than a loud sync failure.
    """

    def load(self, data) -> date | None:
        if data is None:
            return None

        s = bytes(data).decode("utf-8").strip()

        if s in ("infinity", "-infinity"):
            return date.max if s == "infinity" else date.min

        # Handle negative years (BC dates)
        if s.startswith("-") or "bc" in s.lower():
            return date.min

        try:
            year, month, day = (int(part) for part in s.split("-"))
        except ValueError as e:
            raise ValueError(f"Unparseable Redshift date value: {s!r}") from e

        if year > 9999:
            return date.max
        if year < 1:
            return date.min

        return date(year, month, day)


def _redshift_select_clause(
    enabled_columns: Optional[list[str]],
    primary_keys: Optional[list[str]],
    incremental_field: Optional[str],
) -> sql.Composable:
    """Build the SELECT-list fragment as a `psycopg.sql.Composable`."""
    projected = compute_projected_columns(enabled_columns, primary_keys, incremental_field)
    if projected is None:
        return sql.SQL("*")
    return sql.SQL(", ").join(sql.Identifier(column) for column in projected)


def _build_query(
    schema: str,
    table_name: str,
    should_use_incremental_field: bool,
    table_type: Literal["table", "view", "materialized_view"] | None,
    incremental_field: Optional[str],
    incremental_field_type: Optional[IncrementalFieldType],
    db_incremental_field_last_value: Optional[Any],
    add_sampling: Optional[bool] = False,
    enabled_columns: Optional[list[str]] = None,
    primary_keys: Optional[list[str]] = None,
    row_filters: Optional[list[ValidatedRowFilter]] = None,
) -> sql.Composed:
    select_clause = _redshift_select_clause(enabled_columns, primary_keys, incremental_field)
    # Row filters apply only to the real data path; sampling/row-count queries stay unfiltered
    # (an over-estimate is harmless).
    row_filter_conditions = render_psycopg_row_filter_conditions(row_filters or [])

    if not should_use_incremental_field:
        if add_sampling:
            # Redshift doesn't support TABLESAMPLE SYSTEM, use random() instead
            query = sql.SQL("SELECT {cols} FROM {table} WHERE random() < 0.01").format(
                cols=select_clause, table=sql.Identifier(schema, table_name)
            )
            query_with_limit = cast(LiteralString, f"{query.as_string()} LIMIT 1000")
            return sql.SQL(query_with_limit).format()

        query = sql.SQL("SELECT {cols} FROM {table}").format(
            cols=select_clause, table=sql.Identifier(schema, table_name)
        )
        if row_filter_conditions:
            query = query + sql.SQL(" WHERE ") + and_join(row_filter_conditions)
        return query

    if incremental_field is None or incremental_field_type is None:
        raise ValueError("incremental_field and incremental_field_type can't be None")

    if db_incremental_field_last_value is None:
        db_incremental_field_last_value = incremental_type_to_initial_value(incremental_field_type)

    operator = sql.SQL(incremental_type_to_operator(incremental_field_type))

    if add_sampling:
        # Redshift doesn't support TABLESAMPLE SYSTEM
        query = sql.SQL(
            "SELECT {cols} FROM {schema}.{table} WHERE {incremental_field} {op} {last_value} AND random() < 0.01"
        ).format(
            cols=select_clause,
            schema=sql.Identifier(schema),
            table=sql.Identifier(table_name),
            incremental_field=sql.Identifier(incremental_field),
            op=operator,
            last_value=sql.Literal(db_incremental_field_last_value),
        )
        query_with_limit = cast(LiteralString, f"{query.as_string()} LIMIT 1000")
        return sql.SQL(query_with_limit).format()

    query = sql.SQL("SELECT {cols} FROM {schema}.{table} WHERE {incremental_field} {op} {last_value}").format(
        cols=select_clause,
        schema=sql.Identifier(schema),
        table=sql.Identifier(table_name),
        incremental_field=sql.Identifier(incremental_field),
        op=operator,
        last_value=sql.Literal(db_incremental_field_last_value),
    )
    if row_filter_conditions:
        query = query + sql.SQL(" AND ") + and_join(row_filter_conditions)
    query_str = cast(LiteralString, f"{query.as_string()} ORDER BY {{incremental_field}} ASC")
    return sql.SQL(query_str).format(incremental_field=sql.Identifier(incremental_field))


def _explain_query(cursor: psycopg.Cursor, query: sql.Composed, logger: FilteringBoundLogger):
    logger.debug(f"Running EXPLAIN on {query.as_string()}")

    try:
        # Debug-only, best-effort: Redshift can't EXPLAIN queries against leader-node-only system
        # views such as `svv_table_info` (they fail with `UndefinedColumn: column "t" does not
        # exist in t`), so swallow failures rather than reporting an expected, non-actionable error.
        query_with_explain = sql.SQL("EXPLAIN {}").format(query)
        cursor.execute(query_with_explain)
        rows = cursor.fetchall()
        explain_result: str = ""
        for row in rows:
            for col in row:
                explain_result += f"\n{col}"
        logger.debug(f"EXPLAIN result: {explain_result}")
    except Exception as e:
        logger.debug(f"EXPLAIN raised an exception: {e}")
        # A failed EXPLAIN aborts the surrounding transaction, and Redshift has no savepoints to
        # scope it. Roll back the aborted transaction so the caller's real query — which runs on
        # the same connection right after this probe — isn't killed by `InFailedSqlTransaction`.
        # Every caller runs read-only discovery queries, so there is no pending work to lose.
        try:
            if cursor.connection.info.transaction_status == TransactionStatus.INERROR:
                cursor.connection.rollback()
        except Exception:
            pass


def _is_fetch_size_error(error: Exception) -> bool:
    """Is this Redshift rejecting the FETCH size rather than the cursor itself?

    Matched on the message because Redshift reports it as a generic `InternalError_`/
    `FeatureNotSupported` with no distinguishing SQLSTATE. Both halves are required so an
    unrelated "exceeds the limit" (e.g. the cumulative result-set cap, which shrinking the fetch
    cannot fix) doesn't trigger a pointless retry.
    """
    message = str(error).lower()
    return "fetch size" in message and "exceeds the limit" in message


def _is_cursor_size_error(error: Exception) -> bool:
    """Is this Redshift refusing to materialize a cursor result set this large?

    A cursor's result set is materialized whole on the leader node, and the cap is on that total,
    not on the page a `FETCH` asks for. So no fetch size gets under it: the cap makes the server
    cursor permanently unusable for the table on this cluster, whatever we do to the fetch.
    """
    message = str(error).lower()
    return "cursor data" in message or ("cursor result set" in message and "exceeds the limit" in message)


def _rollback_if_aborted(connection: psycopg.Connection) -> None:
    """Clear an aborted transaction so the next attempt isn't killed by `InFailedSqlTransaction`.

    Redshift has no savepoints to scope a failure, so the whole transaction goes. This also frees
    the cursor name for a re-DECLARE, since an aborted transaction turns `CLOSE` into a no-op.
    """
    if connection.info.transaction_status == TransactionStatus.INERROR:
        connection.rollback()


def _recover_after_failed_probe(connection: psycopg.Connection) -> None:
    """Roll back a best-effort probe's aborted transaction, swallowing a lost connection."""
    try:
        _rollback_if_aborted(connection)
    except Exception:
        pass


_T = TypeVar("_T")

_MAX_SETUP_CONNECTION_DROP_ATTEMPTS = 3


def _is_transient_connection_drop_error(error: BaseException) -> bool:
    """True if a freshly opened connection died before `build_pipeline`'s setup phase finished.

    psycopg raises this exact OperationalError message when libpq finds the socket already gone
    (a network blip or a cluster pause/resize) — the keepalives configured on connect only detect
    a dead peer during a query, not this class of drop between connecting and the first query.
    """
    return isinstance(error, psycopg.OperationalError) and "the connection is lost" in str(error)


def _retry_on_transient_connection_drop(
    operation: Callable[[], _T],
    logger: FilteringBoundLogger,
    *,
    max_attempts: int = _MAX_SETUP_CONNECTION_DROP_ATTEMPTS,
) -> _T:
    """Run `operation`, retrying the whole thing (including reopening the connection) on a
    transient connection drop rather than failing sync setup on the first blip and burning a
    full Temporal activity retry — which re-runs from the very start of the sync — to recover
    from something a cheap in-process reconnect fixes in seconds.
    """
    attempt = 0
    while True:
        try:
            return operation()
        except psycopg.OperationalError as e:
            attempt += 1
            if attempt >= max_attempts or not _is_transient_connection_drop_error(e):
                raise
            logger.warning(
                "Transient Redshift connection drop during pipeline setup; retrying",
                attempt=attempt,
                max_attempts=max_attempts,
                exc_info=e,
            )
            time.sleep(min(2 * attempt, 30))


def _reads_primary_keys(cursor: psycopg.Cursor, schema: str) -> bool | None:
    """Can this connection read primary-key constraints in `schema` at all?

    `information_schema.table_constraints` exposes only the objects the role holds privileges on,
    so an empty result for one table means either "no key is declared" or "no privilege to see the
    one that is", and the two need opposite advice. Finding a key on any table in the schema
    settles it: the role can read the view, so an empty per-table result is a real absence.

    `None` when the probe itself fails, which settles nothing either way.
    """
    query = sql.SQL("""
        SELECT 1
        FROM information_schema.table_constraints
        WHERE table_schema = {schema} AND constraint_type = 'PRIMARY KEY'
        LIMIT 1""").format(schema=sql.Literal(schema))
    try:
        return cursor.execute(query).fetchone() is not None
    except Exception:
        _recover_after_failed_probe(cursor.connection)
        return None


def _no_primary_key_warning(
    cursor: psycopg.Cursor,
    schema: str,
    table_name: str,
    table_type: Literal["table", "view", "materialized_view"] | None,
) -> str:
    """The warning for a table whose primary-key lookup came back empty.

    Each branch states only what the empty result actually establishes, so the operator is never
    sent after a key that cannot exist or that we merely failed to read.
    """
    if table_type in ("view", "materialized_view"):
        relation = "materialized view" if table_type == "materialized_view" else "view"
        return (
            f"No primary keys found for {table_name}. A {relation} cannot have a primary key. "
            "Select a primary key manually to enable incremental sync, or use full table replication instead."
        )

    if _reads_primary_keys(cursor, schema):
        return (
            f"No primary key is set on {table_name}. Select one manually to enable incremental sync, "
            "or use full table replication instead."
        )

    return (
        f"Could not determine a primary key for {table_name}. Either none is set, or PostHog's role "
        f"cannot read constraints in schema {schema}. Check the role has SELECT on the table. You can "
        "also select a primary key manually, or use full table replication instead."
    )


def _is_materialized_view(cursor: psycopg.Cursor, schema: str, table_name: str) -> bool:
    """Is this relation a materialized view?

    Redshift exposes no `pg_matviews`, so the `pg_views` lookup that classifies a regular view
    never matches a materialized one — `svv_mv_info` is the only catalog that lists them.
    Best-effort: a role that can't read the system view degrades to the `pg_views` answer rather
    than failing discovery.
    """
    query = sql.SQL("SELECT {table} IN (SELECT name FROM svv_mv_info WHERE schema_name = {schema}) as res").format(
        schema=sql.Literal(schema), table=sql.Literal(table_name)
    )
    try:
        row = cursor.execute(query).fetchone()
    except Exception:
        _recover_after_failed_probe(cursor.connection)
        return False
    return row is not None and row[0] is True


def _libpq_rows_per_chunk() -> int:
    """Rows per libpq chunk while streaming, or 1 where chunked delivery isn't available.

    Chunked row mode arrived in libpq 17. On an older build `stream()` still streams correctly,
    one row at a time — only the per-row overhead differs, never the memory profile.
    """
    return REDSHIFT_STREAM_ROWS_PER_CHUNK if pq.version() >= _LIBPQ_CHUNKED_ROWS_MIN_VERSION else 1


def _stream_rows_as_arrow_batches(
    cursor: psycopg.Cursor,
    query: sql.Composed,
    chunk_size: int,
    arrow_schema: pa.Schema,
    *,
    primary_keys: list[str] | None = None,
    binary_reporter: BinaryColumnReporter | None = None,
) -> Iterator[pa.Table]:
    """Yield one Arrow table per `chunk_size` rows, reading rows straight off the wire.

    `stream()` puts libpq in single-row (or chunked-row) mode: no cursor is declared, so the
    per-node cap on cursor data never applies, and no result set is buffered into the worker
    either. Those were the two ways a large table could not be read.
    """
    column_names: list[str] = []
    pending: list[Any] = []

    def to_arrow(rows: list[Any]) -> pa.Table:
        return table_from_iterator(
            (dict(zip(column_names, row)) for row in rows),
            arrow_schema,
            primary_keys=primary_keys,
            binary_reporter=binary_reporter,
        )

    for row in cursor.stream(query, size=_libpq_rows_per_chunk()):
        if not column_names:
            # Only described once the first result arrives, so it can't be read before the loop.
            column_names = [column.name for column in cursor.description or []]
        pending.append(row)
        if len(pending) >= chunk_size:
            yield to_arrow(pending)
            pending = []

    if pending:
        yield to_arrow(pending)


def _fetch_arrow_batches(
    cursor: psycopg.Cursor,
    chunk_size: int,
    arrow_schema: pa.Schema,
    fetch_size: int | None = None,
    *,
    primary_keys: list[str] | None = None,
    binary_reporter: BinaryColumnReporter | None = None,
) -> Iterator[pa.Table]:
    """Yield one Arrow table per `chunk_size` rows drawn from an already-executed `cursor`.

    `fetch_size` decouples the per-`FETCH` page from the Arrow batch: rows accumulate across
    pages until `chunk_size` is reached. Redshift caps a single `FETCH` on a single-node cluster
    (see `REDSHIFT_SINGLE_NODE_FETCH_LIMIT`) far below the chunk sizes we target, so paging is
    the only way to keep the server cursor and still write batches the Delta writer sizes well.
    Defaults to `chunk_size`, i.e. one `FETCH` per Arrow table.
    """
    column_names = [column.name for column in cursor.description or []]
    page_size = fetch_size or chunk_size

    def to_arrow(rows: list[Any]) -> pa.Table:
        return table_from_iterator(
            (dict(zip(column_names, row)) for row in rows),
            arrow_schema,
            primary_keys=primary_keys,
            binary_reporter=binary_reporter,
        )

    pending: list[Any] = []
    while True:
        rows = cursor.fetchmany(page_size)
        if not rows:
            break

        pending.extend(rows)
        # Overshoots by at most `page_size - 1` rows, which is bounded and far below the byte
        # budget `chunk_size` was derived from.
        if len(pending) >= chunk_size:
            yield to_arrow(pending)
            pending = []

    if pending:
        yield to_arrow(pending)


def _stream_arrow_batches(
    connection: psycopg.Connection,
    query: sql.Composed,
    chunk_size: int,
    arrow_schema: pa.Schema,
    cursor_name: str,
    logger: FilteringBoundLogger,
    *,
    primary_keys: list[str] | None = None,
) -> Iterator[pa.Table]:
    """Stream `query` as Arrow tables, holding only `chunk_size` rows in the worker at a time.

    Two ways to read, tried in order. Streaming (`stream()`) is preferred: libpq delivers rows as
    the server produces them, so nothing is declared on the cluster and nothing is buffered in the
    worker. The server-side cursor (`DECLARE`/`FETCH`) is the fallback, mirroring the sibling
    Postgres driver.

    Redshift constrains cursors in ways Postgres doesn't, which is why streaming leads. A cursor's
    result set is materialized whole on the leader node under a per-node-type cap, so a table above
    that cap can never be read through a cursor at any fetch size. Single-node clusters separately
    reject a `FETCH FORWARD` above 1000 rows; that one is a property of the cluster rather than the
    table, so the retry at `REDSHIFT_SINGLE_NODE_FETCH_LIMIT` recovers it.

    Neither path buffers the whole result set, so there is no third attempt: an unnamed cursor would
    pull the entire table into the worker and OOM the pod, taking every co-tenant extraction on it
    down too. A table that neither path can read fails the sync instead.

    Once a batch has been yielded every recovery is off the table: re-running the query would
    re-emit rows the pipeline has already consumed, so later errors propagate.
    """
    yielded = False
    binary_reporter = BinaryColumnReporter(logger)

    try:
        with connection.cursor() as stream_cursor:
            for batch in _stream_rows_as_arrow_batches(
                stream_cursor,
                query,
                chunk_size,
                arrow_schema,
                primary_keys=primary_keys,
                binary_reporter=binary_reporter,
            ):
                yielded = True
                yield batch
        return
    except Exception as e:
        if yielded:
            raise
        _rollback_if_aborted(connection)
        logger.warning(f"Row streaming unusable ({e}); falling back to a server-side cursor", exc_info=e)

    fetch_sizes = [chunk_size]
    if chunk_size > REDSHIFT_SINGLE_NODE_FETCH_LIMIT:
        fetch_sizes.append(REDSHIFT_SINGLE_NODE_FETCH_LIMIT)

    for attempt, fetch_size in enumerate(fetch_sizes):
        try:
            # `close()` is a no-op while the transaction is aborted (psycopg checks the status
            # first), so this never masks the original failure with a CLOSE error.
            with connection.cursor(name=cursor_name) as server_cursor:
                server_cursor.execute(query)
                for batch in _fetch_arrow_batches(
                    server_cursor,
                    chunk_size,
                    arrow_schema,
                    fetch_size,
                    primary_keys=primary_keys,
                    binary_reporter=binary_reporter,
                ):
                    yielded = True
                    yield batch
            return
        except Exception as e:
            if yielded:
                raise
            _rollback_if_aborted(connection)

            is_last_attempt = attempt == len(fetch_sizes) - 1
            if not is_last_attempt and _is_fetch_size_error(e):
                logger.warning(
                    f"Server cursor rejected a {fetch_size}-row FETCH ({e}); "
                    f"retrying at {REDSHIFT_SINGLE_NODE_FETCH_LIMIT} rows per fetch"
                )
                continue

            if _is_cursor_size_error(e):
                # Classified, permanent for this table on this cluster: no fetch size gets under the
                # cap, and streaming already failed. Retrying just repeats a materialization that
                # takes over a minute to fail.
                raise NonRetryableException(
                    "This table is too large to read from this Redshift cluster. The cluster caps how "
                    "much data a cursor can hold, and row streaming is unavailable, so PostHog cannot "
                    "page through the result set. Sync fewer columns, add a row filter, or move to a "
                    "multi-node cluster."
                ) from e

            logger.warning(f"Server-side cursor unusable ({e})", exc_info=e)
            raise


class RedshiftColumn(Column):
    """Implementation of the `Column` protocol for a Redshift source."""

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

        match self.data_type.lower():
            case "bigint" | "int8":
                arrow_type = pa.int64()
            case "integer" | "int" | "int4":
                arrow_type = pa.int32()
            case "smallint" | "int2":
                arrow_type = pa.int16()
            case "numeric" | "decimal":
                if not self.numeric_precision or not self.numeric_scale:
                    raise TypeError("expected `numeric_precision` and `numeric_scale` to be `int`, got `NoneType`")
                arrow_type = build_pyarrow_decimal_type(self.numeric_precision, self.numeric_scale)
            case "real" | "float4":
                arrow_type = pa.float32()
            case "double precision" | "float8" | "float":
                arrow_type = pa.float64()
            case "text" | "varchar" | "character varying" | "char" | "character" | "bpchar" | "nchar" | "nvarchar":
                arrow_type = pa.string()
            case "date":
                arrow_type = pa.date32()
            case "time" | "time without time zone":
                arrow_type = pa.time64("us")
            case "timestamp" | "timestamp without time zone":
                arrow_type = pa.timestamp("us")
            case "timestamptz" | "timestamp with time zone":
                arrow_type = pa.timestamp("us", tz="UTC")
            case "boolean" | "bool":
                arrow_type = pa.bool_()
            case "super":
                # Redshift SUPER type for semi-structured data
                arrow_type = pa.string()
            case "geometry" | "geography":
                arrow_type = pa.string()
            case "hllsketch":
                arrow_type = pa.string()
            case _:
                arrow_type = pa.string()

        return pa.field(self.name, arrow_type, nullable=self.nullable)


@frozen
class DisplayNameIndex:
    display_by_pair: dict[tuple[str, str], str]
    schemas: list[str]
    bare_tables: list[str]


@frozen
class QualifiedRelation:
    """A relation addressed by namespace and name. Both are strings, so keeping them named
    stops a `COUNT(*)` being aimed at `name.schema`."""

    schema: str
    name: str


@frozen
class RedshiftTableSetup:
    """Everything `build_pipeline` learns about a table before it can stream rows."""

    full_table: Table[RedshiftColumn]
    primary_keys: list[str] | None
    projected_table: Table[RedshiftColumn]
    chunk_size: int
    rows_to_sync: int
    partition_settings: PartitionSettings | None
    duplicate_primary_keys: bool


class RedshiftImplementation(SQLSourceImplementation[RedshiftSourceConfig, psycopg.Connection, Any]):
    # `psycopg.Cursor` does not satisfy `_CursorLike` (its `execute`
    # signature uses `params` instead of `args`, and accepts `Query`
    # rather than `str`), so the cursor type is widened to `Any` here.
    """Redshift driver implementation paired with `RedshiftSource`.

    Owns the full Redshift lifecycle — SSH tunnel + psycopg connection,
    `information_schema` and `svv_table_info` batch listing queries used
    during schema discovery, per-cursor metadata used during the
    streaming sync, and the dlt pipeline factory (`build_pipeline`).
    """

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    @contextmanager
    def connect(self, config: RedshiftSourceConfig) -> Iterator[psycopg.Connection]:
        """Open a psycopg connection for the duration of the context.

        Opens the SSH tunnel (if configured) and connects with the
        Redshift-wide SSL conventions in one place — every listing
        method takes the resulting connection, so discovery against an
        SSH-tunneled cluster only opens the tunnel once.
        """
        with open_ssh_tunnel(config) as (host, port):
            with psycopg.connect(
                host=host,
                port=port,
                dbname=config.database,
                user=config.user,
                password=config.password,
                **_REDSHIFT_CONNECT_OPTS,
            ) as conn:
                conn.adapters.register_loader("date", SafeDateLoader)
                yield conn

    # ------------------------------------------------------------------
    # Listing — batch queries run once during `get_schemas`
    # ------------------------------------------------------------------

    def get_columns(
        self,
        conn: psycopg.Connection,
        config: RedshiftSourceConfig,
        names: list[str] | None,
    ) -> dict[str, list[tuple[str, str, bool]]]:
        """List columns, keyed by the discovery display name.

        Pinned `schema` keeps the single-namespace fast path (bare table keys). A blank `schema`
        enumerates every non-system namespace and returns qualified `schema.table` keys so
        cross-schema duplicate table names stay distinct.
        """
        selected_schema = normalize_namespace(config.schema)
        qualify = selected_schema is None

        with conn.cursor() as cursor:
            params: dict = {"internal_column": REDSHIFT_INTERNAL_COLUMN_LIKE}
            where: list[str] = ["column_name NOT LIKE %(internal_column)s"]
            if selected_schema is not None:
                params["schema"] = selected_schema
                where.append("table_schema = %(schema)s")
            else:
                placeholders, system_params = _named_placeholders("system_schema", SYSTEM_REDSHIFT_SCHEMAS)
                params.update(system_params)
                where.append(f"table_schema NOT IN ({placeholders})")
                where.append("table_schema NOT LIKE 'pg_temp_%%'")
            if names:
                name_clause, name_params = self._column_name_predicate(names, selected_schema)
                params.update(name_params)
                where.append(name_clause)

            cursor.execute(
                f"""
                SELECT table_schema, table_name, column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE {" AND ".join(where)}
                ORDER BY table_schema ASC, table_name ASC
                """,
                params,
            )
            result = cursor.fetchall()

        schema_list: dict[str, list[tuple[str, str, bool]]] = collections.defaultdict(list)
        for table_schema, table_name, column_name, data_type, is_nullable in result:
            display = _display_name(table_schema, table_name, qualify=qualify)
            schema_list[display].append((column_name, data_type, is_nullable == "YES"))
        return dict(schema_list)

    @staticmethod
    def _column_name_predicate(names: list[str], selected_schema: Optional[str]) -> tuple[str, dict[str, str]]:
        """Build a WHERE fragment restricting `information_schema.columns` to the requested tables.

        Pinned schema → match by bare `table_name`. Blank schema → match each qualified
        `schema.table` on both parts (bare names fall back to any-schema for legacy self-heal).
        """
        clauses: list[str] = []
        params: dict[str, str] = {}
        for index, name in enumerate(names):
            if selected_schema is not None:
                params[f"name_{index}"] = name
                clauses.append(f"table_name = %(name_{index})s")
                continue
            schema, _, table = name.partition(".")
            if table:
                params[f"sch_{index}"] = schema
                params[f"tbl_{index}"] = table
                clauses.append(f"(table_schema = %(sch_{index})s AND table_name = %(tbl_{index})s)")
            else:
                params[f"name_{index}"] = name
                clauses.append(f"table_name = %(name_{index})s")
        return "(" + " OR ".join(clauses) + ")", params

    def get_primary_keys(
        self,
        conn: psycopg.Connection,
        config: RedshiftSourceConfig,
        tables: list[str],
    ) -> dict[str, list[str] | None]:
        """Detect primary keys for all tables in a single query, each in declared column order.

        Permission-sensitive — some Redshift deployments restrict access
        to `information_schema.table_constraints`. Swallow and log any
        failure so schema discovery keeps working without PKs.

        A swallowed failure returns every table as `None`, which the base
        contract cannot distinguish from "declares no key". The sync path
        re-runs the lookup per table and says which it is
        (`_no_primary_key_warning`); surfacing the difference at discovery
        needs a channel on `SourceSchema` that does not exist yet.
        """
        result: dict[str, list[str] | None] = dict.fromkeys(tables)
        if not tables:
            return result

        selected_schema = normalize_namespace(config.schema)
        index = self._index_display_names(tables, selected_schema)

        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    sql.SQL("""
                        SELECT tc.table_schema, tc.table_name, kcu.column_name
                        FROM information_schema.table_constraints tc
                        JOIN information_schema.key_column_usage kcu
                        ON tc.constraint_name = kcu.constraint_name
                        AND tc.table_schema = kcu.table_schema
                        AND tc.table_name = kcu.table_name
                        WHERE tc.table_schema = ANY({schemas})
                        AND tc.table_name = ANY({names})
                        AND tc.constraint_type = 'PRIMARY KEY'
                        ORDER BY tc.table_schema, tc.table_name, kcu.ordinal_position
                    """).format(schemas=sql.Literal(index.schemas), names=sql.Literal(index.bare_tables))
                )
                rows = cursor.fetchall()
        except Exception as e:
            structlog.get_logger().warning(
                "Primary keys for Redshift schemas are undetermined, not absent: the detection query failed",
                exc_info=e,
            )
            return result

        pks: dict[str, list[str]] = collections.defaultdict(list)
        for table_schema, table_name, column_name in rows:
            display = index.display_by_pair.get((table_schema, table_name))
            if display is not None:
                pks[display].append(column_name)
        for display, pk_cols in pks.items():
            result[display] = pk_cols
        return result

    @staticmethod
    def _index_display_names(tables: list[str], selected_schema: Optional[str]) -> DisplayNameIndex:
        """Map `(schema, table)` → display key, plus the distinct schemas and bare table names.

        Lets a single batch query (`schema = ANY(...) AND table = ANY(...)`) cover both the
        single-namespace and multi-namespace cases; results re-key to the display name by pair.
        A display whose schema is unknown (bare key in multi-schema mode) is dropped from the
        queryable schema list — it can't be matched to a result row, so it degrades to no metadata
        rather than querying a schema that doesn't exist.
        """
        display_by_pair: dict[tuple[str, str], str] = {}
        schemas: set[str] = set()
        bare_tables: set[str] = set()
        for display in tables:
            schema, table = _split_display_name(display, selected_schema)
            bare_tables.add(table)
            if schema is None:
                continue
            display_by_pair[(schema, table)] = display
            schemas.add(schema)
        return DisplayNameIndex(
            display_by_pair=display_by_pair, schemas=sorted(schemas), bare_tables=sorted(bare_tables)
        )

    def get_row_counts(
        self,
        conn: psycopg.Connection,
        config: RedshiftSourceConfig,
        tables: list[str],
    ) -> dict[str, int | None]:
        """Return per-table row counts using `svv_table_info` for tables and `COUNT(*)` for views.

        `svv_table_info.tbl_rows` is a Redshift system table that gives
        cheap row count estimates for materialized tables; views aren't
        in it, so they fall through to a (slower) `UNION ALL` of
        `COUNT(*)` queries. A materialized view is in neither under its
        own name — its storage is registered under an internal one — so
        `svv_mv_info` routes it onto the `COUNT(*)` path too. Errors are
        swallowed — schema discovery keeps working without row counts.
        """
        if not tables:
            return {}

        selected_schema = normalize_namespace(config.schema)
        index = self._index_display_names(tables, selected_schema)

        result: dict[str, int | None] = {}
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    sql.SQL("SET statement_timeout = {timeout}").format(timeout=sql.Literal(1000 * 30))  # 30 secs
                )

                params: dict = {"schemas": index.schemas, "names": index.bare_tables}
                cursor.execute(
                    """
                    SELECT schema, "table" AS table_name, tbl_rows AS row_count
                    FROM svv_table_info
                    WHERE schema = ANY(%(schemas)s) AND "table" = ANY(%(names)s)
                    """,
                    params,
                )
                for schema_name, table_name, row_count in cursor.fetchall():
                    display = index.display_by_pair.get((schema_name, table_name))
                    if display is not None:
                        result[display] = int(row_count)

                cursor.execute(
                    "SELECT schemaname, viewname FROM pg_views WHERE schemaname = ANY(%(schemas)s) AND viewname = ANY(%(names)s)",
                    params,
                )
                to_count = [
                    QualifiedRelation(schema=schema_name, name=view_name)
                    for schema_name, view_name in cursor.fetchall()
                    if (schema_name, view_name) in index.display_by_pair
                ]
                to_count.extend(self._materialized_views(conn, cursor, index, params))

                if to_count:
                    view_counts = [
                        sql.SQL(
                            "SELECT {schema_lit} AS schema_name, {view_lit} AS table_name, COUNT(*) AS row_count FROM {schema}.{view}"
                        ).format(
                            schema_lit=sql.Literal(relation.schema),
                            view_lit=sql.Literal(relation.name),
                            schema=sql.Identifier(relation.schema),
                            view=sql.Identifier(relation.name),
                        )
                        for relation in to_count
                    ]
                    cursor.execute(sql.SQL(" UNION ALL ").join(view_counts))
                    for schema_name, table_name, row_count in cursor.fetchall():
                        display = index.display_by_pair.get((schema_name, table_name))
                        if display is not None:
                            result[display] = int(row_count)
        except Exception:
            return {}

        return result

    @staticmethod
    def _materialized_views(
        conn: psycopg.Connection,
        cursor: Any,
        index: DisplayNameIndex,
        params: dict,
    ) -> list[QualifiedRelation]:
        """Each requested relation that is a materialized view.

        Isolated from the caller's `except` so a role without access to `svv_mv_info` loses only
        the materialized-view counts, not every count in the batch. The rollback matters for the
        same reason: a failed probe aborts the transaction, and the `COUNT(*)` batch that follows
        runs on the same connection.
        """
        try:
            cursor.execute(
                "SELECT schema_name, name FROM svv_mv_info WHERE schema_name = ANY(%(schemas)s) AND name = ANY(%(names)s)",
                params,
            )
            rows = cursor.fetchall()
        except Exception:
            _recover_after_failed_probe(conn)
            return []

        return [
            QualifiedRelation(schema=schema_name, name=view_name)
            for schema_name, view_name in rows
            if (schema_name, view_name) in index.display_by_pair
        ]

    def get_leading_index_columns(
        self,
        conn: psycopg.Connection,
        config: RedshiftSourceConfig,
        tables: list[str],
    ) -> dict[str, set[str]] | None:
        """Return the columns that drive `WHERE col >= …` predicate pushdown per table.

        Redshift is columnar with no traditional B-tree indexes; SORTKEYs are the
        structure that accelerates predicate pushdown. The `sortkey` value reported
        by `pg_table_def` encodes both the kind of sortkey and the column's
        position:

        - **Compound sortkeys** use positive integers (1, 2, 3, …) where ``sortkey = 1``
          is the leading column. Only the leading column meaningfully accelerates
          `WHERE col >= …`; subsequent columns require equality predicates on
          preceding columns to be useful.
        - **Interleaved sortkeys** mix signs (e.g. ``-1, 2, -3, 4``). All non-zero
          sortkey columns contribute equally to predicate pushdown by design — the
          whole point of interleaved sortkeys is to give every column equal
          weight. Treating only ``sortkey = -1`` as indexed produces false warnings
          on the other interleaved columns.

        Returns None when discovery fails so the caller defaults to no-warning.
        Tables with no sortkey return an empty set so the warning fires.
        """
        if not tables:
            return {}

        selected_schema = normalize_namespace(config.schema)
        index = self._index_display_names(tables, selected_schema)
        result: dict[str, set[str]] = {table: set() for table in tables}

        try:
            with conn.cursor() as cursor:
                # pg_table_def only returns rows for schemas in search_path; without
                # this SET, schema=anything-other-than-public-or-the-username silently
                # returns zero rows and the helper marks every sortkey column as
                # unindexed. Multi-schema discovery puts every discovered schema on the
                # path. Documented behavior: docs.aws.amazon.com/redshift/latest/dg/r_PG_TABLE_DEF.html
                cursor.execute(
                    sql.SQL("SET search_path TO {schemas}").format(
                        schemas=sql.SQL(", ").join(sql.Identifier(schema) for schema in index.schemas)
                    )
                )
                cursor.execute(
                    sql.SQL("""
                        SELECT schemaname, tablename, "column", sortkey
                        FROM pg_table_def
                        WHERE schemaname = ANY({schemas})
                          AND tablename = ANY({names})
                          AND sortkey != 0
                    """).format(schemas=sql.Literal(index.schemas), names=sql.Literal(index.bare_tables))
                )
                # Group rows by display name so we can classify compound vs interleaved
                # before deciding which columns count as indexed. Negative sortkey
                # values are the marker Redshift uses for interleaved sortkeys.
                rows_by_display: dict[str, list[tuple[str, int]]] = {}
                for schema_name, table_name, column_name, sortkey_value in cursor.fetchall():
                    display = index.display_by_pair.get((schema_name, table_name))
                    if display is None:
                        continue
                    rows_by_display.setdefault(display, []).append((column_name, sortkey_value))

                for display, sortkey_rows in rows_by_display.items():
                    is_interleaved = any(sk < 0 for _, sk in sortkey_rows)
                    if is_interleaved:
                        result[display] = {col for col, _ in sortkey_rows}
                    else:
                        result[display] = {col for col, sk in sortkey_rows if sk == 1}
        except Exception as e:
            structlog.get_logger().warning("Failed to detect sortkeys for Redshift schemas", exc_info=e)
            return None

        return result

    def get_source_metadata(
        self,
        conn: psycopg.Connection,
        config: RedshiftSourceConfig,
        tables: list[str],
    ) -> SourceMetadata:
        """Stamp per-row namespace onto each schema so sync can route without re-querying.

        Redshift namespaces are connection-scoped (one database), so there is no catalog.
        Persisted into `schema_metadata` by `reconcile_schema_metadata` and read back by
        `resolve_source_location` during `build_pipeline`.
        """
        selected_schema = normalize_namespace(config.schema)
        metadata = SourceMetadata()
        for display in tables:
            schema, table = _split_display_name(display, selected_schema)
            metadata.catalog_by_table[display] = None
            metadata.schema_by_table[display] = schema
            metadata.table_name_by_table[display] = table
        return metadata

    def get_incremental_filter(self) -> IncrementalFieldFilter:
        return filter_redshift_incremental_fields

    # ------------------------------------------------------------------
    # Per-cursor metadata — used during `build_pipeline`
    # ------------------------------------------------------------------

    def get_primary_keys_for_table(
        self,
        cursor: psycopg.Cursor,
        schema: str,
        table_name: str,
        logger: FilteringBoundLogger | None = None,
        table_type: Literal["table", "view", "materialized_view"] | None = None,
    ) -> list[str] | None:
        """Return the primary-key column names for a single table in declared order, or None.

        `table_type` only shapes the warning on an empty result, which is ambiguous on its own:
        see `_no_primary_key_warning` for what each case establishes.
        """
        query = sql.SQL("""
            SELECT
                kcu.column_name
            FROM
                information_schema.table_constraints tc
            JOIN
                information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
            WHERE
                tc.table_schema = {schema}
                AND tc.table_name = {table}
                AND tc.constraint_type = 'PRIMARY KEY'
            ORDER BY
                kcu.ordinal_position""").format(schema=sql.Literal(schema), table=sql.Literal(table_name))

        if logger is not None:
            _explain_query(cursor, query, logger)
            logger.debug(f"Running query: {query.as_string()}")
        cursor.execute(query)
        rows = cursor.fetchall()
        if len(rows) > 0:
            return [row[0] for row in rows]

        if logger is not None:
            logger.warning(_no_primary_key_warning(cursor, schema, table_name, table_type))
        return None

    def has_duplicate_primary_keys(
        self,
        cursor: psycopg.Cursor,
        schema: str,
        table_name: str,
        primary_keys: list[str] | None,
        logger: FilteringBoundLogger,
    ) -> bool:
        if not primary_keys or len(primary_keys) == 0:
            return False

        try:
            sql_query = cast(
                LiteralString,
                f"""
                SELECT {", ".join(["{}" for _ in primary_keys])}
                FROM {{}}.{{}}
                GROUP BY {", ".join([str(i + 1) for i, _ in enumerate(primary_keys)])}
                HAVING COUNT(*) > 1
                LIMIT 1
            """,
            )
            query = sql.SQL(sql_query).format(
                *[sql.Identifier(key) for key in primary_keys],
                sql.Identifier(schema),
                sql.Identifier(table_name),
            )
            _explain_query(cursor, query, logger)
            logger.debug(f"Running query: {query.as_string()}")
            cursor.execute(query)
            row = cursor.fetchone()
            return row is not None
        except psycopg.errors.QueryCanceled:
            raise
        except psycopg.OperationalError:
            # A connection-level failure (e.g. the SSL connection dropping mid-query) means the
            # probe never ran — swallowing it as "no duplicate keys" would be a false negative.
            # Propagate it so the activity's retry path handles it; these are transient and stay
            # retryable. Mirrors the equivalent Postgres source.
            raise
        except Exception as e:
            # A Redshift system-requested query abort (error code 1020, "system requested abort")
            # is the cluster's WLM/QMR cancelling the query — the same transient, non-actionable
            # class as `QueryCanceled`, which psycopg surfaces here as `InternalError_` rather than
            # `QueryCanceled`. The duplicate-PK check is best-effort (the caller defaults to no
            # duplicates), so skip gracefully instead of reporting an expected, non-actionable error
            # to error tracking. Mirrors the graceful-skip probes elsewhere in this driver.
            if "system requested abort" in str(e):
                logger.debug(f"has_duplicate_primary_keys: query aborted by Redshift, skipping check: {e}")
                return False
            capture_exception(e)
            return False

    def get_table_metadata(
        self,
        cursor: psycopg.Cursor,
        schema: str,
        table_name: str,
        logger: FilteringBoundLogger | None = None,
    ) -> Table[RedshiftColumn]:
        """Return rich column metadata for building a PyArrow schema."""
        is_mat_view = _is_materialized_view(cursor, schema, table_name)
        is_view = False
        if not is_mat_view:
            is_view_query = sql.SQL(
                "SELECT {table} IN (SELECT viewname FROM pg_views WHERE schemaname = {schema}) as res"
            ).format(schema=sql.Literal(schema), table=sql.Literal(table_name))
            is_view_res = cursor.execute(is_view_query).fetchone()
            is_view = is_view_res is not None and is_view_res[0] is True

        query = sql.SQL("""
            SELECT
                column_name,
                data_type,
                is_nullable,
                numeric_precision,
                numeric_scale
            FROM
                information_schema.columns
            WHERE
                table_schema = {schema}
                AND table_name = {table}
                AND column_name NOT LIKE {internal_column}""").format(
            schema=sql.Literal(schema),
            table=sql.Literal(table_name),
            internal_column=sql.Literal(REDSHIFT_INTERNAL_COLUMN_LIKE),
        )

        if logger is not None:
            _explain_query(cursor, query, logger)
            logger.debug(f"Running query: {query.as_string()}")
        cursor.execute(query)

        numeric_data_types = {"numeric", "decimal"}
        columns = []
        for name, data_type, nullable, numeric_precision_candidate, numeric_scale_candidate in cursor:
            if data_type in numeric_data_types:
                numeric_precision = numeric_precision_candidate or DEFAULT_NUMERIC_PRECISION
                numeric_scale = numeric_scale_candidate or DEFAULT_NUMERIC_SCALE
            else:
                numeric_precision = None
                numeric_scale = None

            columns.append(
                RedshiftColumn(
                    name=name,
                    data_type=data_type,
                    nullable=nullable == "YES",
                    numeric_precision=numeric_precision,
                    numeric_scale=numeric_scale,
                )
            )

        table_type: Literal["table", "view", "materialized_view"] = "table"
        if is_mat_view:
            table_type = "materialized_view"
        elif is_view:
            table_type = "view"
        return Table(name=table_name, parents=(schema,), columns=columns, type=table_type)

    def get_rows_to_sync(
        self,
        cursor: psycopg.Cursor,
        inner_query: Any,
        inner_query_args: Any,
        logger: FilteringBoundLogger,
    ) -> int:
        """Count the rows the given `inner_query` will produce.

        Overrides the base helper to (1) let `psycopg.errors.QueryCanceled`
        bubble out so `build_pipeline` can promote it to
        `QueryTimeoutException`, and (2) promote Redshift's
        `temporary file size exceeds temp_file_limit` to
        `TemporaryFileSizeExceedsLimitException` — both are listed in
        `get_non_retryable_errors` and need to escape the base's catch-all
        `except Exception` that otherwise returns 0.
        """
        try:
            query = sql.SQL("SELECT COUNT(*) FROM ({}) as t").format(inner_query)
            cursor.execute(query)
            row = cursor.fetchone()
            if row is None:
                return 0
            return int(row[0] or 0)
        except psycopg.errors.QueryCanceled:
            raise
        except psycopg.errors.InsufficientPrivilege as e:
            # The connecting role can SELECT the table itself but Redshift also gates access to a
            # materialized view's base relation(s) separately (SQLSTATE 42501). Row-count
            # estimation is best-effort (the caller defaults to 0), so skip gracefully instead of
            # reporting the expected, non-actionable error to error tracking. Mirrors
            # `fetch_table_stats`.
            logger.debug(f"get_rows_to_sync: no privilege to run count query, using 0 as rows to sync: {e}")
            return 0
        except Exception as e:
            logger.debug(f"get_rows_to_sync: Error: {e}. Using 0 as rows to sync", exc_info=e)
            if "Remote request timeout" in str(e):
                # Redshift's leader node lost internal RPC contact with a compute node mid-query
                # (SQLSTATE-less `InternalError_`, code 29150) — a transient cluster-side hiccup,
                # the same non-actionable class as a WLM/QMR abort (see `has_duplicate_primary_keys`).
                # Row-count estimation is best-effort (already defaulting to 0 here), so skip
                # reporting the expected error to error tracking.
                return 0
            capture_exception(e)
            if "temporary file size exceeds temp_file_limit" in str(e):
                raise TemporaryFileSizeExceedsLimitException(
                    f"Error: {e}. Please ensure your incremental field is set as a SORTKEY on the table"
                )
            return 0

    def fetch_table_stats(
        self,
        cursor: psycopg.Cursor,
        schema: str,
        table_name: str,
        logger: FilteringBoundLogger,
    ) -> TableStats | None:
        """Return `size` (in MB) and `tbl_rows` from `svv_table_info`.

        `size` is reported in megabytes by Redshift's system table —
        converted to bytes here so the shared `get_partition_settings`
        math operates on a single unit. Returns None when either value
        is missing or zero so the base falls back to no partitioning.
        """
        query = sql.SQL("""
            SELECT size, tbl_rows
            FROM svv_table_info
            WHERE schema = {schema} AND "table" = {table}
        """).format(schema=sql.Literal(schema), table=sql.Literal(table_name))

        try:
            _explain_query(cursor, query, logger)
            logger.debug(f"Running query: {query.as_string()}")
            cursor.execute(query)
            result = cursor.fetchone()
        except psycopg.errors.QueryCanceled:
            raise
        except psycopg.errors.InsufficientPrivilege as e:
            # Some Redshift roles aren't granted access to the `svv_table_info` system view. That's
            # a customer permission-config issue, not an actionable bug — table stats are optional
            # (we fall back to no partitioning), so skip gracefully without reporting the expected,
            # non-actionable error to error tracking. Mirrors `_explain_query`/`get_row_counts`.
            logger.debug(f"fetch_table_stats: no access to svv_table_info, returning None: {e}")
            return None
        except Exception as e:
            capture_exception(e)
            logger.debug(f"fetch_table_stats: returning None due to error: {e}")
            return None

        if result is None:
            logger.debug("fetch_table_stats: no results returning None")
            return None

        size_mb, tbl_rows = result
        if size_mb is None or tbl_rows is None or size_mb == 0 or tbl_rows == 0:
            logger.debug("fetch_table_stats: missing or zero size/rows, returning None")
            return None

        return TableStats(table_size_bytes=int(size_mb) * 1024 * 1024, row_count=int(tbl_rows))

    def fetch_average_row_size(
        self,
        cursor: psycopg.Cursor,
        schema: str,
        table_name: str,
        inner_query: Any,
        inner_query_args: Any,
        logger: FilteringBoundLogger,
    ) -> int | None:
        """Derive the average row size from `svv_table_info`'s reported size and row count.

        Redshift has no portable whole-row size expression — `pg_column_size(t)` (like Postgres'
        `octet_length(t::text)`) needs a composite whole-row reference that Redshift rejects with
        `UndefinedColumn: column "t" does not exist in t`, so sampling the rows directly fails on
        every table and the caller silently fell back to `DEFAULT_CHUNK_SIZE` for all of them. The
        table's own catalog stats give the same figure without a sample scan.

        `size` is the *compressed* on-disk footprint, so this under-estimates the decompressed
        working set and the chunk it yields stays larger than the true row size warrants. The caller
        caps the result at `DEFAULT_CHUNK_SIZE` either way, so an under-estimate is safe: it can
        only shrink a table's chunk from what it was, never grow it.

        Best-effort, like every other stats probe on this driver: None falls back to the default.
        """
        stats = self.fetch_table_stats(cursor, schema, table_name, logger)
        if stats is None or stats.row_count <= 0:
            logger.debug("fetch_average_row_size: no usable table stats, returning None")
            return None

        return max(1, stats.table_size_bytes // stats.row_count)

    # ------------------------------------------------------------------
    # Pipeline build — the dlt `SourceResponse` for a single table
    # ------------------------------------------------------------------

    def build_pipeline(
        self,
        config: RedshiftSourceConfig,
        inputs: SourceInputs,
        *,
        chunk_size_override: int | None = None,
    ) -> SourceResponse:
        # `chunk_size_override` is sourced from
        # `ExternalDataSchema.sync_type_config` by the caller
        # (`RedshiftSource.source_for_pipeline`) — keeping the ORM
        # lookup at the source layer lets the driver stay free of
        # Django model imports.
        # Route this row to its own namespace: prefer the per-row `schema_metadata`, fall back to
        # the connection `schema`, then `public`. `response_name` keeps a migrated row on its
        # legacy Delta subdir (via `dwh_storage_key`) so qualifying the name never orphans data.
        location = resolve_source_location(inputs, config_namespace=config.schema, default="public")
        table_name = location.table_name
        if not table_name:
            raise ValueError("Table name is missing")

        schema = location.schema or "public"
        logger = inputs.logger
        should_use_incremental_field = inputs.should_use_incremental_field
        incremental_field = inputs.incremental_field
        incremental_field_type = inputs.incremental_field_type
        db_incremental_field_last_value = inputs.db_incremental_field_last_value
        enabled_columns = inputs.enabled_columns
        row_filters = inputs.row_filters

        def _discover_and_probe() -> RedshiftTableSetup:
            with self.connect(config) as connection:
                # Autocommit so each best-effort discovery probe runs in its own transaction. A probe
                # that fails — a permission error, an EXPLAIN the cluster rejects, a cancelled COUNT(*) —
                # otherwise leaves the shared transaction aborted (INERROR), and every probe after it
                # raises `InFailedSqlTransaction` until a rollback. Mirrors the postgres source.
                connection.autocommit = True
                with connection.cursor() as cursor:
                    logger.debug("Getting table types...")
                    full_table = self.get_table_metadata(cursor, schema, table_name, logger)

                    cursor.execute(
                        sql.SQL("SET statement_timeout = {timeout}").format(
                            timeout=sql.Literal(1000 * 60 * 10)
                        )  # 10 mins
                    )
                    try:
                        logger.debug("Getting primary keys...")
                        primary_keys = self.get_primary_keys_for_table(
                            cursor, schema, table_name, logger, full_table.type
                        )
                        if primary_keys:
                            logger.debug(f"Found primary keys: {primary_keys}")

                        # Resolve PKs before projection so SELECT and Arrow schema agree.
                        if primary_keys is None and "id" in full_table:
                            logger.debug("Falling back to ['id'] for primary keys...")
                            primary_keys = ["id"]

                        projected = compute_projected_columns(enabled_columns, primary_keys, incremental_field)
                        table = project_arrow_columns(full_table, projected)
                        logger.debug(f"Source schema: {table.to_arrow_schema()}")

                        inner_query_with_limit = _build_query(
                            schema,
                            table_name,
                            should_use_incremental_field,
                            table.type,
                            incremental_field,
                            incremental_field_type,
                            db_incremental_field_last_value,
                            add_sampling=True,
                            enabled_columns=enabled_columns,
                            primary_keys=primary_keys,
                        )

                        inner_query_without_limit = _build_query(
                            schema,
                            table_name,
                            should_use_incremental_field,
                            table.type,
                            incremental_field,
                            incremental_field_type,
                            db_incremental_field_last_value,
                            enabled_columns=enabled_columns,
                            primary_keys=primary_keys,
                            row_filters=row_filters,
                        )
                        logger.debug("Getting table chunk size...")
                        if chunk_size_override is not None:
                            chunk_size = chunk_size_override
                            logger.debug(f"Using chunk_size_override: {chunk_size_override}")
                        else:
                            # `inner_query_with_limit` is a `psycopg.sql.Composed`
                            # rather than a `str`; the override on
                            # `fetch_average_row_size` accepts it via `Any`.
                            chunk_size = self.get_chunk_size(
                                cursor,
                                schema,
                                table_name,
                                inner_query_with_limit,  # type: ignore[arg-type]
                                None,
                                logger,
                            )
                        logger.debug("Getting rows to sync...")
                        rows_to_sync = self.get_rows_to_sync(cursor, inner_query_without_limit, None, logger)
                        logger.debug("Getting partition settings...")
                        partition_settings = (
                            self.get_partition_settings(cursor, schema, table_name, logger)
                            if should_use_incremental_field
                            else None
                        )
                        duplicate_primary_keys = False
                        if primary_keys == ["id"] and "id" in full_table:
                            # Only check dupes when we fell back to the `id` PK above.
                            logger.debug("Checking duplicate primary keys...")
                            duplicate_primary_keys = self.has_duplicate_primary_keys(
                                cursor, schema, table_name, primary_keys, logger
                            )
                    except psycopg.errors.QueryCanceled:
                        if should_use_incremental_field:
                            raise QueryTimeoutException(
                                f"10 min timeout statement reached. Please ensure your incremental field ({incremental_field}) is set as a SORTKEY on the table"
                            )
                        raise
            return RedshiftTableSetup(
                full_table=full_table,
                primary_keys=primary_keys,
                projected_table=table,
                chunk_size=chunk_size,
                rows_to_sync=rows_to_sync,
                partition_settings=partition_settings,
                duplicate_primary_keys=duplicate_primary_keys,
            )

        # A fresh connection can still drop before setup finishes (network blip, cluster
        # pause/resize) — retry the whole discovery+probe phase (reopening the connection) rather
        # than let it fail through to a full Temporal activity retry, which restarts the sync
        # from scratch. See `_retry_on_transient_connection_drop`.
        setup = _retry_on_transient_connection_drop(_discover_and_probe, logger)
        primary_keys = setup.primary_keys
        table = setup.projected_table
        chunk_size = setup.chunk_size
        rows_to_sync = setup.rows_to_sync
        partition_settings = setup.partition_settings
        duplicate_primary_keys = setup.duplicate_primary_keys

        def get_rows() -> Iterator[Any]:
            arrow_schema = table.to_arrow_schema()
            with self.connect(config) as streaming_connection:
                streaming_connection.adapters.register_loader("json", JsonAsStringLoader)
                query = _build_query(
                    schema,
                    table_name,
                    should_use_incremental_field,
                    table.type,
                    incremental_field,
                    incremental_field_type,
                    db_incremental_field_last_value,
                    enabled_columns=enabled_columns,
                    primary_keys=primary_keys,
                    row_filters=row_filters,
                )
                logger.debug(f"Redshift query: {query.as_string()}")

                # Left in the connection's default (autocommit off) transaction: Redshift only
                # allows a cursor inside an explicit transaction block, and only one open per
                # session — this connection is dedicated to the stream, so neither binds.
                yield from _stream_arrow_batches(
                    streaming_connection,
                    query,
                    chunk_size,
                    arrow_schema,
                    f"posthog_{inputs.team_id}_{schema}.{table_name}",
                    logger,
                    primary_keys=primary_keys,
                )

        return SourceResponse(
            name=location.response_name,
            items=get_rows,
            primary_keys=primary_keys,
            partition_count=partition_settings.partition_count if partition_settings else None,
            partition_size=partition_settings.partition_size if partition_settings else None,
            rows_to_sync=rows_to_sync,
            has_duplicate_primary_keys=duplicate_primary_keys,
        )
