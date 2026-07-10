"""MySQL driver for PostHog's data-warehouse import pipeline.

Everything MySQL-specific — connection lifecycle (with SSH tunnel),
schema listing, per-cursor metadata for the streaming sync, the dlt
pipeline build, type conversions, the `FORCE INDEX` bad-plan fallback —
lives on `MySQLImplementation`. The source-class `MySQLSource` is a
thin PostHog-layer wrapper that just holds an instance and validates
credentials.

Module-level free helpers (`_build_query`, `_sanitize_identifier`,
`_safe_convert_date`, `_safe_convert_datetime`, `_is_bad_plan_error`)
are pure functions used by `MySQLImplementation` and exercised directly
by unit tests. They take no MySQL-driver state and are fine as
module-scope primitives.
"""

from __future__ import annotations

import time
import datetime
import collections
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from typing import Any, TypeVar

from django.conf import settings

import pyarrow as pa
import pymysql
import structlog
import pymysql.converters
from pymysql.constants import FIELD_TYPE
from pymysql.cursors import Cursor, SSCursor
from structlog.types import FilteringBoundLogger

# Module-level error-capture seam. This module's best-effort probes (get_rows_to_sync,
# explain_query, fetch_average_row_size) deliberately do NOT report handled failures here;
# their guard tests patch `mysql.capture_exception` to enforce that.
from posthog.exceptions_capture import capture_exception  # noqa: F401

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
    BacktickIdentifierQuoter,
    Column,
    InvalidIdentifierError,
    SelectQueryBuilder,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import MySQLSourceConfig
from products.warehouse_sources.backend.types import IncrementalFieldType, PartitionSettings

__all__ = [
    "MySQLColumn",
    "MySQLImplementation",
    "STATEMENT_TIMEOUT_SECONDS",
    "filter_mysql_incremental_fields",
    "get_connection_metadata",
]

_IDENTIFIER_QUOTER = BacktickIdentifierQuoter()
_QUERY_BUILDER = SelectQueryBuilder(quoter=_IDENTIFIER_QUOTER)

# Applied to the row-streaming connection so large result preparation
# (e.g. filesort on a multi-GB table) doesn't hit MySQL's default 60s
# net_write_timeout before the first rows are ready. Used for both the
# client-side PyMySQL read_timeout and the server-side SET SESSION
# net_write_timeout / net_read_timeout — PyMySQL and MySQL both take seconds.
STATEMENT_TIMEOUT_SECONDS = 600  # 10 mins

# pymysql error code for "Lost connection to MySQL server during query" — the
# symptom we see when the optimizer picks a bad plan (full scan + filesort) and
# the filesort preparation exceeds a middlebox / server-side query timeout
# before any rows stream back.
_LOST_CONNECTION_DURING_QUERY_CODE = 2013

# pymysql error code for "Out of sort memory, consider increasing server sort
# buffer size" — the same bad plan (full scan + filesort over the incremental
# field) seen from the other side: the filesort completes its planning but the
# server's `sort_buffer_size` is too small to hold the sort, so MySQL aborts
# before streaming. Forcing the incremental-field index lets MySQL read rows in
# index order and skip the filesort entirely, so the same FORCE INDEX fallback
# resolves it.
_OUT_OF_SORT_MEMORY_CODE = 1038

# pymysql error code for "Can't connect to MySQL server on '...'" — raised at
# connect time when the socket connect can't be established. The parenthesised
# suffix carries the underlying cause (a timeout vs. a refused connection vs. a
# failed DNS lookup), which is how we tell a transient timeout apart from a hard
# config error.
_CANT_CONNECT_CODE = 2003

_SYSTEM_SCHEMAS = ("information_schema", "mysql", "performance_schema", "sys")


def _configured_schema(config: MySQLSourceConfig) -> str | None:
    return normalize_namespace(config.schema)


def _display_table_name(source_schema: str, table_name: str, *, configured_schema: str | None) -> str:
    if configured_schema is not None:
        return table_name
    return f"{source_schema}.{table_name}"


def _source_table_names(display_names: list[str], *, configured_schema: str | None) -> tuple[str, ...]:
    names = set()
    for display_name in display_names:
        if configured_schema is None and "." in display_name:
            _, _, table_name = display_name.partition(".")
            names.add(table_name)
        else:
            names.add(display_name)
    return tuple(sorted(names))


def _matches_requested_name(
    requested_names: set[str],
    *,
    source_schema: str,
    table_name: str,
    configured_schema: str | None,
) -> bool:
    display_name = _display_table_name(source_schema, table_name, configured_schema=configured_schema)
    return (
        display_name in requested_names
        or table_name in requested_names
        or f"{source_schema}.{table_name}" in requested_names
    )


def _source_location_from_display_name(display_name: str, *, configured_schema: str | None) -> tuple[str | None, str]:
    if configured_schema is not None:
        return configured_schema, display_name
    source_schema, separator, table_name = display_name.partition(".")
    if separator:
        return normalize_namespace(source_schema), table_name
    return None, display_name


def _safe_convert_date(obj: Any) -> datetime.date | None:
    """Convert MySQL date, returning None for invalid dates like '0000-00-00'."""
    if isinstance(obj, (bytes, bytearray)):
        obj = obj.decode("utf-8")
    try:
        parts = obj.split("-", 2)
        return datetime.date(int(parts[0]), int(parts[1]), int(parts[2]))
    except (ValueError, IndexError, AttributeError):
        return None


def _safe_convert_datetime(obj: Any) -> datetime.datetime | None:
    """Convert MySQL datetime/timestamp, returning None for invalid values like '0000-00-00 00:00:00'."""
    if isinstance(obj, (bytes, bytearray)):
        obj = obj.decode("utf-8")
    try:
        date_part, time_part = obj.split(" ", 1)
        date_values = [int(x) for x in date_part.split("-", 2)]
        time_parts = time_part.split(":", 2)
        hours = int(time_parts[0])
        minutes = int(time_parts[1])
        # Handle optional microseconds
        sec_parts = time_parts[2].split(".", 1)
        seconds = int(sec_parts[0])
        microseconds = int(sec_parts[1].ljust(6, "0")) if len(sec_parts) > 1 else 0
        return datetime.datetime(date_values[0], date_values[1], date_values[2], hours, minutes, seconds, microseconds)
    except (ValueError, IndexError, AttributeError):
        return None


# Custom conversions that return None for MySQL zero dates instead of raw strings
_MYSQL_SAFE_CONVERSIONS: dict[type[object] | int, Any] = {
    **pymysql.converters.conversions,
    FIELD_TYPE.DATE: _safe_convert_date,
    FIELD_TYPE.DATETIME: _safe_convert_datetime,
    FIELD_TYPE.TIMESTAMP: _safe_convert_datetime,
}


def filter_mysql_incremental_fields(
    columns: list[tuple[str, str, bool]],
) -> list[tuple[str, IncrementalFieldType, bool]]:
    results: list[tuple[str, IncrementalFieldType, bool]] = []
    for column_name, type, nullable in columns:
        type = type.lower()
        if type.startswith("timestamp"):
            results.append((column_name, IncrementalFieldType.Timestamp, nullable))
        elif type == "date":
            results.append((column_name, IncrementalFieldType.Date, nullable))
        elif type == "datetime":
            results.append((column_name, IncrementalFieldType.DateTime, nullable))
        elif type == "tinyint" or type == "smallint" or type == "mediumint" or type == "int" or type == "bigint":
            results.append((column_name, IncrementalFieldType.Integer, nullable))

    return results


def _sanitize_identifier(identifier: str) -> str:
    """Back-compat shim for callers that still expect a plain `ValueError`.

    New code should use `BacktickIdentifierQuoter` directly — same allowlist,
    same quoting, exposed through the shared `IdentifierQuoter` interface.
    """
    try:
        return _IDENTIFIER_QUOTER.quote(identifier)
    except InvalidIdentifierError as e:
        # Preserve the old message shape so semgrep / log-matching rules that
        # key on the old text keep working.
        raise ValueError(f"Invalid SQL identifier: {identifier}") from e


def _build_query(
    schema: str,
    table_name: str,
    should_use_incremental_field: bool,
    incremental_field: str | None,
    incremental_field_type: IncrementalFieldType | None,
    db_incremental_field_last_value: Any | None,
    force_index_name: str | None = None,
    enabled_columns: list[str] | None = None,
    primary_keys: list[str] | None = None,
    row_filters: list[ValidatedRowFilter] | None = None,
) -> tuple[str, dict[str, Any]]:
    hint: str | None = None
    if force_index_name is not None:
        # Sanitize before building the hint — bad names must fail fast.
        hint = f"FORCE INDEX ({_IDENTIFIER_QUOTER.quote(force_index_name)})"

    if not should_use_incremental_field:
        result = _QUERY_BUILDER.select_all(
            schema=schema,
            table_name=table_name,
            extra_table_hint=hint,
            enabled_columns=enabled_columns,
            primary_keys=primary_keys,
            row_filters=row_filters,
        )
        params = result.params if isinstance(result.params, dict) else {}
        return result.sql, params

    if incremental_field is None or incremental_field_type is None:
        raise ValueError("incremental_field and incremental_field_type can't be None")

    result = _QUERY_BUILDER.select_all(
        schema=schema,
        table_name=table_name,
        incremental_field=incremental_field,
        incremental_field_type=incremental_field_type,
        incremental_last_value=db_incremental_field_last_value,
        extra_table_hint=hint,
        enabled_columns=enabled_columns,
        primary_keys=primary_keys,
        row_filters=row_filters,
    )
    params = result.params if isinstance(result.params, dict) else {}
    return result.sql, params


def _is_bad_plan_error(e: pymysql.err.OperationalError) -> bool:
    """Return True if the error is a symptom of MySQL filesorting the incremental
    `ORDER BY` instead of using an index — recoverable via the FORCE INDEX fallback.

    Matches two codes, both signalling the optimizer picked a full scan + filesort
    over the incremental field:

    - `2013` (lost connection during query): the filesort preparation outran a
      middlebox / server-side query timeout before any rows streamed back.
    - `1038` (out of sort memory): the filesort itself overran the server's
      `sort_buffer_size`.

    Forcing the incremental-field index makes MySQL read rows in index order and
    skip the filesort, resolving both. Other `OperationalError`s (access denied,
    table missing, etc.) should propagate untouched.
    """
    code = e.args[0] if e.args else None
    return code in (_LOST_CONNECTION_DURING_QUERY_CODE, _OUT_OF_SORT_MEMORY_CODE)


# Number of times `connect` will open a fresh pymysql connection before giving up. Matches the
# Postgres source's `_retry_on_connection_dropped` budget so the in-process window spans the few
# seconds a real failover / idle cull / tunnel hiccup takes to recover, rather than exhausting in
# ~3s and surfacing the drop as error-tracking noise.
_MAX_CONNECT_ATTEMPTS = 5

# pymysql error code 2003 (CR_CONN_HOST_ERROR): the catch-all "Can't connect to MySQL server
# on '<host>'" raised for any failure to establish the connection. Almost always a deterministic
# config problem (wrong host/port, closed firewall) and so non-retryable — the one transient
# exception is an SSL handshake the peer aborted with an unexpected EOF (see
# `_is_transient_connect_drop`).
_CANT_CONNECT_TO_SERVER_CODE = 2003

# OpenSSL's signature for "the peer closed the connection before the TLS handshake finished".
# pymysql wraps it as the 2003 connect failure above. Unlike WRONG_VERSION_NUMBER (a server that
# doesn't speak TLS at all — a deterministic config error, already non-retryable), an unexpected
# EOF mid-handshake is a transient drop: an overloaded server, a proxy/load-balancer idle cull, a
# failover, or a momentary network blip, all of which a fresh attempt recovers from. Mirrors the
# Postgres source, which retries its own "SSL connection has been closed unexpectedly" on connect.
_SSL_UNEXPECTED_EOF_TOKEN = "[SSL: UNEXPECTED_EOF_WHILE_READING]"

# paramiko raises a bare, message-less EOFError from `start_client` when the SSH gateway accepts
# the TCP connection but closes it during the SSH handshake — a non-SSH service on the port, a
# bastion refusing PostHog's IPs, or a proxy that resets the stream. sshtunnel doesn't wrap it
# (it only translates *auth* failures into BaseSSHTunnelForwarderError), so it escapes with an
# empty `str()`, matching no non-retryable rule and retrying forever. `connect` translates it into
# this stable, classifiable message (see `MySQLSource.get_non_retryable_errors`) — same
# gateway-configuration class as a wrapped "Could not establish session to SSH gateway" failure.
# Distinct from the `[SSL: UNEXPECTED_EOF_WHILE_READING]` token above, which is a transient drop in
# the *database* TLS handshake (deliberately kept retryable).
_SSH_HANDSHAKE_EOF_ERROR = "SSH gateway closed the connection during the SSH handshake"


def _is_transient_connect_drop(e: BaseException) -> bool:
    """Return True if the connection was dropped mid-handshake — a transient blip.

    Two shapes share this transient class, both surfaced by pymysql as an
    `OperationalError` at connect time:

    - `2013` (lost connection): a socket close while reading the server greeting —
      an overloaded server, a proxy idle cull, a failover, a momentary network blip.
      A fresh attempt recovers. The one 2013 that is *not* transient is the SSL-version
      mismatch (a deterministic config error, already non-retryable): it arrives with an
      `[SSL: ...` suffix, so exclude that and let it surface.
    - `2003` (can't connect) carrying an `[SSL: UNEXPECTED_EOF_WHILE_READING]` cause:
      the peer aborted the TLS handshake with an unexpected EOF — the SSL-flavoured
      sibling of the 2013 drop, equally transient. The generic 2003 (wrong host/port,
      firewall) stays non-retryable, so match only the unexpected-EOF token.
    """
    if not isinstance(e, pymysql.err.OperationalError):
        return False
    code = e.args[0] if e.args else None
    args_text = " ".join(str(arg) for arg in e.args)
    if code == _LOST_CONNECTION_DURING_QUERY_CODE:
        return "[SSL:" not in args_text
    if code == _CANT_CONNECT_TO_SERVER_CODE:
        return _SSL_UNEXPECTED_EOF_TOKEN in args_text
    return False


def _is_transient_connect_timeout(e: BaseException) -> bool:
    """Return True if the initial connect timed out — a transient blip.

    A connect that outruns `connect_timeout` surfaces as pymysql 2003
    ("Can't connect to MySQL server on '...' (timed out)") wrapping the socket
    `TimeoutError`. Unlike the other 2003 causes — a refused connection or a
    failed DNS lookup, both deterministic host/port misconfig that stay
    non-retryable via the "Can't connect to MySQL server on" classifier — a
    timeout usually means the server was momentarily slow or unreachable (an
    overloaded server, a cold PlanetScale endpoint, a brief network blip), so a
    fresh attempt recovers. Match only the "timed out" payload so the persistent
    failures still surface.
    """
    if not isinstance(e, pymysql.err.OperationalError):
        return False
    code = e.args[0] if e.args else None
    if code != _CANT_CONNECT_CODE:
        return False
    return "timed out" in " ".join(str(arg) for arg in e.args)


# pymysql raises this `InternalError` from `_read_packet` when an incoming packet's
# sequence number doesn't match the expected one (it `_force_close()`s the socket first).
_PACKET_SEQUENCE_ERROR_PHRASE = "Packet sequence number wrong"


def _is_transient_packet_sequence_error(e: BaseException) -> bool:
    """Return True if the handshake stream desynced mid-exchange — a transient blip.

    A packet-sequence mismatch during connect means the server's handshake reply
    arrived out of order or truncated (an overloaded server, a proxy/load balancer
    interfering, a momentary network blip) and pymysql force-closed the dead socket.
    It's the same transient class as the 2013 drop above and a fresh attempt recovers,
    but it surfaces as `InternalError`, not `OperationalError`, so it needs its own
    predicate. Match the stable phrase, not the volatile got/expected packet numbers.
    """
    if not isinstance(e, pymysql.err.InternalError):
        return False
    return any(_PACKET_SEQUENCE_ERROR_PHRASE in str(arg) for arg in e.args)


# Vitess/PlanetScale vtgate surfaces a backend tablet it can't reach at connect time as pymysql
# OperationalError(1815, 'internal connection error: dial tcp <addr>: connect: connection timed
# out, after N attempts, reqid=...'): the vtgate handshake succeeds but dialing the tablet behind
# it times out — a failover, a restart, or a momentary network blip that a fresh attempt recovers
# from. 1815 is MySQL's generic ER_INTERNAL_ERROR, so key on the Go-network `dial tcp` +
# `connection timed out` signature (no plain MySQL error carries the `dial tcp` token) rather than
# the bare code; the volatile tablet address, attempt count, and reqid stay untouched. This is the
# connect-time sibling of the `code = Unavailable` tablet-unavailable case, which instead lands on
# the first query after connect (see `_is_transient_tablet_unavailable`).
_VITESS_DIAL_TOKEN = "dial tcp"
_VITESS_DIAL_TIMEOUT_TOKEN = "connection timed out"


def _is_transient_vitess_dial_timeout(e: BaseException) -> bool:
    """Return True if a Vitess vtgate timed out dialing its backend tablet — a transient blip."""
    if not isinstance(e, pymysql.err.OperationalError):
        return False
    args_text = " ".join(str(arg) for arg in e.args)
    return _VITESS_DIAL_TOKEN in args_text and _VITESS_DIAL_TIMEOUT_TOKEN in args_text


def _connect_with_transient_retry(kwargs: dict[str, Any]) -> pymysql.Connection:
    """Open a pymysql connection, retrying a transient drop or timeout on connect.

    Mirrors the in-process connect retry the Postgres source uses: a momentary
    drop or timeout while establishing the connection recovers on a fresh attempt,
    so retry it here with a bounded backoff instead of failing schema discovery /
    sync setup on the first blip and surfacing it as captured error-tracking noise.
    """
    attempt = 0
    while True:
        try:
            return pymysql.connect(**kwargs)
        except pymysql.err.DatabaseError as e:
            attempt += 1
            if attempt >= _MAX_CONNECT_ATTEMPTS or not (
                _is_transient_connect_drop(e)
                or _is_transient_connect_timeout(e)
                or _is_transient_packet_sequence_error(e)
                or _is_transient_vitess_dial_timeout(e)
            ):
                raise
            structlog.get_logger().warning(
                "Transient MySQL connection error during connect; retrying",
                attempt=attempt,
                max_attempts=_MAX_CONNECT_ATTEMPTS,
                exc_info=e,
            )
            time.sleep(min(2 * attempt, 30))


_T = TypeVar("_T")

# Vitess/PlanetScale vtgate wraps a momentarily-unreachable backend tablet (a failover,
# restart, or rollout) as pymysql OperationalError(1105) carrying the gRPC status
# `code = Unavailable`. 1105 is MySQL's generic ER_UNKNOWN_ERROR catch-all, so we key on
# the stable `code = Unavailable` token rather than the bare code — the volatile
# target/host/port and other 1105 payloads stay untouched.
_GRPC_UNAVAILABLE_TOKEN = "code = Unavailable"


def _is_transient_tablet_unavailable(e: BaseException) -> bool:
    """Return True if a Vitess vtgate reported its backend tablet transiently unavailable.

    gRPC `Unavailable` is the canonical retry-me status: the tablet is briefly
    unreachable (failover, restart) even though the vtgate handshake succeeded, so the
    first query after connect fails with a 1105 `code = Unavailable`. A fresh attempt
    after a short backoff usually lands on a healthy tablet.
    """
    if not isinstance(e, pymysql.err.OperationalError):
        return False
    return _GRPC_UNAVAILABLE_TOKEN in " ".join(str(arg) for arg in e.args)


def _retry_on_transient_tablet_unavailable(
    operation: Callable[[], _T],
    logger: FilteringBoundLogger,
    *,
    max_attempts: int = _MAX_CONNECT_ATTEMPTS,
) -> _T:
    """Run `operation`, retrying a transient Vitess tablet-unavailable error.

    Mirrors `_connect_with_transient_retry`, but covers the metadata queries that run on
    a freshly opened connection: reconnecting alone doesn't help when the vtgate
    handshake succeeds and only the first query hits an unavailable tablet, so retry the
    whole operation (which reopens the connection) with a bounded backoff instead of
    failing sync setup on the first blip and surfacing it as captured error-tracking
    noise. Non-transient errors re-raise immediately because
    `_is_transient_tablet_unavailable` only matches the gRPC `Unavailable` status.
    """
    attempt = 0
    while True:
        try:
            return operation()
        except pymysql.err.OperationalError as e:
            attempt += 1
            if attempt >= max_attempts or not _is_transient_tablet_unavailable(e):
                raise
            logger.warning(
                "Transient MySQL tablet-unavailable error during metadata discovery; retrying",
                attempt=attempt,
                max_attempts=max_attempts,
                exc_info=e,
            )
            time.sleep(min(2 * attempt, 30))


def _release_streaming_cursor(cursor: SSCursor) -> None:
    """Detach an unbuffered cursor from its connection without draining it.

    PyMySQL's `SSCursor.close()` (and its `__del__`) finishes the unbuffered
    query by reading every outstanding row packet from the server via
    `_finish_unbuffered_query`. When we abandon a stream early — a cancelled
    Temporal activity injects `GeneratorExit`, or the FORCE INDEX fallback
    restarts the query — that drain runs against a connection that is already
    going away and raises `OperationalError(2013, 'Lost connection to MySQL
    server during query')` from inside the teardown path, masking the real
    reason iteration stopped. Clearing the connection reference is exactly what
    PyMySQL does once a query is fully consumed, so the cursor's later
    `close`/`__del__` becomes a no-op and the owning `with self.connect(...)`
    block closes the socket cleanly.
    """
    # PyMySQL clears this same attribute once a query is fully consumed; the
    # stub types it non-optional, so we mirror that runtime behaviour here.
    cursor.connection = None  # type: ignore[assignment]  # ty: ignore[invalid-assignment]


def get_connection_metadata(conn: pymysql.Connection, *, database: str) -> dict[str, Any]:
    """Connection metadata persisted on a direct-query source for the HogQL executor."""
    with conn.cursor() as cursor:
        cursor.execute("SELECT DATABASE(), VERSION()")
        row = cursor.fetchone()
    current_database = str(row[0]) if row and row[0] is not None else database
    version = str(row[1]) if row and row[1] is not None else ""
    # The HogQL direct-query executor only branches postgres-vs-mysql on `engine`, so
    # MariaDB also reports "mysql"; the version string still identifies MariaDB servers.
    return {
        "database": current_database,
        "version": version,
        "engine": "mysql",
    }


class MySQLColumn(Column):
    """`Column` for a MySQL source — carries enough type info to build a PyArrow field.

    Attributes:
        name: Column name.
        data_type: Base MySQL type (`int`, `varchar`, `decimal`, …).
        column_type: Full type string including modifiers (e.g. `int(10) unsigned`),
            used to detect `unsigned` which affects the PyArrow integer width.
        nullable: Whether the column is nullable in MySQL.
        numeric_precision / numeric_scale: Populated only for `decimal` / `numeric`.
    """

    def __init__(
        self,
        name: str,
        data_type: str,
        column_type: str,
        nullable: bool,
        numeric_precision: int | None = None,
        numeric_scale: int | None = None,
    ) -> None:
        self.name = name
        self.data_type = data_type
        self.column_type = column_type
        self.nullable = nullable
        self.numeric_precision = numeric_precision
        self.numeric_scale = numeric_scale

    def to_arrow_field(self) -> pa.Field[pa.DataType]:
        """Return a `pyarrow.Field` that closely matches this column."""
        arrow_type: pa.DataType

        # deltalake doesn't support unsigned types, so unsigned ints are
        # widened to the next signed type that can hold their range.
        is_unsigned = "unsigned" in self.column_type

        match self.data_type.lower():
            case "bigint":
                # No larger type than (u)int64 — keep unsigned semantics.
                arrow_type = pa.uint64() if is_unsigned else pa.int64()
            case "int" | "integer" | "mediumint":
                arrow_type = pa.uint64() if is_unsigned else pa.int32()
            case "smallint":
                arrow_type = pa.uint32() if is_unsigned else pa.int16()
            case "tinyint":
                arrow_type = pa.uint16() if is_unsigned else pa.int8()
            case "decimal" | "numeric":
                if self.numeric_precision is None or self.numeric_scale is None:
                    raise TypeError("expected `numeric_precision` and `numeric_scale` to be `int`, got `NoneType`")
                arrow_type = build_pyarrow_decimal_type(self.numeric_precision, self.numeric_scale)
            case "float":
                arrow_type = pa.float32()
            case "double" | "double precision":
                arrow_type = pa.float64()
            case "varchar" | "char" | "text" | "mediumtext" | "longtext":
                arrow_type = pa.string()
            case "date":
                # MySQL allows zero dates ('0000-00-00') which we map to None,
                # so date columns must always be nullable in the Arrow schema.
                arrow_type = pa.date32()
                return pa.field(self.name, arrow_type, nullable=True)
            case "datetime" | "timestamp":
                arrow_type = pa.timestamp("us")
                return pa.field(self.name, arrow_type, nullable=True)
            case "time":
                arrow_type = pa.time64("us")
            case "boolean" | "bool":
                arrow_type = pa.bool_()
            case "binary" | "varbinary" | "blob" | "mediumblob" | "longblob":
                arrow_type = pa.binary()
            case "uuid":
                arrow_type = pa.string()
            case "json":
                arrow_type = pa.string()
            case _ if self.data_type.endswith("[]"):  # Array types (not native in MySQL)
                arrow_type = pa.string()
            case _:
                arrow_type = pa.string()

        return pa.field(self.name, arrow_type, nullable=self.nullable)


class MySQLImplementation(SQLSourceImplementation[MySQLSourceConfig, pymysql.Connection, Cursor]):
    """MySQL driver implementation paired with `MySQLSource`.

    One class owns everything MySQL-specific: the SSH tunnel + pymysql
    connection lifecycle, `information_schema`-style batch queries used
    during schema listing, per-cursor metadata used during the streaming
    sync (primary keys, column types, row counts, partition/chunk sizing,
    `FORCE INDEX` index lookup, `EXPLAIN` diagnostics), and the dlt
    pipeline factory (`build_pipeline`).
    """

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    @contextmanager
    def connect(
        self,
        config: MySQLSourceConfig,
        *,
        read_timeout: int | None = None,
    ) -> Iterator[pymysql.Connection]:
        """Open a pymysql connection for the duration of the context.

        Opens the SSH tunnel (if configured), then connects with the
        MySQL-wide conventions: safe date/datetime converters, and a
        PlanetScale workload hint injected automatically when the host
        resolves to a `*.psdb.cloud` address. Callers only vary one
        thing — the streaming path sets `read_timeout=STATEMENT_TIMEOUT_SECONDS`
        so multi-GB filesorts don't drop on middlebox timeouts before the
        first rows are ready.
        """
        ssl_ca: str | None = None
        if config.using_ssl:
            ssl_ca = "/etc/ssl/cert.pem" if settings.DEBUG else "/etc/ssl/certs/ca-certificates.crt"

        with self._ssh_tunnel_endpoint(config) as (host, port):
            kwargs: dict[str, Any] = {
                "host": host,
                "port": port,
                "database": config.database,
                "user": config.user,
                "password": config.password,
                "connect_timeout": 10,
                "ssl_ca": ssl_ca,
                "conv": _MYSQL_SAFE_CONVERSIONS,
                "init_command": "SET workload = 'OLAP';" if host.endswith("psdb.cloud") else None,
            }
            if read_timeout is not None:
                kwargs["read_timeout"] = read_timeout
            with _connect_with_transient_retry(kwargs) as conn:
                yield conn

    @contextmanager
    def _ssh_tunnel_endpoint(self, config: MySQLSourceConfig) -> Iterator[tuple[str, int]]:
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
        conn: pymysql.Connection,
        config: MySQLSourceConfig,
        names: list[str] | None,
    ) -> dict[str, list[tuple[str, str, bool]]]:
        configured_schema = _configured_schema(config)
        requested_names = set(names or [])
        params: dict[str, Any] = {}
        schema_filter = "table_schema NOT IN %(system_schemas)s"
        if configured_schema is not None:
            schema_filter = "table_schema = %(schema)s"
            params["schema"] = configured_schema
        else:
            params["system_schemas"] = _SYSTEM_SCHEMAS

        names_filter = ""
        if names:
            params["names"] = _source_table_names(names, configured_schema=configured_schema)
            names_filter = "AND table_name IN %(names)s"

        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT table_schema, table_name, column_name, data_type, is_nullable"
                " FROM information_schema.columns"
                f" WHERE {schema_filter} {names_filter}"
                " ORDER BY table_schema ASC, table_name ASC, ordinal_position ASC",
                params,
            )
            rows = cursor.fetchall()

        result: dict[str, list[tuple[str, str, bool]]] = collections.defaultdict(list)
        for source_schema, table_name, column_name, data_type, is_nullable in rows:
            if requested_names and not _matches_requested_name(
                requested_names,
                source_schema=source_schema,
                table_name=table_name,
                configured_schema=configured_schema,
            ):
                continue
            display_name = _display_table_name(source_schema, table_name, configured_schema=configured_schema)
            result[display_name].append((column_name, data_type, is_nullable == "YES"))
        return dict(result)

    def get_primary_keys(
        self,
        conn: pymysql.Connection,
        config: MySQLSourceConfig,
        tables: list[str],
    ) -> dict[str, list[str] | None]:
        """Detect primary keys for every table in a single query.

        Permission-sensitive — some MySQL deployments restrict access to
        `information_schema.TABLE_CONSTRAINTS`. Swallow and log any
        failure so schema discovery keeps working without PKs.
        """
        result: dict[str, list[str] | None] = dict.fromkeys(tables)
        if not tables:
            return result

        configured_schema = _configured_schema(config)
        schema_filter = "tc.TABLE_SCHEMA NOT IN %(system_schemas)s"
        params: dict[str, Any] = {
            "names": _source_table_names(tables, configured_schema=configured_schema),
        }
        if configured_schema is not None:
            schema_filter = "tc.TABLE_SCHEMA = %(schema)s"
            params["schema"] = configured_schema
        else:
            params["system_schemas"] = _SYSTEM_SCHEMAS

        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT tc.TABLE_SCHEMA, tc.TABLE_NAME, kcu.COLUMN_NAME
                    FROM information_schema.TABLE_CONSTRAINTS tc
                    JOIN information_schema.KEY_COLUMN_USAGE kcu
                    ON tc.CONSTRAINT_NAME = kcu.CONSTRAINT_NAME
                    AND tc.TABLE_SCHEMA = kcu.TABLE_SCHEMA
                    AND tc.TABLE_NAME = kcu.TABLE_NAME
                    WHERE {schema_filter}
                    AND tc.TABLE_NAME IN %(names)s
                    AND tc.CONSTRAINT_TYPE = 'PRIMARY KEY'
                    """.format(schema_filter=schema_filter),
                    params,
                )
                rows = cursor.fetchall()
        except Exception as e:
            structlog.get_logger().warning("Failed to detect primary keys for MySQL schemas", exc_info=e)
            return result

        pks: dict[str, list[str]] = collections.defaultdict(list)
        for source_schema, table_name, column_name in rows:
            display_name = _display_table_name(source_schema, table_name, configured_schema=configured_schema)
            if display_name in result:
                pks[display_name].append(column_name)
        for table_name, pk_cols in pks.items():
            result[table_name] = pk_cols
        return result

    def get_incremental_filter(self) -> IncrementalFieldFilter:
        return filter_mysql_incremental_fields

    def get_leading_index_columns(
        self,
        conn: pymysql.Connection,
        config: MySQLSourceConfig,
        tables: list[str],
    ) -> dict[str, set[str]] | None:
        """Return the leading column of each index per table.

        `information_schema.STATISTICS` lists every index (primary, unique,
        secondary) one row per column. `SEQ_IN_INDEX = 1` identifies the
        first column of each index, which is what speeds up
        `WHERE col >= …` predicates. Returns `None` when discovery fails
        so the caller defaults to no warning; tables with no indexes still
        appear with an empty set so the UI can distinguish them from
        "lookup failed".
        """
        if not tables:
            return {}

        configured_schema = _configured_schema(config)
        schema_filter = "TABLE_SCHEMA NOT IN %(system_schemas)s"
        params: dict[str, Any] = {
            "names": _source_table_names(tables, configured_schema=configured_schema),
        }
        if configured_schema is not None:
            schema_filter = "TABLE_SCHEMA = %(schema)s"
            params["schema"] = configured_schema
        else:
            params["system_schemas"] = _SYSTEM_SCHEMAS

        result: dict[str, set[str]] = {table: set() for table in tables}
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME
                    FROM information_schema.STATISTICS
                    WHERE {schema_filter}
                      AND TABLE_NAME IN %(names)s
                      AND SEQ_IN_INDEX = 1
                    """.format(schema_filter=schema_filter),
                    params,
                )
                for source_schema, table_name, column_name in cursor.fetchall():
                    display_name = _display_table_name(source_schema, table_name, configured_schema=configured_schema)
                    if display_name in result:
                        result[display_name].add(column_name)
        except Exception as e:
            structlog.get_logger().warning("Failed to detect leading index columns for MySQL schemas", exc_info=e)
            return None
        return result

    def get_source_metadata(
        self,
        conn: pymysql.Connection,
        config: MySQLSourceConfig,
        tables: list[str],
    ) -> SourceMetadata:
        configured_schema = _configured_schema(config)
        metadata = SourceMetadata()
        for display_name in tables:
            source_schema, source_table_name = _source_location_from_display_name(
                display_name,
                configured_schema=configured_schema,
            )
            metadata.schema_by_table[display_name] = source_schema
            metadata.table_name_by_table[display_name] = source_table_name
        return metadata

    # ------------------------------------------------------------------
    # Per-cursor metadata — used during `build_pipeline`
    # ------------------------------------------------------------------

    def get_primary_keys_for_table(self, cursor: Cursor, schema: str, table_name: str) -> list[str] | None:
        """Return the primary-key column names for a single table, or None."""
        cursor.execute(
            """
                SELECT COLUMN_NAME
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = %(schema)s
                AND TABLE_NAME = %(table_name)s
                AND COLUMN_KEY = 'PRI'
            """,
            {"schema": schema, "table_name": table_name},
        )
        rows = cursor.fetchall()
        if len(rows) > 0:
            return [row[0] for row in rows]
        return None

    def get_table_metadata(self, cursor: Cursor, schema: str, table_name: str) -> Table[MySQLColumn]:
        """Return rich column metadata for building a PyArrow schema."""
        cursor.execute(
            """
                SELECT
                    column_name,
                    data_type,
                    column_type,
                    is_nullable,
                    numeric_precision,
                    numeric_scale
                FROM
                    information_schema.columns
                WHERE
                    table_schema = %(schema)s
                    AND table_name = %(table_name)s
            """,
            {"schema": schema, "table_name": table_name},
        )

        numeric_data_types = {"numeric", "decimal"}
        columns = []
        for name, data_type, column_type, nullable, numeric_precision_candidate, numeric_scale_candidate in cursor:
            if data_type in numeric_data_types:
                numeric_precision = (
                    numeric_precision_candidate
                    if numeric_precision_candidate is not None
                    else DEFAULT_NUMERIC_PRECISION
                )
                numeric_scale = (
                    numeric_scale_candidate if numeric_scale_candidate is not None else DEFAULT_NUMERIC_SCALE
                )
            else:
                numeric_precision = None
                numeric_scale = None

            columns.append(
                MySQLColumn(
                    name=name,
                    data_type=data_type,
                    column_type=column_type,
                    nullable=nullable,
                    numeric_precision=numeric_precision,
                    numeric_scale=numeric_scale,
                )
            )

        return Table(name=table_name, parents=(schema,), columns=columns)

    def get_rows_to_sync(
        self,
        cursor: Cursor,
        inner_query: str,
        inner_query_args: Any,
        logger: FilteringBoundLogger,
    ) -> int:
        """Count the rows the given `inner_query` will produce. Returns 0 on error."""
        try:
            # The MAX_EXECUTION_TIME optimizer hint bounds this probe at 60s —
            # we'd rather return 0 and let the sync proceed than block here.
            query = f"SELECT /*+ MAX_EXECUTION_TIME(60000) */ COUNT(*) FROM ({inner_query}) as t"

            cursor.execute(query, inner_query_args)
            row = cursor.fetchone()

            if row is None:
                logger.debug("get_rows_to_sync: No results returned. Using 0 as rows to sync")
                return 0

            rows_to_sync = row[0] or 0
            rows_to_sync_int = int(rows_to_sync)

            logger.debug(f"get_rows_to_sync: rows_to_sync_int={rows_to_sync_int}")
            return rows_to_sync_int
        except Exception as e:
            # This COUNT(*) is a best-effort estimate for progress reporting and partition sizing.
            # It shares its FROM/WHERE with the real streaming query, so any genuine problem
            # (missing column, bad incremental field, permissions) resurfaces there and is
            # classified through the normal retryable/non-retryable path. The MAX_EXECUTION_TIME
            # hint above also makes timeouts here expected. Capturing it would only flood error
            # tracking with handled duplicates, so we log at debug and fall back to 0.
            logger.debug(f"get_rows_to_sync: Error: {e}. Using 0 as rows to sync", exc_info=e)
            return 0

    def fetch_table_stats(
        self,
        cursor: Cursor,
        schema: str,
        table_name: str,
        logger: FilteringBoundLogger,
    ) -> TableStats | None:
        """Return DATA_LENGTH / TABLE_ROWS for `schema.table_name`.

        `DATA_LENGTH` only covers values in the clustered index — types
        like `TEXT` are stored off-page, so the figure can under-count.
        `TABLE_ROWS` is an InnoDB estimate. Both are close enough to
        size partitions, and cheap compared to a `COUNT(*)` full scan
        that can time out on large tables.
        """
        query = """
            SELECT
                t.DATA_LENGTH AS table_size,
                t.TABLE_ROWS AS row_count
            FROM
                information_schema.TABLES AS t
            WHERE
                t.TABLE_SCHEMA = %(schema)s
                AND t.TABLE_NAME = %(table_name)s
        """
        logger.debug(f"fetch_table_stats: running query {query}")
        cursor.execute(query, {"schema": schema, "table_name": table_name})
        result = cursor.fetchone()
        if result is None:
            logger.debug("fetch_table_stats: no results returning None")
            return None

        table_size, row_count = result
        if table_size is None or row_count is None:
            logger.debug("fetch_table_stats: missing table_size or row_count, returning None")
            return None

        return TableStats(table_size_bytes=int(table_size), row_count=int(row_count))

    def fetch_average_row_size(
        self,
        cursor: Cursor,
        schema: str,
        table_name: str,
        inner_query: str,
        inner_query_args: Any,
        logger: FilteringBoundLogger,
    ) -> int | None:
        """Sample `LENGTH(COALESCE(col, ''))` across columns on the first 1000 rows.

        Column names are pulled from `information_schema.COLUMNS`, then
        each name is passed through the identifier quoter before being
        interpolated into the `LENGTH(...)` sum. `inner_query` is the
        SELECT the sync is about to run — its identifiers were already
        quoted by the shared `SelectQueryBuilder`, and its arguments are
        rebound as parameters here. No untrusted value ever reaches raw
        SQL.
        """
        try:
            cursor.execute(
                """
                    SELECT COLUMN_NAME
                    FROM INFORMATION_SCHEMA.COLUMNS
                    WHERE TABLE_SCHEMA = %(schema)s
                    AND TABLE_NAME = %(table_name)s
                    ORDER BY ORDINAL_POSITION
                """,
                {"schema": schema, "table_name": table_name},
            )
            rows = cursor.fetchall()
            if not rows:
                logger.debug("fetch_average_row_size: No columns found.")
                return None

            columns = [row[0] for row in rows]
            # Column names come from the DB catalog and can legitimately contain
            # characters the identifier allowlist rejects (e.g. `:` or spaces in
            # `Ach:CompanyId`). Row-size estimation is best-effort, so skip any
            # column we can't safely quote rather than abandoning the whole
            # estimate. The allowlist stays the hard boundary for user-supplied
            # identifiers elsewhere.
            quoted_columns = []
            skipped_columns = []
            for col in columns:
                try:
                    quoted_columns.append(_IDENTIFIER_QUOTER.quote(col))
                except InvalidIdentifierError:
                    skipped_columns.append(col)

            if skipped_columns:
                logger.debug(
                    f"fetch_average_row_size: skipping {len(skipped_columns)} unquotable column(s): {skipped_columns}."
                )

            if not quoted_columns:
                logger.debug("fetch_average_row_size: No quotable columns found.")
                return None

            length_sum = " + ".join(f"LENGTH(COALESCE({quoted}, ''))" for quoted in quoted_columns)
            # length_sum and inner_query are built from sanitized identifiers;
            # no user-supplied values are interpolated into the SQL itself.
            size_query = "SELECT AVG(" + length_sum + ") as avg_row_size FROM (" + inner_query + " LIMIT 1000) as t"

            cursor.execute(size_query, inner_query_args)
            row = cursor.fetchone()

            if row is None or row[0] is None:
                logger.debug("fetch_average_row_size: No results returned.")
                return None

            row_size_bytes = max(row[0] or 0, 1)
            return int(row_size_bytes)
        except Exception as e:
            # Row-size sampling is a best-effort probe: on any failure the caller falls back to the
            # default chunk size and the sync proceeds. A genuine problem (missing table, revoked
            # permission) resurfaces in the real extraction query and is classified through the normal
            # retryable/non-retryable path, while a transient connection drop here (e.g. pymysql's
            # `InterfaceError(0, '')` when the socket was already closed) stays retryable there too.
            # Capturing it would only flood error tracking with handled duplicates, so log at debug and
            # fall back. Mirrors `get_partition_settings` and the Redshift source's `fetch_average_row_size`.
            logger.debug(f"fetch_average_row_size: Error: {e}.", exc_info=e)
            return None

    def find_index_for_cursor(
        self,
        cursor: Cursor,
        schema: str,
        table_name: str,
        cursor_field: str,
        logger: FilteringBoundLogger,
    ) -> str | None:
        """Return an index whose leading column equals `cursor_field`.

        Used for the `FORCE INDEX (...)` retry when the optimizer picks
        a full table scan over the incremental field's index.
        Identifiers are quoted before being interpolated into
        `SHOW INDEX FROM ...`; `SHOW INDEX` has no parameterized form in
        MySQL.
        """
        try:
            query = f"SHOW INDEX FROM {_IDENTIFIER_QUOTER.quote(schema)}.{_IDENTIFIER_QUOTER.quote(table_name)}"
            cursor.execute(query)
            rows = cursor.fetchall()
            column_names = [col[0] for col in cursor.description or []]
            # SHOW INDEX column positions vary by MySQL version; look them up by name.
            try:
                key_name_idx = column_names.index("Key_name")
                seq_idx = column_names.index("Seq_in_index")
                column_idx = column_names.index("Column_name")
            except ValueError:
                logger.debug("SHOW INDEX returned unexpected columns: %s", column_names)
                return None

            for row in rows:
                if row[column_idx] == cursor_field and row[seq_idx] == 1:
                    return row[key_name_idx]
            return None
        except Exception as e:
            logger.debug(f"find_index_for_cursor failed: {e}", exc_info=e)
            return None

    def explain_query(
        self,
        cursor: Cursor,
        query: str,
        query_args: Any,
        logger: FilteringBoundLogger,
    ) -> None:
        """Log MySQL `EXPLAIN` output for `query` at debug level.

        Used to diagnose sync failures on large tables — reveals whether
        the optimizer chose full-scan + filesort vs. a range scan on the
        incremental index.
        """
        try:
            explain_query = f"EXPLAIN {query}"
            logger.debug(f"Running EXPLAIN on: {query}")
            cursor.execute(explain_query, query_args)
            rows = cursor.fetchall()
            column_names = [col[0] for col in cursor.description or []]
            explain_lines = [str(dict(zip(column_names, row))) for row in rows]
            logger.debug(f"EXPLAIN result: {' | '.join(explain_lines) if explain_lines else '(empty)'}")
        except Exception as e:
            # EXPLAIN is best-effort diagnostics; its failure never affects the
            # sync (the streaming query runs right after regardless). Capturing
            # here just floods error tracking with benign, non-actionable noise —
            # e.g. MySQL 1345 when EXPLAINing a view whose underlying tables the
            # connected user lacks SHOW VIEW on. Debug-log only, like
            # `find_index_for_cursor`.
            logger.debug(f"EXPLAIN raised an exception: {e}", exc_info=e)

    # ------------------------------------------------------------------
    # Pipeline build — the dlt `SourceResponse` for a single table
    # ------------------------------------------------------------------

    def build_pipeline(self, config: MySQLSourceConfig, inputs: SourceInputs) -> SourceResponse:
        location = resolve_source_location(
            inputs,
            config_namespace=_configured_schema(config),
            default=normalize_namespace(config.database),
        )
        schema = location.schema
        table_name = location.table_name
        if not schema:
            raise ValueError("Schema is missing")
        if not table_name:
            raise ValueError("Table name is missing")

        logger = inputs.logger
        should_use_incremental_field = inputs.should_use_incremental_field
        incremental_field = inputs.incremental_field
        incremental_field_type = inputs.incremental_field_type
        db_incremental_field_last_value = inputs.db_incremental_field_last_value
        enabled_columns = inputs.enabled_columns
        row_filters = inputs.row_filters

        def _discover_metadata() -> tuple[list[str] | None, pa.Schema, int, PartitionSettings | None, int]:
            with self.connect(config) as connection:
                with connection.cursor() as cursor:
                    primary_keys = self.get_primary_keys_for_table(cursor, schema, table_name)
                    full_table = self.get_table_metadata(cursor, schema, table_name)

                    # Resolve PKs before the projection so probe/sample queries match the streaming SELECT.
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
            return primary_keys, arrow_schema, chunk_size, partition_settings, rows_to_sync

        # A PlanetScale/Vitess tablet can be momentarily unavailable even once the vtgate
        # handshake succeeds, so retry the whole metadata-discovery block (reopening the
        # connection) on a transient `code = Unavailable` rather than failing setup on the
        # first blip — see `_retry_on_transient_tablet_unavailable`.
        primary_keys, arrow_schema, chunk_size, partition_settings, rows_to_sync = (
            _retry_on_transient_tablet_unavailable(_discover_metadata, logger)
        )

        def _stream_with_optional_force_index(force_index_name: str | None) -> Iterator[Any]:
            """Open a fresh connection and stream rows.

            The pipeline itself persists the per-batch cursor value (see
            `update_incremental_field_values`), so a retry that restarts
            from the original starting cursor is correct but occasionally
            replays a few already-processed rows; the delta merge
            dedupes by primary key.
            """
            with self.connect(config, read_timeout=STATEMENT_TIMEOUT_SECONDS) as streaming_connection:
                # Bump server-side timeouts for large table scans. The
                # defaults (60s each) are too low for multi-GB unbuffered
                # queries — the server drops the connection before the
                # first rows are ready.
                try:
                    with streaming_connection.cursor() as setup_cursor:
                        setup_cursor.execute(
                            f"SET SESSION net_write_timeout = {STATEMENT_TIMEOUT_SECONDS}, net_read_timeout = {STATEMENT_TIMEOUT_SECONDS}"
                        )
                except Exception as e:
                    logger.warning(f"Failed to set session timeouts on MySQL sync connection: {e}")
                ss_cursor = streaming_connection.cursor(SSCursor)
                try:
                    query, args = _build_query(
                        schema,
                        table_name,
                        should_use_incremental_field,
                        incremental_field,
                        incremental_field_type,
                        db_incremental_field_last_value,
                        force_index_name=force_index_name,
                        enabled_columns=enabled_columns,
                        primary_keys=primary_keys,
                        row_filters=row_filters,
                    )
                    logger.debug(f"MySQL query: {query.format(args)}")

                    # EXPLAIN before the streaming query to help
                    # diagnose failures where MySQL picks full scan
                    # + filesort over the incremental index.
                    # `explain_query` consumes its rows via
                    # fetchall(), leaving the cursor in a clean
                    # state for the streaming execute() below.
                    self.explain_query(ss_cursor, query, args, logger)

                    ss_cursor.execute(query, args)

                    column_names = [column[0] for column in ss_cursor.description or []]

                    while True:
                        # use chunk_size to fetch rows instead of DEFAULT_CHUNK_SIZE
                        batch = ss_cursor.fetchmany(chunk_size)
                        if not batch:
                            break

                        yield table_from_iterator((dict(zip(column_names, row)) for row in batch), arrow_schema)
                finally:
                    # Tear the streaming cursor down without draining the rest of
                    # the unbuffered result set — see `_release_streaming_cursor`.
                    # Closing it normally here would reissue the lost-connection
                    # error over a cancellation or the FORCE INDEX restart.
                    _release_streaming_cursor(ss_cursor)

        def get_rows() -> Iterator[Any]:
            # Track whether any batch reached the pipeline. If one did,
            # the retry path can't safely restart from the original
            # cursor: the delta merge only dedupes rows for `incremental`
            # writes into an existing table (see
            # `delta_table_helper.write_to_deltalake`), so full-refresh
            # and first-ever-sync scenarios would get silent duplicates
            # on replay. The observed bad-plan failure fails before any
            # rows stream, so this guard is defensive — it enforces the
            # invariant the PR assumes.
            yielded_any = False
            try:
                for chunk in _stream_with_optional_force_index(force_index_name=None):
                    yielded_any = True
                    yield chunk
                return
            except pymysql.err.OperationalError as e:
                if not _is_bad_plan_error(e):
                    raise
                if yielded_any:
                    logger.warning(
                        f"Streaming query died with a bad query plan (error {e.args[0] if e.args else '?'}) "
                        f"after already yielding rows — skipping FORCE INDEX fallback to avoid duplicates."
                    )
                    raise
                logger.warning(
                    f"Streaming query died with a bad query plan (error {e.args[0] if e.args else '?'}). "
                    f"Attempting FORCE INDEX fallback."
                )
                if not should_use_incremental_field or not incremental_field:
                    # Without an incremental field there's no cursor to force an index on.
                    logger.warning(
                        "Bad query plan hit, but sync has no incremental field — cannot apply FORCE INDEX fallback."
                    )
                    raise

                with self.connect(config) as probe_connection:
                    with probe_connection.cursor() as probe_cursor:
                        force_index_name = self.find_index_for_cursor(
                            probe_cursor, schema, table_name, incremental_field, logger
                        )

                if not force_index_name:
                    logger.warning(
                        f"Bad query plan hit and no usable index on "
                        f"{schema}.{table_name}.{incremental_field} — cannot apply FORCE INDEX fallback. "
                        f"Customer should add an index on the incremental field."
                    )
                    raise

                logger.warning(f"Retrying streaming query with FORCE INDEX ({force_index_name}) after bad query plan")
                yield from _stream_with_optional_force_index(force_index_name)

        return SourceResponse(
            name=location.response_name,
            items=get_rows,
            primary_keys=primary_keys,
            partition_count=partition_settings.partition_count if partition_settings else None,
            partition_size=partition_settings.partition_size if partition_settings else None,
            rows_to_sync=rows_to_sync,
        )
