from __future__ import annotations

import re
import math
import time
import socket
import ipaddress
import threading
import collections
import dataclasses
from collections.abc import Callable, Iterator
from contextlib import ExitStack, _GeneratorContextManager, contextmanager
from datetime import (
    UTC,
    date,
    datetime,
    time as datetime_time,
    timezone,
)
from typing import TYPE_CHECKING, Any, Literal, LiteralString, Optional, TypeVar, cast

if TYPE_CHECKING:
    from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource

from django.conf import settings

import psycopg
import pyarrow as pa
import structlog
from psycopg import sql
from psycopg.adapt import Loader
from psycopg.types.datetime import TimeLoader, TimestampLoader, TimestamptzLoader, TimetzLoader
from structlog.types import FilteringBoundLogger

from posthog.hogql.database.schema.duckdb_table_functions import is_dangerous_table_function

from posthog.exceptions_capture import capture_exception

from products.warehouse_sources.backend.temporal.data_imports.naming_convention import NamingConvention
from products.warehouse_sources.backend.temporal.data_imports.pipelines.helpers import (
    incremental_type_to_initial_value,
    incremental_type_to_operator,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.consts import (
    DEFAULT_CHUNK_SIZE,
    DEFAULT_TABLE_SIZE_BYTES,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    SourceInputs,
    SourceResponse,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.utils import (
    DEFAULT_NUMERIC_PRECISION,
    DEFAULT_NUMERIC_SCALE,
    DEFAULT_PARTITION_TARGET_SIZE_IN_BYTES,
    MAX_NUMERIC_SCALE,
    QueryTimeoutException,
    TemporaryFileSizeExceedsLimitException,
    build_pyarrow_decimal_type,
    table_from_iterator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import open_ssh_tunnel
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql import (
    Column,
    Table,
    ValidatedRowFilter,
    compute_projected_columns,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.implementation import (
    SQLSourceImplementation,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.incremental import (
    IncrementalFieldFilter,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.predicates_psycopg import (
    and_join,
    render_psycopg_row_filter_conditions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import PostgresSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.exceptions import XminUnsupportedError
from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.partitioned_tables import (
    build_partition_query,
    get_estimated_row_count_for_partitioned_table as _get_estimated_row_count_for_partitioned_table,
    get_partition_settings_for_partitioned_table as _get_partition_settings_for_partitioned_table,
    get_partition_strategy,
    is_partitioned_table as _is_partitioned_table,
    is_supported_incremental_type_for_window,
    iterate_date_windows,
    iterate_partitions,
    list_child_partitions,
)
from products.warehouse_sources.backend.types import IncrementalFieldType, PartitionSettings

# Sources created after this date must use SSL/TLS connections
SSL_REQUIRED_AFTER_DATE = datetime(2026, 2, 18, tzinfo=UTC)
IDENTIFIER_FUNCTION_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
SYSTEM_POSTGRES_SCHEMAS = ["information_schema", "pg_catalog", "pg_toast"]

# Statement timeout applied to the row-streaming connection so a slow FETCH
# (large partitioned scan, cold cache, etc.) does not get killed by a short
# default statement_timeout on the source role.
SYNC_STATEMENT_TIMEOUT_MS = 1000 * 60 * 10  # 10 mins

METADATA_STATEMENT_TIMEOUT_MS = 1000 * 60 * 10  # 10 mins

# Alias for the projected `xmin` system column on xmin syncs. `SELECT *` never returns system
# columns, so it must be projected explicitly; the alias also names the ORDER BY / WHERE cursor.
XMIN_PROJECTED_COLUMN = "_ph_xmin"
# xmin replication relies on `pg_snapshot_xmin` / `xid8`, both PG13+.
XMIN_MIN_SERVER_VERSION = 130000

# In-process retries for a recovery conflict before the abort (non-retryable, see source.py). The
# read path counts these only once the chunk has shrunk to the floor.
_MAX_SETUP_RECOVERY_CONFLICT_RETRIES = 10
_MAX_READ_RECOVERY_CONFLICT_RETRIES = 10
# A shorter query holds its snapshot for less time, lowering the odds the replica cancels it.
_MIN_RECOVERY_CONFLICT_CHUNK_SIZE = 100

# Bounded in-process retries for a transient connection drop hit *during* the setup metadata
# probes (not just the initial connect). Mirrors `_connect_with_dropped_retry`'s default; past
# this the drop is treated as sustained and re-raised for Temporal to retry the whole activity.
_MAX_SETUP_CONNECTION_DROPPED_RETRIES = 5


def source_requires_ssl(source: ExternalDataSource, source_config: Any = None) -> bool:
    """Return whether this source must connect over SSL/TLS.

    SSL is required for sources created after the cutoff date, unless the
    user has explicitly opted out via the ``require_tls`` toggle on an active
    SSH tunnel.
    """
    if source.created_at < SSL_REQUIRED_AFTER_DATE:
        return False

    if source_config is not None:
        # Not every source config carries an SSH tunnel (e.g. Snowflake), and the param is typed
        # `Any` — only the tunnel opt-out can relax the SSL requirement, so its absence means "required".
        ssh_tunnel = getattr(source_config, "ssh_tunnel", None)
        if ssh_tunnel is not None and ssh_tunnel.enabled and not ssh_tunnel.require_tls.enabled:
            return False

    return True


class SSLRequiredError(Exception):
    """Raised when SSL/TLS is required but the database does not support it."""

    pass


# libpq connection option that pins the client encoding to UTF8. Some Postgres-wire-compatible
# engines (notably Amazon Redshift) report their `client_encoding` as the legacy alias `UNICODE`,
# which psycopg3's encoding map doesn't recognise — decoding the first query result then raises
# `NotSupportedError: codec not available in Python: 'UNICODE'`. Forcing the encoding sidesteps it.
FORCE_UTF8_CLIENT_ENCODING = "-c client_encoding=UTF8"


# Substrings PgBouncer / libpq use when the upstream backend connection died
# mid-stream. We hit these when a long-running sync holds a server-side cursor
# (and thus an open transaction) idle across the slow delta-merge phase and the
# source's idle_in_transaction_session_timeout / PgBouncer server_idle_timeout
# culls the backend. They're transient — recover by reconnecting and resuming.
_CONNECTION_DROPPED_ERROR_SUBSTRINGS = (
    "server conn crashed",
    "server closed the connection unexpectedly",
    # Narrow "connection to server …" variants only — a bare "connection to server"
    # would also match initial-connect failures like "connection to server at
    # \"host\" failed: FATAL: password authentication failed", which are permanent
    # and must not be retried.
    "connection to server was lost",
    "connection to server was closed",
    "consuming input failed",
    # The SSL-flavoured drop: an established TLS connection closed mid-handshake or mid-stream
    # (pooler/firewall idle cull, failover, network blip). libpq surfaces it bare as "... failed:
    # SSL connection has been closed unexpectedly" — no "consuming input failed" prefix — so the
    # substring above doesn't catch it. Same transient class; recover by reconnecting. A genuine
    # no-SSL-support source fails with a different message ("server does not support SSL") and, on
    # require_ssl sources, is converted to SSLRequiredError before reaching this check.
    "ssl connection has been closed unexpectedly",
    # The lower-level form of the same TLS drop: a socket-level failure during the SSL handshake or
    # read (EOF, connection reset) surfaces as "... SSL SYSCALL error: EOF detected" (and similar).
    # Same transient class as the bare SSL drop above — a pooler/firewall idle cull, failover, or
    # network blip mid-handshake — and recovers on reconnect. Never the unsupported-SSL signal,
    # which is the distinct "server does not support SSL" message.
    "ssl syscall error",
    "no connection to the server",
    "terminating connection due to",
    # psycopg's own message when libpq finds the socket already gone (PGconn.socket
    # raises this from inside a wait, e.g. the commit at the end of get_connection).
    # Same transient dead-socket class as the libpq drops above — recover by reconnecting.
    "the connection is lost",
    # Supabase's Supavisor pooler reports a transient failure to reach the upstream backend (TCP
    # timeout while the backend is briefly unreachable — failover, idle cull, restart) as a
    # ConnectionFailure (SQLSTATE 08006, an OperationalError) carrying the Erlang-tuple reason
    # "{:error, :etimedout}". Same transient class as the libpq drops above — recover by
    # reconnecting. The Erlang-tuple wording is the stable, low-false-positive signal.
    "{:error, :etimedout}",
    # The connection-refused sibling of "{:error, :etimedout}": Supavisor reaches us fine but the
    # TCP connect to its upstream backend is refused while the backend is briefly down (failover,
    # restart, idle cull), surfacing as a ConnectionFailure carrying "{:error, :econnrefused}". This
    # is distinct from libpq's bare English "Connection refused" (a permanent wrong-host/port
    # misconfiguration that stays non-retryable, see source.py): here the pooler is reachable and the
    # source was streaming moments earlier in the same sync, so a fresh reconnect recovers. Match the
    # Erlang-tuple wording, the stable low-false-positive signal.
    "{:error, :econnrefused}",
    # Neon's proxy reports a compute that didn't finish waking from scale-to-zero before the
    # auth handshake deadline as a ConnectionFailure (SQLSTATE 08006, an OperationalError):
    # "Failed to connect to database: authentication did not complete within <n>ms". The wake is
    # transient (a suspended compute reactivates in seconds), so a fresh connect after a short
    # backoff succeeds — recover by reconnecting rather than failing the whole activity. Match the
    # timeout phrasing, which is distinct from the permanent credential-rejection wordings
    # ("password authentication failed", "SASL authentication failed"), and exclude the volatile
    # millisecond value.
    "authentication did not complete within",
)

# Supavisor (Supabase's connection pooler) doesn't surface a dropped upstream connection with a
# libpq/PgBouncer signature — it raises its own pooler-internal error as a generic psycopg
# InternalError_ (SQLSTATE XX000) carrying a Supavisor error code. The trailing message varies —
# both "(EDBHANDLEREXITED) DbHandler exited. Check logs for more information" and
# "(EDBHANDLEREXITED) connection to database closed. Check logs for more information" have been
# observed for the same condition — but the code is the stable signal, so match the code itself
# rather than any one message wording.
#   - EDBHANDLEREXITED: the pooler's per-session DbHandler process exited because its backend
#     connection died (idle cull, backend restart, failover).
#   - ECHECKOUTRETRIES ("failed to check out a connection after multiple retries"): the pooler
#     couldn't hand us a backend connection after retrying internally — its pool was momentarily
#     exhausted or every backend was busy. A slot frees the moment another session returns one.
# Both are the same transient class as the libpq drops above and recover on reconnect. Genuine
# XX000 internal errors (data corruption, etc.) carry a different code and stay non-recoverable.
#
# Supavisor also surfaces a backend socket that closed mid-session — after the client authenticated
# — as "Internal error (authenticated): :closed", where ":closed" is the Erlang gen_tcp reason for a
# peer-closed socket (its DbHandler lost the backend connection to an idle cull, restart, or
# failover). There's no error code here, so match the full phrase including the ":closed" reason: a
# fresh reconnect re-establishes a new session — the same transient class. Matching only the
# "(authenticated)" wrapper would be too broad: a non-:closed "Internal error (authenticated): ..."
# could be a permanent pooler/protocol failure that should surface immediately, not be retried.
_POOLER_CONNECTION_DROPPED_ERROR_SUBSTRINGS = (
    "edbhandlerexited",
    "echeckoutretries",
    "internal error (authenticated): :closed",
)

# Connect-time capacity errors: the source refuses a *new* connection because it has hit a
# connection limit, not because anything is misconfigured. PostgreSQL raises "sorry, too many
# clients already" once max_connections is reached, "remaining connection slots are reserved for
# roles with the SUPERUSER attribute" once only the superuser_reserved_connections slots remain,
# and "too many connections for role" once a role's own CONNECTION LIMIT is hit. Supabase's
# Supavisor session-mode pooler reports its own variant when every client slot it exposes is in use
# ("(EMAXCONNSESSION) max clients reached in session mode - max clients are limited to pool_size:
# <n>"). All of these are transient capacity conditions on the customer's database or pooler — a
# slot frees the moment another connection closes (or a session ends) — so a fresh connect after a
# short backoff usually succeeds. Retried in-process on the read/sync connect path (see
# `_is_dropped_or_connect_timeout` / `_connect_with_dropped_retry`); kept retryable and intentionally
# NOT added to `get_non_retryable_errors` (see source.py). The Supavisor match is on the stable
# "max clients reached in session mode" phrase, excluding the volatile pool_size and the
# "(EMAXCONNSESSION)" code (mirrors the `PostgresErrors` validation mapping in source.py).
_CONNECTION_LIMIT_ERROR_SUBSTRINGS = (
    "sorry, too many clients already",
    "remaining connection slots are reserved",
    "too many connections for role",
    "max clients reached in session mode",
)

# Exception types that can carry a connection-dropped error. ProtocolViolation is
# PgBouncer's synthetic error packet; OperationalError is libpq detecting the dead
# socket. IdleInTransactionSessionTimeout (SQLSTATE 25P03) is what Postgres raises
# when the source's idle_in_transaction_session_timeout culls our backend while a
# server-side cursor holds a transaction open across the slow delta-merge between
# yields — psycopg maps it to InternalError, not OperationalError, so it must be
# named explicitly or the type-based catch below would miss it. InternalError_ is the
# generic XX000 class Supavisor's "DbHandler exited" pooler drop arrives as; it's only
# treated as a drop when its message matches the narrow pooler signature above.
_CONNECTION_DROPPED_ERROR_TYPES = (
    psycopg.errors.ProtocolViolation,
    psycopg.OperationalError,
    psycopg.errors.IdleInTransactionSessionTimeout,
    psycopg.errors.InternalError_,
)


def _safe_close_connection(connection: psycopg.Connection | None) -> None:
    """Close a connection without raising.

    Prefer this over Connection.__exit__ for teardown in exception handlers:
    __exit__ attempts a commit/rollback first, which can itself raise on a
    broken connection and mask the original error. close() just releases the
    socket. Accepts None so callers can close a connection that was never opened
    (a connect that raised before assigning) without a None-check at each site.
    """
    if connection is None or connection.closed:
        return
    try:
        connection.close()
    except Exception:
        pass


def _is_connection_dropped_error(error: BaseException) -> bool:
    """True if the error indicates the upstream connection was dropped mid-stream.

    psycopg surfaces these as ProtocolViolation (PgBouncer's synthetic error
    packet) or OperationalError (libpq detecting the dead socket), so we match on
    type and message rather than a single SQLSTATE.

    IdleInTransactionSessionTimeout is the exception: it carries SQLSTATE 25P03 and
    unambiguously means the source terminated our backend for holding a transaction
    open too long, so the type alone is enough — no message match required.
    """
    if isinstance(error, psycopg.errors.IdleInTransactionSessionTimeout):
        return True
    if isinstance(error, psycopg.errors.ProtocolViolation | psycopg.OperationalError):
        message = " ".join(str(arg) for arg in error.args).lower()
        return any(substring in message for substring in _CONNECTION_DROPPED_ERROR_SUBSTRINGS)
    # Supavisor's pooler drop arrives as a generic XX000 InternalError_, not the libpq/PgBouncer
    # types above, so match it on its own narrow signature (see _POOLER_CONNECTION_DROPPED_*).
    if isinstance(error, psycopg.errors.InternalError_):
        message = " ".join(str(arg) for arg in error.args).lower()
        return any(substring in message for substring in _POOLER_CONNECTION_DROPPED_ERROR_SUBSTRINGS)
    return False


def _is_connection_limit_error(error: BaseException) -> bool:
    """True if the source refused a connection because it's at a connection limit.

    Usually a connect-time refusal (`psycopg.OperationalError`), but a pooler that caches an
    upstream login failure instead reveals the limit on the first query as a `ProtocolViolation`
    ("server login has been failing, cached error: remaining connection slots are reserved ..."),
    so match that type too. Distinct from `_is_connection_dropped_error` — the backend connection
    was never usable — but the same transient capacity class: a slot frees the moment another
    connection closes, so it stays retryable and is never a `NonRetryableError`.
    """
    if not isinstance(error, psycopg.OperationalError | psycopg.errors.ProtocolViolation):
        return False
    message = " ".join(str(arg) for arg in error.args).lower()
    return any(substring in message for substring in _CONNECTION_LIMIT_ERROR_SUBSTRINGS)


def _is_dropped_or_connect_timeout(error: BaseException) -> bool:
    """Transient connect-path failures the import/read reconnect recovers from in process.

    A mid-stream drop (`_is_connection_dropped_error`), a connect-time timeout, or a connect-time
    connection-limit refusal (`_is_connection_limit_error`). psycopg raises `ConnectionTimeout`
    ("connection timeout expired") only while *establishing* a connection, never mid-query, so on the
    import/read path it's transient: the source was reachable moments earlier in the same sync, and
    the reconnect just needs retrying. Connection-limit refusals ("sorry, too many clients already",
    etc.) are likewise transient — a slot frees the moment another connection closes. Used by the
    read/sync connect retry (`_connect_with_dropped_retry`) and the `offset_chunking` reconnect. The
    schema-discovery path retries drops and connection-limit refusals too (via
    `_is_dropped_or_connection_limit`) but deliberately keeps failing fast on connect-time *timeouts*,
    where a timeout usually means an unreachable host / unconfigured firewall (see `PostgresErrors`
    and `get_non_retryable_errors`).
    """
    return (
        _is_connection_dropped_error(error)
        or _is_connection_limit_error(error)
        or isinstance(error, psycopg.errors.ConnectionTimeout)
    )


def _is_dropped_or_connection_limit(error: BaseException) -> bool:
    """Transient conditions the background schema-discovery retry recovers from in process.

    A mid-stream drop (`_is_connection_dropped_error`) or a connection-limit refusal
    (`_is_connection_limit_error`). Both are transient — a slot frees as connections close, and a
    pooler-cached login failure clears once the upstream has capacity — so discovery retries them on
    a fresh connection instead of failing the activity and surfacing captured error-tracking noise.
    Unlike the read/sync connect path (`_is_dropped_or_connect_timeout`), a connect-time *timeout* is
    deliberately excluded: during discovery a timeout usually means a now-unreachable host, which
    should fail fast rather than burn the retry budget.
    """
    return _is_connection_dropped_error(error) or _is_connection_limit_error(error)


def _raise_if_setup_connection_broken(connection: psycopg.Connection) -> None:
    """Surface a connection dropped during metadata discovery as a retryable error.

    The best-effort probes run during `postgres_source` setup (`_explain_query`,
    `_get_table_chunk_size`, and the numeric-scale probe in `_get_table`) isolate their
    queries in `connection.transaction(savepoint_name=...)`. When the upstream
    connection drops mid-probe, psycopg's `Transaction.__exit__` skips its savepoint
    teardown — it early-returns whenever the connection is no longer OK — leaving the
    connection's transaction-nesting counter incremented. The surrounding helpers then
    swallow the follow-up "connection closed" errors, so discovery finishes "successfully"
    and the implicit commit in the enclosing `with connection:` raises a misleading
    `ProgrammingError: Explicit commit() forbidden within a Transaction context`, burying
    the real cause. Detect the broken connection first and raise the actual
    dropped-connection error (transient, so it stays retryable) — the activity then retries
    on a fresh connection instead of failing on a self-inflicted commit error.
    """
    if connection.broken:
        raise psycopg.OperationalError("connection to server was lost during table metadata discovery")


_T = TypeVar("_T")


def _retry_on_connection_dropped(
    operation: Callable[[], _T],
    logger: FilteringBoundLogger,
    *,
    max_attempts: int = 5,
    is_retryable: Callable[[BaseException], bool] = _is_connection_dropped_error,
) -> _T:
    """Run `operation`, retrying transient connection errors with bounded backoff.

    `is_retryable` decides which errors are transient; it defaults to `_is_connection_dropped_error`
    (mid-stream drops only). The read/sync connect path widens it to also retry connect-time timeouts
    and connection-limit refusals (see `_connect_with_dropped_retry` / `_is_dropped_or_connect_timeout`).
    Permanent errors (auth failures, SSL-required) are re-raised immediately because no predicate
    matches them.
    """
    attempt = 0
    while True:
        try:
            return operation()
        except _CONNECTION_DROPPED_ERROR_TYPES as e:
            if not is_retryable(e):
                raise
            attempt += 1
            if attempt >= max_attempts:
                raise
            logger.debug(f"Transient connection error ({e}). Retrying (attempt {attempt}/{max_attempts})")
            time.sleep(min(2 * attempt, 30))


def _connect_with_dropped_retry(
    connect: Callable[[], psycopg.Connection],
    logger: FilteringBoundLogger,
    *,
    max_attempts: int = 5,
) -> psycopg.Connection:
    """Open a connection via `connect`, retrying transient connection-dropped errors.

    The streaming recovery path (offset chunking) is reached precisely because the
    source just dropped our connection (idle cull, failover, mid-stream SSL EOF), so
    the very reconnect that bootstraps the recovery can itself hit a still-recovering
    source and fail with another connection-dropped error — time out establishing the
    socket, or refuse the reconnect with a connection-limit error while still saturated.
    Without this, that transient failure escapes the recovery loop and fails the whole sync.
    Retry all transient classes with bounded backoff; permanent errors (auth failures,
    SSL-required) are re-raised immediately because no transient predicate matches them.
    """
    return _retry_on_connection_dropped(
        connect, logger, max_attempts=max_attempts, is_retryable=_is_dropped_or_connect_timeout
    )


def _next_recovery_conflict_chunk_size(chunk_size: int, successive_errors: int) -> int:
    # Only shrink on a sustained conflict — successive_errors resets on a yielded chunk.
    if successive_errors >= 5 and chunk_size > _MIN_RECOVERY_CONFLICT_CHUNK_SIZE:
        return max(int(chunk_size / 1.5), _MIN_RECOVERY_CONFLICT_CHUNK_SIZE)
    return chunk_size


def _recovery_conflict_abort_error(retries: int) -> Exception:
    # Non-retryable (see source.py): once in-process retries are exhausted the conflict is sustained,
    # and a whole-activity retry just re-reads from offset 0 into the same wall.
    return Exception(
        f"Read replica kept canceling reads due to conflict with recovery after {retries} retries. "
        f"Increase max_standby_streaming_delay or enable hot_standby_feedback on the replica, or sync "
        f"from the primary database instead of the read replica."
    )


def _statement_timeout_as_non_retryable(
    error: BaseException,
    *,
    should_use_incremental_field: bool,
    incremental_field: str | None,
) -> QueryTimeoutException | None:
    """Classify a statement_timeout (QueryCanceled) hit while streaming rows.

    A chunk/fetch that exhausts the 10-min statement_timeout cannot complete in
    time — usually a missing index on the incremental field or a deep OFFSET scan —
    so retrying is futile. On incremental syncs, map it to the same non-retryable
    QueryTimeoutException the server-cursor and windowed read paths already raise,
    with an actionable message. Returns None when the error is not a statement
    timeout, or the sync is non-incremental (the caller should re-raise the original
    error so a full re-sync can reorder rows safely).
    """
    if not isinstance(error, psycopg.errors.QueryCanceled) or not should_use_incremental_field:
        return None
    return QueryTimeoutException(
        f"10 min timeout statement reached. Please ensure your incremental field "
        f"({incremental_field}) has an appropriate index created"
    )


def _raised_while_closing_generator(error: BaseException) -> bool:
    """True when `error` surfaced while the row generator was being closed.

    Closing a suspended generator raises GeneratorExit at the yield; the server
    cursor / connection `__exit__` then runs and can itself issue a round-trip
    (closing the server cursor, the implicit rollback) that hits the
    statement_timeout and raises QueryCanceled, with the GeneratorExit left as
    its `__context__`. The consumer is already done — the sync finished, or the
    activity is being cancelled — so a teardown error here is irrelevant to the
    sync outcome and must not be re-raised: doing so masks the real cause (e.g.
    the cancellation) and floods error tracking with phantom statement timeouts.
    """
    seen: set[int] = set()
    ctx: BaseException | None = error.__context__
    while ctx is not None and id(ctx) not in seen:
        if isinstance(ctx, GeneratorExit):
            return True
        seen.add(id(ctx))
        ctx = ctx.__context__
    return False


def _pk_uniqueness_probe_timeout_error() -> QueryTimeoutException:
    """Build the timeout error for the fallback `id` primary-key uniqueness probe.

    When a table has no declared primary key we fall back to assuming `id` is unique and verify
    it with a full-table `GROUP BY id HAVING COUNT(*) > 1`, which can exhaust the statement_timeout
    on large tables. The generic table-setup timeout message points at the incremental field, but
    indexing that field doesn't help this probe — the fix is a primary key / index on `id`. Keeps
    the "has an appropriate index" fragment so it stays non-retryable at the activity layer too
    (see source.py).
    """
    return QueryTimeoutException(
        'Timed out verifying that the "id" column is unique. This table has no primary key, so '
        'PostHog assumed "id" was unique to sync incrementally but could not confirm it within the '
        'timeout. Add a primary key, or ensure the "id" column has an appropriate index created, so '
        "PostHog can sync this table incrementally."
    )


@dataclasses.dataclass(frozen=True)
class PostgresDiscoveredSchema:
    source_catalog: str | None
    source_schema: str
    source_table_name: str
    columns: list[tuple[str, str, bool]]


def _is_duckdb_connection(cursor: psycopg.Cursor) -> bool:
    cursor.execute("SELECT version()")
    row = cursor.fetchone()
    version = str(row[0]) if row and row[0] is not None else ""
    return "duckdb" in version.lower() or "duckgres" in version.lower()


def _get_sslmode(require_ssl: bool) -> str:
    """Return the appropriate sslmode based on whether SSL is required.

    Args:
        require_ssl: If True, returns "require" which forces SSL and fails if
            the server doesn't support it. If False, returns "prefer" which
            tries SSL but falls back to unencrypted if not available.
    """

    if settings.TEST or settings.DEBUG or settings.E2E_TESTING:
        return "prefer"

    return "require" if require_ssl else "prefer"


# Transaction-mode connection poolers reject the libpq `options` startup parameter outright:
# Supabase's Supavisor (port 6543) and PgBouncer in transaction mode report "unsupported startup
# parameter: options", and AWS RDS Proxy reports "RDS Proxy currently doesn't support command-line
# options". We only send `options` to pin client_encoding=UTF8 for Redshift's legacy UNICODE alias
# (see FORCE_UTF8_CLIENT_ENCODING), and Redshift never sits behind these poolers — so when a server
# rejects `options`, dropping it and retrying is safe (UTF8 is the default client encoding for real
# Postgres). The RDS Proxy text uses a typographic apostrophe, so match the apostrophe-free tail.
_OPTIONS_STARTUP_PARAM_UNSUPPORTED_SUBSTRINGS = (
    "unsupported startup parameter: options",
    "support command-line options",
)


def _is_options_startup_param_unsupported(error: BaseException) -> bool:
    if not isinstance(error, psycopg.OperationalError):
        return False
    message = " ".join(str(arg) for arg in error.args).lower()
    return any(substring in message for substring in _OPTIONS_STARTUP_PARAM_UNSUPPORTED_SUBSTRINGS)


# libpq reports a non-'S'/'N' byte to its SSLRequest packet as "received invalid response to SSL
# negotiation: <byte>". The handshake mentions SSL, but the cause is that the host/port doesn't
# reach a PostgreSQL server speaking the SSL protocol — a wrong port, an HTTP/proxy/edge endpoint,
# or a TCP proxy fronting a paused/deleted database. Don't mislabel it "SSL not supported": let the
# raw message reach `get_non_retryable_errors` for an accurate, non-retryable diagnosis.
_INVALID_SSL_NEGOTIATION_RESPONSE_SUBSTRING = "received invalid response to ssl negotiation"


def _is_invalid_ssl_negotiation_response(error: BaseException) -> bool:
    return _INVALID_SSL_NEGOTIATION_RESPONSE_SUBSTRING in " ".join(str(arg) for arg in error.args).lower()


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip("[]"))
        return True
    except ValueError:
        return False


def _resolve_hostaddr_with_timeout(host: str, port: int, timeout: float) -> str | None:
    """Resolve `host` to an IP under a wall-clock `timeout`, to hand psycopg as `hostaddr`.

    psycopg3 resolves hostnames in Python before libpq ever connects — `conninfo_attempts` calls
    `socket.getaddrinfo` (see psycopg/_conninfo_attempts.py) and only then passes the resolved address
    to libpq. `connect_timeout` bounds establishing the socket, never that name lookup, so a stalled
    or unresponsive resolver blocks the (threaded, non-interruptible) sync activity for as long as the
    OS resolver takes. It never trips `connect_timeout`; the activity instead runs until Temporal's
    `start_to_close_timeout` cancels the worker thread mid-`getaddrinfo`, surfacing a misleading
    `CancelledError` and burning the whole activity's retry budget. Resolving here and passing the
    address via `hostaddr` (which makes psycopg skip its own lookup) turns a stalled resolver into a
    fast, retryable error instead.

    Returns None when there is nothing to bound — an empty host, a Unix-socket path, or a host that is
    already an IP literal — and also on a genuine resolution failure, so psycopg connects (and
    re-raises that failure) exactly as before and the existing "Name or service not known"
    classification still applies. Only a resolver that exceeds `timeout` becomes an `OperationalError`;
    its message deliberately avoids the non-retryable "could not translate host name" /
    "Name or service not known" fragments because a stalled resolver is usually transient.
    """
    if not host or host.startswith("/") or _is_ip_literal(host):
        return None

    addrinfo: list[Any] = []
    lookup_error: list[BaseException] = []

    def _lookup() -> None:
        try:
            addrinfo.extend(socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP, type=socket.SOCK_STREAM))
        except BaseException as e:  # noqa: BLE001 — surfaced to the caller below via lookup_error
            lookup_error.append(e)

    # Daemon thread so a stalled getaddrinfo can be abandoned without blocking worker shutdown or
    # piling up non-daemon threads — the OS resolver bounds the orphaned lookup on its own.
    thread = threading.Thread(target=_lookup, daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        raise psycopg.OperationalError(f"Timed out resolving database host name after {timeout}s")
    # A genuine resolution failure falls through to None so psycopg connects and re-raises it,
    # preserving the existing "Name or service not known" classification.
    if lookup_error:
        if isinstance(lookup_error[0], OSError):
            return None
        raise lookup_error[0]
    if not addrinfo:
        return None
    # sockaddr[0] is the address string (getaddrinfo types it as str | int across the IPv4/IPv6
    # tuple variants, so coerce to satisfy the str return type).
    return str(addrinfo[0][4][0])


def _connect_with_options_fallback(**connect_kwargs: Any) -> psycopg.Connection:
    """`psycopg.connect` that retries without the libpq `options` startup parameter when the
    server rejects it.

    See `_OPTIONS_STARTUP_PARAM_UNSUPPORTED_SUBSTRINGS` for why transaction-mode poolers reject
    `options` and why dropping it is safe.
    """
    try:
        return psycopg.connect(**connect_kwargs)
    except psycopg.OperationalError as e:
        if not (connect_kwargs.get("options") and _is_options_startup_param_unsupported(e)):
            raise
    # Retry outside the `except` block: a genuine failure on the options-less connect (bad
    # password, tenant not found) must propagate on its own, not chained to the benign — and now
    # recovered — "options unsupported" error, which otherwise masks the real cause in error tracking.
    return psycopg.connect(**{k: v for k, v in connect_kwargs.items() if k != "options"})


def _connect_to_postgres(
    *,
    host: str,
    port: int,
    database: str,
    user: str,
    password: str,
    require_ssl: bool = False,
    connect_timeout: int = 15,
    **kwargs: Any,
) -> psycopg.Connection:
    sslmode = _get_sslmode(require_ssl)
    # Redshift (and other Postgres-wire-compatible engines) report `client_encoding` as the legacy
    # alias `UNICODE`, which psycopg3's encoding map doesn't recognise — it raises
    # `NotSupportedError: codec not available in Python: 'UNICODE'` the first time it decodes a query
    # result. Pinning the client encoding makes the server report `UTF8` instead, which psycopg maps
    # cleanly. We always force UTF8 and append any caller-supplied `options` after it.
    caller_options = kwargs.pop("options", None)
    options = f"{FORCE_UTF8_CLIENT_ENCODING} {caller_options}" if caller_options else FORCE_UTF8_CLIENT_ENCODING
    # Bound psycopg's Python-side DNS lookup in production (see `_resolve_hostaddr_with_timeout`).
    # Dev/test connect to local or fake hosts, so skip the real lookup there — mirrors `_get_sslmode`.
    if not (settings.TEST or settings.DEBUG or settings.E2E_TESTING):
        hostaddr = _resolve_hostaddr_with_timeout(host, port, connect_timeout)
        if hostaddr is not None:
            kwargs["hostaddr"] = hostaddr
    try:
        return _connect_with_options_fallback(
            host=host,
            port=port,
            dbname=database,
            user=user,
            password=password,
            sslmode=sslmode,
            connect_timeout=connect_timeout,
            sslrootcert="/tmp/no.txt",
            sslcert="/tmp/no.txt",
            sslkey="/tmp/no.txt",
            keepalives=1,
            keepalives_idle=30,
            keepalives_interval=10,
            keepalives_count=5,
            options=options,
            **kwargs,
        )
    except psycopg.OperationalError as e:
        if (
            require_ssl
            and "SSL" in str(e)
            and not _is_invalid_ssl_negotiation_response(e)
            and not _is_connection_dropped_error(e)
        ):
            raise SSLRequiredError(
                "SSL/TLS connection is required but your database does not support it. "
                "Please enable SSL/TLS on your PostgreSQL server or contact your database administrator."
            ) from e
        raise


@contextmanager
def pg_connection(
    *,
    host: str,
    port: int,
    database: str,
    user: str,
    password: str,
    require_ssl: bool = False,
) -> Iterator[psycopg.Connection]:
    """Context manager that opens a postgres connection and ensures it is closed on exit."""
    conn = _connect_to_postgres(
        host=host, port=port, database=database, user=user, password=password, require_ssl=require_ssl
    )
    try:
        yield conn
    finally:
        conn.close()


def get_primary_key_columns(conn: psycopg.Connection, schema: str, table_names: list[str]) -> dict[str, list[str]]:
    """Return ordered PK columns per table: {table_name: [col, ...]}.

    Uses pg_catalog rather than information_schema because information_schema views
    are ACL-filtered — a user with only SELECT grants may not see PK constraint rows
    depending on PostgreSQL version, which would silently hide `supports_cdc=True`
    for their tables and make CDC look unavailable in the source wizard.
    """
    if not table_names:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.relname AS table_name,
                   a.attname AS column_name,
                   array_position(i.indkey, a.attnum) AS ord
            FROM pg_index i
            JOIN pg_class c ON c.oid = i.indrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = ANY(i.indkey)
            WHERE i.indisprimary
              AND n.nspname = %s
              AND c.relname = ANY(%s)
            ORDER BY c.relname, array_position(i.indkey, a.attnum)
            """,
            (schema, table_names),
        )
        result: dict[str, list[str]] = {}
        for row in cur:
            result.setdefault(row[0], []).append(row[1])
    return result


def get_leading_index_columns(
    conn: psycopg.Connection, schema: str, table_names: list[str]
) -> dict[str, set[str]] | None:
    """Return the set of columns that are the leading column of any index per table.

    Used to surface a UI warning when a user picks an incremental field that isn't
    indexed — those would force a full scan on every sync. Includes the primary key
    (since PKs back an implicit index in Postgres). Excludes:

    - `indkey[0] = 0`: the leading index entry is an expression (e.g. a functional
      index on `lower(email)`), not a plain column — we can't tell whether it
      accelerates `WHERE col >= …` so don't claim it does.
    - `indisvalid = false`: the index isn't usable by the planner (failed
      `CREATE INDEX CONCURRENTLY`, in-progress build) and won't accelerate any
      query.
    - `indpred IS NOT NULL`: partial indexes only accelerate queries whose
      predicate the planner can prove implies the index predicate. Most partial
      indexes in practice (`WHERE deleted_at IS NULL` and similar) don't apply
      to the incremental sync's `WHERE col >= last_max`, so flagging the
      leading column as indexed would suppress a warning the user genuinely
      needs.

    Returns None when discovery fails (e.g. permission issues on system catalogs)
    so the caller can default to no warning rather than blowing away other
    discovery results.
    """
    if not table_names:
        return {}
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT c.relname AS table_name,
                       a.attname AS column_name
                FROM pg_index i
                JOIN pg_class c ON c.oid = i.indrelid
                JOIN pg_namespace n ON n.oid = c.relnamespace
                JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = i.indkey[0]
                WHERE i.indkey[0] <> 0
                  AND i.indisvalid
                  AND i.indpred IS NULL
                  AND n.nspname = %s
                  AND c.relname = ANY(%s)
                """,
                (schema, table_names),
            )
            result: dict[str, set[str]] = {}
            for row in cur:
                result.setdefault(row[0], set()).add(row[1])
        return result
    except Exception as e:
        structlog.get_logger().warning("Failed to detect leading index columns for Postgres schemas", exc_info=e)
        return None


def _normalize_function_names(function_names: list[Any]) -> list[str]:
    return sorted(
        {
            function_name.lower()
            for function_name in function_names
            if isinstance(function_name, str) and IDENTIFIER_FUNCTION_NAME_RE.fullmatch(function_name)
        }
    )


def filter_postgres_incremental_fields(
    columns: list[tuple[str, str, bool]],
) -> list[tuple[str, IncrementalFieldType, bool]]:
    results: list[tuple[str, IncrementalFieldType, bool]] = []
    for column_name, type, nullable in columns:
        type = type.lower()
        if type.startswith("timestamp"):
            results.append((column_name, IncrementalFieldType.Timestamp, nullable))
        elif type == "date":
            results.append((column_name, IncrementalFieldType.Date, nullable))
        elif type == "integer" or type == "smallint" or type == "bigint":
            results.append((column_name, IncrementalFieldType.Integer, nullable))

    return results


def _normalize_selected_schema(schema: str | None) -> str | None:
    if not isinstance(schema, str):
        return None

    normalized = schema.strip()
    return normalized or None


def _get_display_table_name(schema_name: str, table_name: str, *, qualify_with_schema: bool) -> str:
    return f"{schema_name}.{table_name}" if qualify_with_schema else table_name


def _build_named_value_placeholders(prefix: str, values: list[str]) -> tuple[str, dict[str, str]]:
    placeholders: list[str] = []
    params: dict[str, str] = {}

    for index, value in enumerate(values):
        key = f"{prefix}_{index}"
        placeholders.append(f"%({key})s")
        params[key] = value

    return ", ".join(placeholders), params


def _get_discovered_tables(
    cursor: psycopg.Cursor, schema: str | None, names: list[str] | None = None
) -> tuple[dict[str, tuple[str | None, str, str]], bool]:
    selected_schema = _normalize_selected_schema(schema)
    qualify_with_schema = selected_schema is None
    is_duckdb = _is_duckdb_connection(cursor)

    if is_duckdb:
        cursor.execute("SELECT current_database()")
        row = cursor.fetchone()
        current_database = str(row[0]) if row and row[0] is not None else None

        if selected_schema is not None:
            cursor.execute(
                """
                SELECT table_catalog, table_schema, table_name
                FROM information_schema.tables
                WHERE table_catalog = %(current_database)s
                  AND table_schema = %(schema)s
                ORDER BY table_schema, table_name
                """,
                {"current_database": current_database, "schema": selected_schema},
            )
        else:
            system_schema_placeholders, system_schema_params = _build_named_value_placeholders(
                "system_schema", SYSTEM_POSTGRES_SCHEMAS
            )
            cursor.execute(
                f"""
                SELECT table_catalog, table_schema, table_name
                FROM information_schema.tables
                WHERE table_catalog = %(current_database)s
                  AND table_schema NOT IN ({system_schema_placeholders})
                ORDER BY table_schema, table_name
                """,
                {"current_database": current_database, **system_schema_params},
            )

        discovered_rows = cursor.fetchall()
        all_tables = {
            _get_display_table_name(schema_name, table_name, qualify_with_schema=qualify_with_schema): (
                table_catalog,
                schema_name,
                table_name,
            )
            for table_catalog, schema_name, table_name in discovered_rows
        }
    else:
        # pg_class covers all syncable relkinds: r/p (tables), v/m (views), f (foreign).
        if selected_schema is not None:
            cursor.execute(
                """
                SELECT n.nspname AS schema_name, c.relname AS table_name
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE c.relkind IN ('r', 'p', 'v', 'm', 'f')
                  AND n.nspname = %(schema)s
                ORDER BY n.nspname, c.relname
                """,
                {"schema": selected_schema},
            )
        else:
            system_schema_placeholders, system_schema_params = _build_named_value_placeholders(
                "system_schema", SYSTEM_POSTGRES_SCHEMAS
            )
            cursor.execute(
                f"""
                SELECT n.nspname AS schema_name, c.relname AS table_name
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE c.relkind IN ('r', 'p', 'v', 'm', 'f')
                  AND n.nspname NOT IN ({system_schema_placeholders})
                  AND n.nspname NOT LIKE 'pg_temp_%%'
                  AND n.nspname NOT LIKE 'pg_toast_temp_%%'
                ORDER BY n.nspname, c.relname
                """,
                system_schema_params,
            )

        discovered_rows = cursor.fetchall()
        all_tables = {
            _get_display_table_name(schema_name, table_name, qualify_with_schema=qualify_with_schema): (
                None,
                schema_name,
                table_name,
            )
            for schema_name, table_name in discovered_rows
        }

    if names is None:
        return all_tables, qualify_with_schema

    # Match qualified (`schema.table`) and bare `table` names — keys may differ after multi-schema migration.
    filtered: dict[str, tuple[str | None, str, str]] = {}
    for name in names:
        if name in all_tables:
            filtered[name] = all_tables[name]
        elif "." in name:
            _, _, unqualified = name.partition(".")
            if unqualified in all_tables:
                filtered[name] = all_tables[unqualified]
    return filtered, qualify_with_schema


def _row_counts_from_conn(
    connection: psycopg.Connection,
    schema: str | None,
    names: list[str] | None,
) -> dict[str, int]:
    if _normalize_selected_schema(schema) is None and not names:
        return {}
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                sql.SQL("SET LOCAL statement_timeout = {timeout}").format(
                    timeout=sql.Literal(1000 * 30)  # 30 secs
                )
            )
            discovered_tables, _qualify_with_schema = _get_discovered_tables(cursor, schema, names)
            if not discovered_tables:
                return {}

            counts = [
                sql.SQL("SELECT {table_name} AS table_name, COUNT(*) AS row_count FROM {schema}.{table}").format(
                    table_name=sql.Literal(display_name),
                    schema=sql.Identifier(schema_name),
                    table=sql.Identifier(table_name),
                )
                for display_name, (_source_catalog, schema_name, table_name) in discovered_tables.items()
            ]

            union_counts = sql.SQL(" UNION ALL ").join(counts)
            cursor.execute(union_counts)
            row_count_result = cursor.fetchall()
            return {row[0]: row[1] for row in row_count_result}
    except:
        return {}


def _is_unsupported_function_error(error: Exception, function_name: str) -> bool:
    """True when `error` says the database doesn't implement `function_name`.

    Real Postgres raises `UndefinedFunction` (SQLSTATE 42883), but Postgres-wire-compatible engines
    (DuckDB/Flight-SQL-backed proxies, etc.) accept the connection yet lack Postgres-only catalog
    functions like `row_security_active`, surfacing the failure as a generic error whose SQLSTATE we
    can't rely on. Match the function name plus a "missing function" signal in the message so callers
    can degrade quietly instead of alerting on an expected, already-handled shape.
    """
    if isinstance(error, psycopg.errors.UndefinedFunction):
        return True
    message = str(error).lower()
    if function_name.lower() not in message:
        return False
    return any(marker in message for marker in ("does not exist", "unknown function", "not found", "no function"))


def _rls_active_from_conn(
    connection: psycopg.Connection,
    schema: str | None,
    names: list[str] | None,
) -> dict[str, bool]:
    """Per-table map of whether row-level security is active for the connecting role.

    Runs even with no schema/names selected: `row_security_active` is a cheap catalog lookup, so
    there's no cost reason to skip it on the full-table-list view — and that view (the source setup
    picker) is exactly where the warning needs to show.

    One set-based catalog query rather than a per-table function call, so an odd relation (a view, a
    foreign table, one dropped mid-discovery) is simply absent from the result instead of erroring
    the whole batch and dropping every table's warning. Returns only the tables it could resolve;
    callers treat a missing key as "no warning".
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                sql.SQL("SET LOCAL statement_timeout = {timeout}").format(
                    timeout=sql.Literal(1000 * 30)  # 30 secs
                )
            )
            discovered_tables, _qualify_with_schema = _get_discovered_tables(cursor, schema, names)
            if not discovered_tables:
                return {}

            # (source schema, source table) -> the display name used as the schema key elsewhere.
            display_by_source = {
                (schema_name, table_name): display_name
                for display_name, (_source_catalog, schema_name, table_name) in discovered_tables.items()
            }
            wanted = sql.SQL(", ").join(
                sql.SQL("({}, {})").format(sql.Literal(schema_name), sql.Literal(table_name))
                for schema_name, table_name in display_by_source
            )
            # relkind r/p only: RLS is meaningless on views/foreign tables, and row_security_active
            # is never called on them so a discovered view can't error the query.
            query = sql.SQL("""
                SELECT n.nspname, c.relname, row_security_active(c.oid)
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                JOIN (VALUES {wanted}) AS want(schema_name, table_name)
                    ON n.nspname::text = want.schema_name AND c.relname::text = want.table_name
                WHERE c.relkind IN ('r', 'p')
            """).format(wanted=wanted)

            cursor.execute(query)
            result: dict[str, bool] = {}
            for nspname, relname, rls_active in cursor.fetchall():
                display_name = display_by_source.get((nspname, relname))
                if display_name is not None:
                    result[display_name] = bool(rls_active)
            return result
    except Exception as e:
        # This runs on a connection shared with earlier best-effort metadata lookups (PK + index
        # discovery). When one of those fails on a non-Postgres engine — e.g. a Redshift-incompatible
        # `pg_catalog` query — its exception is caught upstream but the connection's transaction is
        # left in `INERROR`, so our first statement here fails with `InFailedSqlTransaction` purely as
        # a downstream symptom. A harsher variant of the same thing: an earlier probe (or a transient
        # drop — SSH-tunnel hiccup, idle cull, failover) leaves the shared connection closed/broken,
        # so our `cursor()` call surfaces as `OperationalError: the connection is closed`. Both are
        # already-handled downstream symptoms, not bugs in this lookup, so don't re-capture them
        # (mirrors `_get_partition_settings` and the caller's own connection-level handler).
        #
        # Postgres-wire-compatible engines (DuckDB/Flight-SQL proxies, etc.) accept our connection
        # but don't implement `row_security_active`. RLS is a Postgres-only concept there, so a
        # missing-function error is an expected "no RLS" answer, not a bug — degrade quietly rather
        # than flooding error tracking. Still capture genuinely unexpected failures.
        if (
            not connection.closed
            and not connection.broken
            and not isinstance(e, psycopg.errors.InFailedSqlTransaction)
            and not _is_unsupported_function_error(e, "row_security_active")
        ):
            capture_exception(e)
        return {}


def _xmin_capable_tables_from_conn(
    connection: psycopg.Connection,
    schema: str | None,
    names: list[str] | None,
) -> set[str]:
    """Display names of relations that can support an xmin sync.

    xmin needs a physical heap tuple (`relkind` `r`/`m` — ordinary tables and materialized views)
    and PG13+ (for `pg_snapshot_xmin`/`xid8`). Partitioned parents (`p`), plain views (`v`) and
    foreign tables (`f`) are excluded: the parent has no tuples of its own and a single global
    ceiling can't span its children's independent xid spaces.
    """
    try:
        if connection.info.server_version < XMIN_MIN_SERVER_VERSION:
            return set()
        with connection.cursor() as cursor:
            cursor.execute(
                sql.SQL("SET LOCAL statement_timeout = {timeout}").format(timeout=sql.Literal(1000 * 30))  # 30 secs
            )
            discovered_tables, _qualify_with_schema = _get_discovered_tables(cursor, schema, names)
            if not discovered_tables:
                return set()

            display_by_source = {
                (schema_name, table_name): display_name
                for display_name, (_source_catalog, schema_name, table_name) in discovered_tables.items()
            }
            wanted = sql.SQL(", ").join(
                sql.SQL("({}, {})").format(sql.Literal(schema_name), sql.Literal(table_name))
                for schema_name, table_name in display_by_source
            )
            query = sql.SQL("""
                SELECT n.nspname, c.relname
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                JOIN (VALUES {wanted}) AS want(schema_name, table_name)
                    ON n.nspname::text = want.schema_name AND c.relname::text = want.table_name
                WHERE c.relkind IN ('r', 'm')
            """).format(wanted=wanted)

            cursor.execute(query)
            capable: set[str] = set()
            for nspname, relname in cursor.fetchall():
                display_name = display_by_source.get((nspname, relname))
                if display_name is not None:
                    capable.add(display_name)
            return capable
    except Exception as e:
        # Best-effort like the PK/RLS/index lookups it runs alongside: losing the `supports_xmin`
        # hint just hides the option for this listing. A non-Postgres engine may lack `relkind`
        # semantics entirely, so degrade quietly.
        if not connection.closed and not connection.broken and not isinstance(e, psycopg.errors.InFailedSqlTransaction):
            structlog.get_logger().warning("Failed to detect xmin-capable tables for Postgres schemas", exc_info=e)
        return set()


def get_postgres_row_count(
    host: str,
    port: int,
    database: str,
    user: str,
    password: str,
    schema: str | None,
    require_ssl: bool = False,
    names: list[str] | None = None,
) -> dict[str, int]:
    if _normalize_selected_schema(schema) is None and not names:
        return {}
    try:
        with pg_connection(
            host=host, port=port, database=database, user=user, password=password, require_ssl=require_ssl
        ) as connection:
            return _row_counts_from_conn(connection, schema, names)
    except:
        return {}


def _schemas_from_conn(
    connection: psycopg.Connection,
    schema: str | None,
    names: list[str] | None,
) -> dict[str, PostgresDiscoveredSchema]:
    """Discover columns for tables on the given pre-opened connection."""
    with connection.cursor() as cursor:
        # Raise statement_timeout for the catalog scan below. Some hosted/pooled Postgres set a
        # short role/server default that cancels the `information_schema.columns` query
        # (QueryCanceled) on large schemas before discovery finishes — the read path guards its own
        # metadata query the same way in `_get_table`. Best-effort: engines without statement_timeout
        # (e.g. DuckDB) reject the SET, so clear the aborted transaction and fall back to the default.
        try:
            cursor.execute(
                sql.SQL("SET statement_timeout = {timeout}").format(timeout=sql.Literal(METADATA_STATEMENT_TIMEOUT_MS))
            )
        except psycopg.Error as e:
            # A dropped or connection-limit-refused upstream fails on this first query too — a pooler
            # surfacing "remaining connection slots are reserved ..." on the first statement. Rolling
            # that back raises a misleading "the connection is lost" that buries the real cause, so
            # re-raise the true error and let the discovery retry recover on a fresh connection. A
            # live engine that merely rejects the SET (e.g. DuckDB) is not a drop/limit: clear the
            # aborted transaction and fall back to the default timeout.
            if _is_connection_dropped_error(e) or _is_connection_limit_error(e):
                raise
            connection.rollback()

        discovered_tables, _qualify_with_schema = _get_discovered_tables(cursor, schema, names)
        if not discovered_tables:
            return {}

        source_schemas = sorted(
            {schema_name for _table_catalog, schema_name, _table_name in discovered_tables.values()}
        )
        schema_placeholders, schema_params = _build_named_value_placeholders("schema", source_schemas)

        cursor.execute(
            f"""
            SELECT * FROM (
                SELECT
                    table_schema,
                    table_name,
                    column_name,
                    data_type,
                    is_nullable,
                    ordinal_position
                FROM information_schema.columns
                WHERE table_schema IN ({schema_placeholders})
                UNION ALL
                SELECT
                    n.nspname AS table_schema,
                    c.relname AS table_name,
                    a.attname AS column_name,
                    pg_catalog.format_type(a.atttypid, a.atttypmod) AS data_type,
                    CASE WHEN a.attnotnull THEN 'NO' ELSE 'YES' END AS is_nullable,
                    a.attnum AS ordinal_position
                FROM pg_class c
                JOIN pg_namespace n ON c.relnamespace = n.oid
                JOIN pg_attribute a ON a.attrelid = c.oid
                WHERE c.relkind = 'm'
                  AND n.nspname IN ({schema_placeholders})
                  AND a.attnum > 0
                  AND NOT a.attisdropped
            ) t
            ORDER BY table_schema ASC, table_name ASC, ordinal_position ASC
            """,
            schema_params,
        )
        result = cursor.fetchall()

        columns_by_table: dict[str, list[tuple[str, str, bool]]] = collections.defaultdict(list)
        discovered_pairs_by_schema_and_table = {
            (schema_name, table_name): display_name
            for display_name, (_source_catalog, schema_name, table_name) in discovered_tables.items()
        }
        for table_schema, table_name, column_name, data_type, is_nullable, _ordinal_position in result:
            display_name = discovered_pairs_by_schema_and_table.get((table_schema, table_name))
            if display_name is None:
                continue

            columns_by_table[display_name].append((column_name, data_type, is_nullable == "YES"))

        return {
            display_name: PostgresDiscoveredSchema(
                source_catalog=source_catalog,
                source_schema=schema_name,
                source_table_name=table_name,
                columns=columns_by_table.get(display_name, []),
            )
            for display_name, (source_catalog, schema_name, table_name) in discovered_tables.items()
        }


def get_schemas(
    host: str,
    database: str,
    user: str,
    password: str,
    schema: str | None,
    port: int,
    require_ssl: bool = False,
    names: list[str] | None = None,
) -> dict[str, PostgresDiscoveredSchema]:
    """Get all tables from PostgreSQL source schemas to sync."""

    # Schema discovery opens a fresh connection on its own periodic cadence. A transient drop —
    # "server closed the connection unexpectedly" / an SSL EOF from a pooler, firewall, or
    # SSH-tunnel hiccup, or a Supavisor "DbHandler exited" (EDBHANDLEREXITED) mid-query — is the
    # same class the import read path already retries via `_connect_with_dropped_retry`.
    # Transaction-mode poolers (Supabase's Supavisor, PgBouncer) routinely accept the client
    # connection and only drop the upstream backend once the first query runs, so the drop can land
    # either on connect or on the first discovery query (e.g. `SELECT version()` in
    # `_is_duckdb_connection`). Retry the whole connect-and-discover cycle on a fresh connection so
    # the retry spans both — otherwise the blip fails the discovery activity and surfaces as
    # captured error-tracking noise even though the next attempt would succeed. Connection-limit
    # refusals ("remaining connection slots are reserved", "sorry, too many clients already") are
    # retried the same way — the customer's database is momentarily out of slots and frees one as
    # connections close. Permanent errors (auth failures, SSL-required) re-raise immediately because
    # `_is_dropped_or_connection_limit` matches only transient drops and connection-limit refusals.
    def _connect_and_discover() -> dict[str, PostgresDiscoveredSchema]:
        connection = _connect_to_postgres(
            host=host, port=port, database=database, user=user, password=password, require_ssl=require_ssl
        )
        try:
            return _schemas_from_conn(connection, schema, names)
        finally:
            connection.close()

    return _retry_on_connection_dropped(
        _connect_and_discover,
        structlog.get_logger(),
        max_attempts=_MAX_SETUP_CONNECTION_DROPPED_RETRIES,
        is_retryable=_is_dropped_or_connection_limit,
    )


def get_primary_keys_for_schemas(
    host: str,
    database: str,
    user: str,
    password: str,
    schema: str,
    port: int,
    table_names: list[str],
    require_ssl: bool = False,
) -> dict[str, list[str] | None]:
    """Detect primary keys for all tables in a single query."""
    result: dict[str, list[str] | None] = dict.fromkeys(table_names)

    try:
        with pg_connection(
            host=host, port=port, database=database, user=user, password=password, require_ssl=require_ssl
        ) as connection:
            pks = get_primary_key_columns(connection, schema, table_names)
            for table_name, pk_cols in pks.items():
                result[table_name] = pk_cols
    except Exception as e:
        structlog.get_logger().warning("Failed to detect primary keys for Postgres schemas", exc_info=e)

    return result


def _foreign_keys_from_conn(
    connection: psycopg.Connection,
    schema: str | None,
    names: list[str] | None,
) -> dict[str, list[tuple[str, str, str]]]:
    """Discover foreign keys on a pre-opened connection."""
    with connection.cursor() as cursor:
        discovered_tables, qualify_with_schema = _get_discovered_tables(cursor, schema, names)
        if not discovered_tables:
            return {}

        source_schemas = sorted(
            {schema_name for _table_catalog, schema_name, _table_name in discovered_tables.values()}
        )
        schema_placeholders, schema_params = _build_named_value_placeholders("schema", source_schemas)

        cursor.execute(
            f"""
            SELECT
                tc.table_schema AS source_schema_name,
                tc.table_name AS table_name,
                kcu.column_name AS column_name,
                ccu.table_schema AS target_schema_name,
                ccu.table_name AS target_table_name,
                ccu.column_name AS target_column_name
            FROM information_schema.table_constraints AS tc
            JOIN information_schema.key_column_usage AS kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.constraint_schema = kcu.constraint_schema
                AND tc.table_schema = kcu.table_schema
            JOIN information_schema.constraint_column_usage AS ccu
                ON ccu.constraint_name = tc.constraint_name
                AND ccu.constraint_schema = tc.constraint_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND tc.table_schema IN ({schema_placeholders})
            ORDER BY tc.table_schema, tc.table_name, kcu.ordinal_position
            """,
            schema_params,
        )
        result = cursor.fetchall()

        foreign_keys_by_table: dict[str, list[tuple[str, str, str]]] = collections.defaultdict(list)
        discovered_pairs_by_schema_and_table = {
            (schema_name, table_name): display_name
            for display_name, (_source_catalog, schema_name, table_name) in discovered_tables.items()
        }
        for (
            source_schema_name,
            table_name,
            column_name,
            target_schema_name,
            target_table_name,
            target_column_name,
        ) in result:
            display_name = discovered_pairs_by_schema_and_table.get((source_schema_name, table_name))
            if display_name is None:
                continue

            target_display_name = _get_display_table_name(
                target_schema_name,
                target_table_name,
                qualify_with_schema=qualify_with_schema or target_schema_name != source_schema_name,
            )
            foreign_keys_by_table[display_name].append((column_name, target_display_name, target_column_name))

        return foreign_keys_by_table


def get_foreign_keys(
    host: str,
    database: str,
    user: str,
    password: str,
    schema: str | None,
    port: int,
    require_ssl: bool = False,
    names: list[str] | None = None,
) -> dict[str, list[tuple[str, str, str]]]:
    """Get foreign keys for tables in the selected PostgreSQL schema."""
    with pg_connection(
        host=host, port=port, database=database, user=user, password=password, require_ssl=require_ssl
    ) as connection:
        return _foreign_keys_from_conn(connection, schema, names)


def get_connection_metadata(
    host: str,
    database: str,
    user: str,
    password: str,
    port: int,
    require_ssl: bool = False,
) -> dict[str, Any]:
    with pg_connection(
        host=host, port=port, database=database, user=user, password=password, require_ssl=require_ssl
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database(), version()")
            row = cursor.fetchone()
            current_database = str(row[0]) if row and row[0] is not None else database
            version = str(row[1]) if row and row[1] is not None else ""
            is_duckdb = "duckdb" in version.lower() or "duckgres" in version.lower()

            function_source = "duckdb_functions" if is_duckdb else "pg_proc"
            available_functions: list[str] = []
            available_table_functions: list[str] = []

            try:
                if is_duckdb:
                    cursor.execute("SELECT DISTINCT function_name FROM duckdb_functions()")
                else:
                    cursor.execute("SELECT DISTINCT proname FROM pg_proc WHERE pg_function_is_visible(oid)")
                available_functions = _normalize_function_names([row[0] for row in cursor.fetchall()])
            except Exception as error:
                capture_exception(error)

            try:
                if is_duckdb:
                    cursor.execute(
                        "SELECT DISTINCT function_name FROM duckdb_functions() WHERE function_type = 'table'"
                    )
                else:
                    # prokind='f' excludes aggregates/windows/procedures; proretset=true selects set-returning fns,
                    # which is how Postgres exposes table functions in pg_proc.
                    cursor.execute(
                        "SELECT DISTINCT proname FROM pg_proc "
                        "WHERE pg_function_is_visible(oid) AND proretset = true AND prokind = 'f'"
                    )
                available_table_functions = _normalize_function_names([row[0] for row in cursor.fetchall()])
            except Exception as error:
                capture_exception(error)

            available_functions = [fn for fn in available_functions if not is_dangerous_table_function(fn)]
            available_table_functions = [fn for fn in available_table_functions if not is_dangerous_table_function(fn)]

            return {
                "database": current_database,
                "version": version,
                "engine": "duckdb" if is_duckdb else "postgres",
                "function_source": function_source,
                "available_functions": available_functions,
                "available_table_functions": available_table_functions,
            }


class JsonAsStringLoader(Loader):
    def load(self, data):
        if data is None:
            return None
        return bytes(data).decode("utf-8")


class RangeAsStringLoader(Loader):
    """Load PostgreSQL range types as their string representation.

    We currently do not support range types. So, for now, the best we can do is
    convert them to `str`. For example, instead of loading a
    `psycopg.types.range.Range(4, 5, '[)')`, we will load `str` "[4,5)".

    Keep in mind that a single range can have multiple possible string
    representations. For example, `psycopg.types.range.Range(4, 5, '[]')` could
    be represented as "[4,5]" or "[4,6)". We let `psycopg` figure which string
    representation to use (from testing, it seems that the latter is preferred).
    """

    def load(self, data):
        if data is None:
            return None
        return bytes(data).decode("utf-8")


class SafeDateLoader(Loader):
    """Load PostgreSQL dates, handling edge cases beyond Python's date range.

    PostgreSQL can store dates beyond Python's datetime.date limits (year 1 to
    year 9999). This includes 'infinity', '-infinity', and dates in years > 9999.
    When encountering such dates, we clamp to Python's date limits rather than
    raising an error.
    """

    def load(self, data) -> date | None:
        if data is None:
            return None

        s = bytes(data).decode("utf-8")

        if s in ("infinity", "-infinity"):
            return date.max if s == "infinity" else date.min

        # Handle negative years (BC dates)
        if s.startswith("-") or "bc" in s.lower():
            return date.min

        try:
            parts = s.split("-")
            if len(parts) == 3:
                year = int(parts[0])
                month = int(parts[1])
                day = int(parts[2])

                if year > 9999:
                    return date.max
                if year < 1:
                    return date.min

                return date(year, month, day)
        except (ValueError, IndexError):
            pass

        # Fallback: clamp to max for unparseable dates
        return date.max


def _clamp_out_of_range_timestamp(data, *, tzinfo: timezone | None) -> datetime:
    """Map a Postgres timestamp value outside Python's datetime range onto datetime.min/max.

    PostgreSQL timestamps span years 4713 BC to 294276 AD and include 'infinity'/'-infinity',
    far wider than Python's datetime (year 1 to 9999). We pick the boundary by sign so values
    'before year 1' (BC dates, '-infinity', negative years) clamp low and everything else
    clamps high. `tzinfo` keeps the result aware/naive to match the column's Arrow type.
    """
    s = bytes(data).decode("utf-8", "replace").strip().lower()
    if s == "-infinity" or s.startswith("-") or "bc" in s:
        return datetime.min.replace(tzinfo=tzinfo)
    return datetime.max.replace(tzinfo=tzinfo)


class SafeTimestampLoader(TimestampLoader):
    """Load PostgreSQL timestamps, handling values beyond Python's datetime range.

    psycopg's default loader raises `DataError` on timestamps outside Python's datetime
    range (years > 9999, 'infinity'/'-infinity'), which aborts the whole table sync. We
    defer to the default loader for in-range values and clamp the rest, mirroring
    `SafeDateLoader`. `timestamp` columns map to a naive Arrow type, so the clamp stays naive.
    """

    # psycopg short-circuits SQL NULL before the loader, so `data` is never None in practice;
    # the guard mirrors SafeDateLoader's defensive parity, hence the widened return + override ignore.
    def load(self, data) -> datetime | None:  # type: ignore[override]
        if data is None:
            return None
        try:
            return super().load(data)
        except psycopg.DataError:
            return _clamp_out_of_range_timestamp(data, tzinfo=None)


class SafeTimestamptzLoader(TimestamptzLoader):
    """`timestamptz` counterpart of `SafeTimestampLoader` (see its docstring).

    `timestamptz` columns map to a UTC-aware Arrow type, so the clamp is made tz-aware to
    avoid mixing naive and aware datetimes in the same Arrow column.
    """

    # See SafeTimestampLoader.load for why the override is widened/ignored.
    def load(self, data) -> datetime | None:  # type: ignore[override]
        if data is None:
            return None
        try:
            return super().load(data)
        except psycopg.DataError:
            return _clamp_out_of_range_timestamp(data, tzinfo=UTC)


def _clamp_pg_hour_24(data) -> bytes | None:
    """Clamp a Postgres '24:00:00' time/timetz value to the max Python time.

    PostgreSQL accepts '24:00:00' as the maximum value for the `time` and
    `timetz` types (end-of-day midnight), but Python's datetime.time caps the
    hour at 23. The time portion of an hour-24 value is always exactly
    '24:00:00', so we return an equivalent buffer with the time clamped to the
    maximum representable value, preserving any timezone suffix. Returns None
    for any value that is not an hour-24 time, so callers re-raise as usual.
    """
    s = bytes(data).decode("utf-8")
    if not s.startswith("24:"):
        return None
    rest = s[len("24:00:00") :]
    tz_suffix = ""
    for i, ch in enumerate(rest):
        if ch in "+-":
            tz_suffix = rest[i:]
            break
    return ("23:59:59.999999" + tz_suffix).encode("utf-8")


def _load_time_clamping_hour_24(super_load: Callable[[Any], datetime_time], data) -> datetime_time:
    """Run psycopg's default time loader, clamping the '24:00:00' edge case.

    Mirrors SafeDateLoader's clamp-to-max behaviour: a Postgres end-of-day
    '24:00:00' (which Python's datetime.time cannot represent) is clamped to
    time.max, while every other value — and any genuine parse error — is
    delegated to psycopg's default loader.
    """
    try:
        return super_load(data)
    except psycopg.DataError:
        clamped = _clamp_pg_hour_24(data)
        if clamped is None:
            raise
        return super_load(clamped)


class SafeTimeLoader(TimeLoader):
    """Load PostgreSQL `time` values, clamping the '24:00:00' edge case."""

    def load(self, data) -> datetime_time:
        return _load_time_clamping_hour_24(super().load, data)


class SafeTimetzLoader(TimetzLoader):
    """Load PostgreSQL `timetz` values, clamping '24:00:00' while preserving the timezone offset."""

    def load(self, data) -> datetime_time:
        return _load_time_clamping_hour_24(super().load, data)


@dataclasses.dataclass
class XminBounds:
    """Bounded xmin window captured once at sync start (see §2.2/§2.3 of the design).

    `lower`/`upper` are bare 32-bit xids compared against tuple `xmin`. `ceiling_xid8` is the
    full 64-bit `pg_snapshot_xmin` we persist as the durable, wraparound-safe cursor; `num_wraparound`
    is its epoch (high 32 bits). `wraparound_or_range` selects the single-wrap `>= lower OR < upper`
    predicate instead of the steady-state `>= lower AND < upper`.
    """

    lower: int
    upper: int
    ceiling_xid8: int
    num_wraparound: int
    wraparound_or_range: bool


def _capture_xmin_ceiling(
    cursor: psycopg.Cursor,
    stored_last_value: Optional[int],
    stored_num_wraparound: Optional[int],
    logger: FilteringBoundLogger,
) -> XminBounds:
    """Capture this run's xmin ceiling on the row-serving connection and derive the read window.

    The ceiling is `pg_snapshot_xmin(pg_current_snapshot())` — the lowest still-running xid — so
    every row with `xmin < ceiling` is committed as of the snapshot and in-flight transactions are
    excluded. Must run on the connection that serves rows (a replica's snapshot xmin lags the
    primary's), which is the autocommit setup cursor here.
    """
    server_version = cursor.connection.info.server_version
    if server_version < XMIN_MIN_SERVER_VERSION:
        raise XminUnsupportedError(
            f"xmin replication requires PostgreSQL 13 or newer (server reports {server_version}). "
            "Choose a different sync type for this table."
        )

    cursor.execute(sql.SQL("SELECT pg_snapshot_xmin(pg_current_snapshot())::text::bigint"))
    row = cursor.fetchone()
    if row is None or row[0] is None:
        raise XminUnsupportedError("Could not read the xmin snapshot ceiling from the source database.")
    ceiling_xid8 = int(row[0])
    ceiling_xid = ceiling_xid8 & 0xFFFFFFFF
    num_wraparound = ceiling_xid8 >> 32

    # First run (no stored cursor): read everything `< ceiling` once. `lower = 0` is below
    # FrozenTransactionId (2) so even frozen tuples are captured by the initial snapshot.
    if stored_last_value is None:
        return XminBounds(
            lower=0,
            upper=ceiling_xid,
            ceiling_xid8=ceiling_xid8,
            num_wraparound=num_wraparound,
            wraparound_or_range=False,
        )

    delta = num_wraparound - (stored_num_wraparound or 0)
    if delta == 0:
        return XminBounds(
            lower=int(stored_last_value),
            upper=ceiling_xid,
            ceiling_xid8=ceiling_xid8,
            num_wraparound=num_wraparound,
            wraparound_or_range=False,
        )
    if delta == 1:
        # Single wrap: changed rows split into `>= old_lower OR < new_upper`.
        return XminBounds(
            lower=int(stored_last_value),
            upper=ceiling_xid,
            ceiling_xid8=ceiling_xid8,
            num_wraparound=num_wraparound,
            wraparound_or_range=True,
        )
    # delta >= 2 (or a negative epoch drift): too much churn to reconstruct safely — force a full
    # re-read of everything `< ceiling`.
    logger.warning(
        f"xmin epoch advanced by {delta} since the last sync (stored={stored_num_wraparound}, "
        f"current={num_wraparound}); forcing a full re-read."
    )
    return XminBounds(
        lower=0, upper=ceiling_xid, ceiling_xid8=ceiling_xid8, num_wraparound=num_wraparound, wraparound_or_range=False
    )


def _build_query(
    schema: str,
    table_name: str,
    should_use_incremental_field: bool,
    table_type: Literal["table", "view", "materialized_view"] | None,
    incremental_field: Optional[str],
    incremental_field_type: Optional[IncrementalFieldType],
    db_incremental_field_last_value: Optional[Any],
    add_sampling: Optional[bool] = False,
    *,
    upper_bound_inclusive: Optional[Any] = None,
    enabled_columns: Optional[list[str]] = None,
    primary_keys: Optional[list[str]] = None,
    row_filters: Optional[list[ValidatedRowFilter]] = None,
    xmin_bounds: Optional[XminBounds] = None,
) -> sql.Composed:
    projected = compute_projected_columns(enabled_columns, primary_keys, incremental_field)
    select_clause: sql.Composable = (
        sql.SQL("*") if projected is None else sql.SQL(", ").join(sql.Identifier(c) for c in projected)
    )
    # Row filters apply only to the real data path; sampling/row-count queries stay unfiltered
    # (an over-estimate is harmless).
    row_filter_conditions = render_psycopg_row_filter_conditions(row_filters or [])

    if xmin_bounds is not None:
        return _build_xmin_query(
            schema, table_name, select_clause, xmin_bounds, row_filter_conditions, add_sampling=bool(add_sampling)
        )

    if not should_use_incremental_field:
        if add_sampling:
            if table_type == "view":
                query = sql.SQL("SELECT {cols} FROM {table} WHERE random() < 0.01").format(
                    cols=select_clause, table=sql.Identifier(schema, table_name)
                )
            else:
                query = sql.SQL("SELECT {cols} FROM {table} TABLESAMPLE SYSTEM (1)").format(
                    cols=select_clause, table=sql.Identifier(schema, table_name)
                )
            return query + sql.SQL(" LIMIT 1000")

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

    # Use the type-aware operator (`>=` for Date) only for single-shot scans. Windowed
    # scans (upper_bound_inclusive set) must keep `>` because consecutive windows use the
    # previous window's hi as the next window's lo — `>=` would re-fetch every row at the
    # boundary value, duplicating each window's hi inside a single run.
    operator = (
        sql.SQL(incremental_type_to_operator(incremental_field_type)) if upper_bound_inclusive is None else sql.SQL(">")
    )

    if add_sampling:
        if table_type == "view":
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
        else:
            query = sql.SQL(
                "SELECT {cols} FROM {schema}.{table} TABLESAMPLE SYSTEM (1) WHERE {incremental_field} {op} {last_value}"
            ).format(
                cols=select_clause,
                schema=sql.Identifier(schema),
                table=sql.Identifier(table_name),
                incremental_field=sql.Identifier(incremental_field),
                op=operator,
                last_value=sql.Literal(db_incremental_field_last_value),
            )
    else:
        query = sql.SQL("SELECT {cols} FROM {schema}.{table} WHERE {incremental_field} {op} {last_value}").format(
            cols=select_clause,
            schema=sql.Identifier(schema),
            table=sql.Identifier(table_name),
            incremental_field=sql.Identifier(incremental_field),
            op=operator,
            last_value=sql.Literal(db_incremental_field_last_value),
        )

    if add_sampling:
        return query + sql.SQL(" LIMIT 1000")

    if upper_bound_inclusive is not None:
        query = sql.SQL("{inner} AND {field} <= {upper}").format(
            inner=query,
            field=sql.Identifier(incremental_field),
            upper=sql.Literal(upper_bound_inclusive),
        )

    if row_filter_conditions:
        query = query + sql.SQL(" AND ") + and_join(row_filter_conditions)

    return query + sql.SQL(" ORDER BY {field} ASC").format(field=sql.Identifier(incremental_field))


def _xmin_predicate(bounds: XminBounds) -> sql.Composed:
    """Bounded predicate over the cast `xmin` (no ordering operators exist on raw `xid`)."""
    xmin_expr = sql.SQL("xmin::text::bigint")
    if bounds.wraparound_or_range:
        return sql.SQL("({xmin} >= {lo} OR {xmin} < {hi})").format(
            xmin=xmin_expr, lo=sql.Literal(bounds.lower), hi=sql.Literal(bounds.upper)
        )
    return sql.SQL("({xmin} >= {lo} AND {xmin} < {hi})").format(
        xmin=xmin_expr, lo=sql.Literal(bounds.lower), hi=sql.Literal(bounds.upper)
    )


def _build_xmin_query(
    schema: str,
    table_name: str,
    select_clause: sql.Composable,
    bounds: XminBounds,
    row_filter_conditions: list[sql.Composable],
    *,
    add_sampling: bool,
) -> sql.Composed:
    # `_ph_xmin` is force-projected (system columns never come back from `SELECT *`) and kept out of
    # `compute_projected_columns` so it can't collide with the user's incremental-field machinery.
    select = sql.SQL("xmin::text::bigint AS {alias}, {cols}").format(
        alias=sql.Identifier(XMIN_PROJECTED_COLUMN), cols=select_clause
    )
    query = sql.SQL("SELECT {cols} FROM {table} WHERE {predicate}").format(
        cols=select, table=sql.Identifier(schema, table_name), predicate=_xmin_predicate(bounds)
    )
    if row_filter_conditions:
        query = query + sql.SQL(" AND ") + and_join(row_filter_conditions)

    # ORDER BY the cast cursor so the offset-resume path stays correct on a connection drop.
    ordered = query + sql.SQL(" ORDER BY xmin::text::bigint ASC")
    if add_sampling:
        return ordered + sql.SQL(" LIMIT 1000")
    return ordered


def _build_count_query(
    schema: str,
    table_name: str,
    should_use_incremental_field: bool,
    incremental_field: Optional[str],
    incremental_field_type: Optional[IncrementalFieldType],
    db_incremental_field_last_value: Optional[Any],
    xmin_bounds: Optional[XminBounds] = None,
) -> sql.Composed:
    if xmin_bounds is not None:
        return sql.SQL("SELECT COUNT(*) FROM {schema}.{table} WHERE {predicate}").format(
            schema=sql.Identifier(schema),
            table=sql.Identifier(table_name),
            predicate=_xmin_predicate(xmin_bounds),
        )

    if not should_use_incremental_field:
        return sql.SQL("SELECT COUNT(*) FROM {schema}.{table}").format(
            schema=sql.Identifier(schema),
            table=sql.Identifier(table_name),
        )

    if incremental_field is None or incremental_field_type is None:
        raise ValueError("incremental_field and incremental_field_type can't be None")

    if db_incremental_field_last_value is None:
        db_incremental_field_last_value = incremental_type_to_initial_value(incremental_field_type)

    operator = sql.SQL(incremental_type_to_operator(incremental_field_type))
    return sql.SQL("SELECT COUNT(*) FROM {schema}.{table} WHERE {incremental_field} {op} {last_value}").format(
        schema=sql.Identifier(schema),
        table=sql.Identifier(table_name),
        incremental_field=sql.Identifier(incremental_field),
        op=operator,
        last_value=sql.Literal(db_incremental_field_last_value),
    )


def _explain_query(cursor: psycopg.Cursor, query: sql.Composed, logger: FilteringBoundLogger):
    logger.debug(f"Running EXPLAIN on {query.as_string()}")

    try:
        # Debug-only, best-effort: EXPLAIN may use syntax the source rejects (e.g. TABLESAMPLE
        # on CockroachDB), so swallow failures.
        query_with_explain = sql.SQL("EXPLAIN {}").format(query)
        cursor.execute(query_with_explain)
        rows = cursor.fetchall()
        explain_result: str = ""
        # Build up a single string of the EXPLAIN output
        for row in rows:
            for col in row:
                explain_result += f"\n{col}"
        logger.debug(f"EXPLAIN result: {explain_result}")
    except Exception as e:
        logger.debug(f"EXPLAIN raised an exception: {e}")


def _get_primary_keys(
    cursor: psycopg.Cursor, schema: str, table_name: str, logger: FilteringBoundLogger
) -> list[str] | None:
    # Uses pg_catalog rather than information_schema because information_schema views
    # are ACL-filtered — a user with only SELECT grants may not see PK constraint rows
    # depending on PostgreSQL version, which silently returned no primary key at sync
    # time even though discovery (which already uses pg_catalog) found one.
    pg_catalog_query = sql.SQL("""
        SELECT a.attname AS column_name
        FROM pg_index i
        JOIN pg_class c ON c.oid = i.indrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = ANY(i.indkey)
        WHERE i.indisprimary
          AND n.nspname = {schema}
          AND c.relname = {table}
        ORDER BY array_position(i.indkey, a.attnum)
    """).format(schema=sql.Literal(schema), table=sql.Literal(table_name))

    _explain_query(cursor, pg_catalog_query, logger)
    logger.debug(f"Running query: {pg_catalog_query.as_string()}")
    cursor.execute(pg_catalog_query)
    rows = cursor.fetchall()
    if len(rows) > 0:
        return [row[0] for row in rows]

    # Some partitioned setups define PKs on child partitions only.
    # In that case, infer PK columns from children if they are consistent.
    child_partition_pk_query = sql.SQL("""
        SELECT
            child_cls.relname AS child_table_name,
            att.attname AS pk_column_name,
            conkey.ordinality AS pk_ordinality
        FROM
            pg_catalog.pg_class parent_cls
        JOIN
            pg_catalog.pg_namespace parent_nsp
            ON parent_nsp.oid = parent_cls.relnamespace
        JOIN
            pg_catalog.pg_inherits inh
            ON inh.inhparent = parent_cls.oid
        JOIN
            pg_catalog.pg_class child_cls
            ON child_cls.oid = inh.inhrelid
        JOIN
            pg_catalog.pg_constraint con
            ON con.conrelid = child_cls.oid
            AND con.contype = 'p'
        JOIN LATERAL
            unnest(con.conkey) WITH ORDINALITY AS conkey(attnum, ordinality)
            ON TRUE
        JOIN
            pg_catalog.pg_attribute att
            ON att.attrelid = child_cls.oid
            AND att.attnum = conkey.attnum
        WHERE
            parent_nsp.nspname = {schema}
            AND parent_cls.relname = {table}
        ORDER BY
            child_cls.relname,
            conkey.ordinality
    """).format(schema=sql.Literal(schema), table=sql.Literal(table_name))
    child_pk_rows: list[tuple[str, str, int]] = []
    try:
        _explain_query(cursor, child_partition_pk_query, logger)
        logger.debug(f"Running child-partition fallback query: {child_partition_pk_query.as_string()}")
        cursor.execute(child_partition_pk_query)
        child_pk_rows = cursor.fetchall()
    except Exception as e:
        # A transient connection drop here means the fallback never ran — swallowing it would
        # capture noise and wrongly report "no primary key" off a dead cursor. Re-raise so the
        # setup retry loop reconnects (mirrors the unwrapped primary query above and the
        # duplicate-PK probe). Genuine query-incompatibility errors (e.g. an engine that can't
        # bind this pg_catalog query) still degrade to best-effort.
        if _is_connection_dropped_error(e):
            raise
        capture_exception(e)
        logger.warning(f"Child-partition fallback query failed for {table_name}: {e}")
    if len(child_pk_rows) > 0:
        child_pks: dict[str, list[str]] = {}
        for child_table_name, pk_column_name, _ in child_pk_rows:
            child_pks.setdefault(child_table_name, []).append(pk_column_name)

        unique_pk_sets = {tuple(pk_cols) for pk_cols in child_pks.values()}
        if len(unique_pk_sets) == 1:
            inferred_primary_keys = list(next(iter(unique_pk_sets)))
            logger.debug(f"Found primary keys for {table_name} via child partitions fallback: {inferred_primary_keys}")
            return inferred_primary_keys

        logger.warning(
            f"Found inconsistent child partition primary keys for {table_name}: {child_pks}. Could not infer a stable key for parent."
        )
        return None

    logger.warning(
        f"No primary keys found for {table_name}. If the table is not a view, does the table have a primary key set?"
    )

    return None


def _has_duplicate_primary_keys(
    cursor: psycopg.Cursor, schema: str, table_name: str, primary_keys: list[str] | None, logger: FilteringBoundLogger
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
            *[sql.Identifier(key) for key in primary_keys], sql.Identifier(schema), sql.Identifier(table_name)
        )
        _explain_query(cursor, query, logger)
        logger.debug(f"Running query: {query.as_string()}")
        cursor.execute(query)
        row = cursor.fetchone()

        return row is not None
    except psycopg.errors.QueryCanceled:
        raise
    except psycopg.OperationalError:
        # A connection-level failure here (e.g. a foreign-data-wrapper server refusing a new
        # connection with "too many connections") means the probe never ran — swallowing it as
        # "no duplicate keys" would be a false negative. Propagate it so the activity's retry
        # path handles it; these are transient and stay retryable.
        raise
    except Exception as e:
        capture_exception(e)
        return False


def _get_table_chunk_size(cursor: psycopg.Cursor, inner_query: sql.Composed, logger: FilteringBoundLogger) -> int:
    # Under autocommit each statement is its own transaction — a failure can't poison
    # subsequent commands, so no SAVEPOINT is needed. When called inside a shared
    # transaction (e.g. tests or future callers), wrap in a SAVEPOINT so that a
    # QueryCanceled doesn't abort the surrounding transaction.
    use_savepoint = not cursor.connection.autocommit
    savepoint_active = False
    try:
        if use_savepoint:
            cursor.execute("SAVEPOINT _chunk_size_probe")
            savepoint_active = True

        query = sql.SQL("""
            SELECT percentile_cont(0.95) within group (order by subquery.row_size) FROM (
                SELECT octet_length(t::text) as row_size FROM ({}) as t
            ) as subquery
        """).format(inner_query)

        # Best-effort: the sampled query can fail (e.g. TABLESAMPLE on CockroachDB); fall back.
        _explain_query(cursor, query, logger)
        logger.debug(f"Running query: {query.as_string()}")
        cursor.execute(query)
        row = cursor.fetchone()

        if savepoint_active:
            cursor.execute("RELEASE SAVEPOINT _chunk_size_probe")
            savepoint_active = False

        if row is None:
            logger.debug(f"_get_table_chunk_size: No results returned. Using DEFAULT_CHUNK_SIZE={DEFAULT_CHUNK_SIZE}")
            chunk_size = DEFAULT_CHUNK_SIZE
        else:
            row_size_bytes = row[0] or 1
            chunk_size = int(DEFAULT_TABLE_SIZE_BYTES / row_size_bytes)
            logger.debug(
                f"_get_table_chunk_size: row_size_bytes={row_size_bytes}. DEFAULT_TABLE_SIZE_BYTES={DEFAULT_TABLE_SIZE_BYTES}. Using CHUNK_SIZE={chunk_size}"
            )

        return chunk_size
    except Exception as e:
        # Best-effort: any failure (including a statement_timeout / QueryCanceled) falls back to
        # DEFAULT_CHUNK_SIZE. The estimation query wraps the sample in `octet_length(t::text)`,
        # which serializes every column to text and so evaluates generated columns and check/domain
        # validator functions — making it strictly more expensive than the real chunked `SELECT *`
        # extraction. A timeout here therefore says nothing about whether extraction will succeed,
        # and the savepoint (when present) keeps the connection usable. The streaming read loop has
        # its own dedicated QueryCanceled handling (`_statement_timeout_as_non_retryable`), so
        # re-raising the cancellation here would only bypass that path and leak a raw, retryable
        # QueryCanceled that Temporal re-attempts forever on tables this query can never complete on.
        if savepoint_active:
            try:
                cursor.execute("ROLLBACK TO SAVEPOINT _chunk_size_probe")
                cursor.execute("RELEASE SAVEPOINT _chunk_size_probe")
            except Exception as rollback_error:
                logger.debug(f"_get_table_chunk_size: Failed to rollback savepoint: {rollback_error}")
        logger.debug(f"_get_table_chunk_size: Error: {e}. Using DEFAULT_CHUNK_SIZE={DEFAULT_CHUNK_SIZE}", exc_info=e)

        return DEFAULT_CHUNK_SIZE


def _role_subject_to_rls(cursor: psycopg.Cursor, schema: str, table_name: str, logger: FilteringBoundLogger) -> bool:
    """Whether row-level security is active for the connecting role on this table."""
    try:
        query = sql.SQL("""
            SELECT row_security_active(c.oid)
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = {schema} AND c.relname = {table}
        """).format(schema=sql.Literal(schema), table=sql.Literal(table_name))
        cursor.execute(query)
        row = cursor.fetchone()
        return bool(row and row[0])
    except psycopg.errors.QueryCanceled:
        raise
    except Exception as e:
        logger.debug(f"_role_subject_to_rls: Error: {e}", exc_info=e)
        return False


def _get_rows_to_sync(
    cursor: psycopg.Cursor,
    count_query: sql.Composed,
    logger: FilteringBoundLogger,
    *,
    should_use_incremental_field: bool = False,
) -> int:
    try:
        _explain_query(cursor, count_query, logger)
        logger.debug(f"Running query: {count_query.as_string()}")
        cursor.execute(count_query)
        row = cursor.fetchone()

        if row is None:
            logger.debug(f"_get_rows_to_sync: No results returned. Using 0 as rows to sync")
            return 0

        rows_to_sync = row[0] or 0
        rows_to_sync_int = int(rows_to_sync)

        logger.debug(f"_get_rows_to_sync: rows_to_sync_int={rows_to_sync_int}")

        return int(rows_to_sync)
    except psycopg.errors.QueryCanceled as e:
        # QueryCanceled means the COUNT was cancelled — usually the statement_timeout, but possibly a
        # lock_timeout or an admin cancel (we don't inspect which). On incremental syncs re-raise:
        # this COUNT shares its WHERE with the real chunked read, so a cancellation here predicts the
        # extraction will hit the same wall — the caller maps it to the actionable "add an index on
        # your incremental field" message. On full-table syncs the COUNT is a full scan while
        # extraction streams sequentially via a server cursor, so a cancelled count says nothing
        # about whether extraction will succeed. Fall back to an unknown total (0) like the sibling
        # `_get_table_chunk_size` probe rather than failing the whole sync at setup on a best-effort
        # estimate.
        if should_use_incremental_field:
            raise
        logger.debug(f"_get_rows_to_sync: COUNT cancelled on a full-table sync ({e}). Using 0 as rows to sync")
        return 0
    except Exception as e:
        # This COUNT(*) is a best-effort estimate for progress reporting and partition sizing.
        # It shares its FROM/WHERE with the real extraction query, so any genuine problem
        # (missing column, unpopulated materialized view, permissions, bad incremental field)
        # resurfaces there and is classified through the normal retryable/non-retryable path.
        # Capturing it here too would only flood error tracking with handled duplicates of
        # user/upstream conditions we already tolerate, so we log at debug and fall back to 0.
        logger.debug(f"_get_rows_to_sync: Error: {e}. Using 0 as rows to sync", exc_info=e)

        if "temporary file size exceeds temp_file_limit" in str(e):
            raise TemporaryFileSizeExceedsLimitException(
                f"Error: {e}. Please ensure your incremental field has an appropriate index created"
            )

        return 0


def _get_partition_settings(
    cursor: psycopg.Cursor,
    schema: str,
    table_name: str,
    logger: FilteringBoundLogger,
    *,
    is_partitioned: bool | None = None,
) -> PartitionSettings | None:
    # For partitioned tables, a plain COUNT(*) and pg_table_size on the
    # parent would scan every child partition / return 0. Use catalog
    # estimates instead.
    try:
        # Reuse the caller's partition flag when given; saves a redundant catalog round trip.
        if is_partitioned is None:
            is_partitioned = _is_partitioned_table(cursor, schema, table_name)
        if is_partitioned:
            return _get_partition_settings_for_partitioned_table(cursor, schema, table_name, logger)
    except Exception as e:
        logger.debug(f"_get_partition_settings: partition detection failed, falling back: {e}")

    query = sql.SQL("""
        SELECT
            CASE WHEN count(*) = 0 OR pg_table_size({schema_table_name_literal}) = 0 THEN NULL
            ELSE round({bytes_per_partition} / (pg_table_size({schema_table_name_literal}) / count(*))) END,
            COUNT(*)
        FROM {schema}.{table}""").format(
        bytes_per_partition=sql.Literal(DEFAULT_PARTITION_TARGET_SIZE_IN_BYTES),
        schema_table_name_literal=sql.Literal(f'{schema}."{table_name}"'),
        schema=sql.Identifier(schema),
        table=sql.Identifier(table_name),
    )

    try:
        _explain_query(cursor, query, logger)
        logger.debug(f"Running query: {query.as_string()}")
        cursor.execute(query)
    except psycopg.errors.QueryCanceled:
        raise
    except psycopg.errors.UndefinedTable as e:
        # The selected table was dropped or renamed in the source between schema discovery and
        # this best-effort partition-sizing probe. That's a user/upstream condition we already
        # tolerate here (return None -> no partitioning), and the real extraction query — which
        # shares this FROM clause — hits the same missing relation and surfaces it through the
        # normal non-retryable path ("does not exist"). Capturing it here too would only flood
        # error tracking with handled duplicates, so mirror `_get_rows_to_sync` and log at debug.
        logger.debug(f"_get_partition_settings: table does not exist, returning None: {e}")
        return None
    except Exception as e:
        # Partition sizing is a best-effort optimization: returning None just falls back to
        # default partition settings and the sync proceeds. This query shares its FROM with the
        # real extraction query, so any genuine problem (missing table, permissions, upstream
        # extension state, read-replica recovery conflict, or an earlier best-effort query in this
        # same transaction having left it `InFailedSqlTransaction`) resurfaces there and is
        # classified through the normal retryable/non-retryable path. Capturing it here too only
        # floods error tracking with handled duplicates of user/upstream conditions we already
        # tolerate, so log at debug and fall back — mirroring `_get_rows_to_sync`.
        logger.debug(f"_get_partition_settings: returning None due to error: {e}", exc_info=e)

        if "temporary file size exceeds temp_file_limit" in str(e):
            raise TemporaryFileSizeExceedsLimitException(
                f"Error: {e}. Please ensure your incremental field has an appropriate index created"
            )

        return None

    result = cursor.fetchone()

    if result is None or len(result) == 0 or result[0] is None:
        logger.debug(f"_get_partition_settings: query result is None, returning None")
        return None

    partition_size = int(result[0])
    total_rows = int(result[1])
    partition_count = math.floor(total_rows / partition_size)

    if partition_count == 0:
        logger.debug(f"_get_partition_settings: partition_count=1, partition_size={partition_size}")
        return PartitionSettings(partition_count=1, partition_size=partition_size)

    logger.debug(f"_get_partition_settings: partition_count={partition_count}, partition_size={partition_size}")
    return PartitionSettings(partition_count=partition_count, partition_size=partition_size)


class PostgreSQLColumn(Column):
    """Implementation of the `Column` protocol for a PostgreSQL source.

    Attributes:
        name: The column's name.
        data_type: The name of the column's data type as described in
            https://www.postgresql.org/docs/current/datatype.html.
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

        match self.data_type.lower():
            case "bigint":
                arrow_type = pa.int64()
            case "integer":
                arrow_type = pa.int32()
            case "smallint":
                arrow_type = pa.int16()
            case "numeric" | "decimal":
                # Use `is None` for the scale half of the guard so that legitimate `NUMERIC(X, 0)`
                # columns (integer-valued numerics, scale == 0) are not mistakenly treated as
                # "missing scale". Precision still uses a truthiness check — precision == 0 is a
                # real pathology (zero-digit budget) and should keep raising from our layer.
                if not self.numeric_precision or self.numeric_scale is None:
                    raise TypeError("expected `numeric_precision` and `numeric_scale` to be `int`, got `NoneType`")

                arrow_type = build_pyarrow_decimal_type(self.numeric_precision, self.numeric_scale)
            case "real":
                arrow_type = pa.float32()
            case "double precision":
                arrow_type = pa.float64()
            case "text" | "varchar" | "character varying":
                arrow_type = pa.string()
            case "date":
                arrow_type = pa.date32()
            case "time" | "time without time zone":
                arrow_type = pa.time64("us")
            case "timestamp" | "timestamp without time zone":
                arrow_type = pa.timestamp("us")
            case "timestamptz" | "timestamp with time zone":
                arrow_type = pa.timestamp("us", tz="UTC")
            case "interval":
                arrow_type = pa.duration("us")
            case "boolean":
                arrow_type = pa.bool_()
            case "bytea":
                arrow_type = pa.binary()
            case "uuid":
                arrow_type = pa.string()
            case "json" | "jsonb":
                arrow_type = pa.string()
            case _ if self.data_type.endswith("[]"):  # Array types
                arrow_type = pa.string()
            case _:
                arrow_type = pa.string()

        return pa.field(self.name, arrow_type, nullable=self.nullable)


def _is_read_replica(cursor: psycopg.Cursor) -> bool:
    cursor.execute("SELECT pg_is_in_recovery()")
    row = cursor.fetchone()
    if row is None:
        return False

    return row[0] is True


def _get_table(
    cursor: psycopg.Cursor,
    schema: str,
    table_name: str,
    logger: FilteringBoundLogger,
    probe_unconstrained_numeric_scale: bool = False,
) -> Table[PostgreSQLColumn]:
    """Read column metadata for `schema.table_name`.

    If `probe_unconstrained_numeric_scale` is True, additionally run a `MAX(scale(col))`
    aggregation on unconstrained `numeric` columns (those declared as `numeric` with no
    precision/scale) to pick a source arrow decimal scale that matches the real data.

    The probe is only useful when a fresh delta column is about to be created — either a
    first-ever sync or a post-reset sync with a cleared incremental watermark — because delta
    decimal column types are immutable after creation. On normal incremental syncs the delta
    column already exists and the probed value is discarded, so the caller should gate
    probing on "is a fresh schema being created" (see the equivalent gating on
    `_get_estimated_row_count_for_partitioned_table` in `postgres_source`)."""
    # Raise a generous statement_timeout for the whole discovery phase before issuing any query.
    # The outer 10-minute setup timeout isn't set until `postgres_source` continues after
    # `_get_table` returns, so without this every probe here — the `pg_matviews`/`pg_views` lookups,
    # the metadata SELECT (whose `information_schema.columns` `numeric_*` columns invoke the slow
    # per-column `_pg_numeric_*` functions), and even the `BEGIN` opening a scoping transaction —
    # inherits a short role/server default that some hosted/pooled Postgres set, which cancels the
    # statement with QueryCanceled mid-discovery. Session, not LOCAL: the connection is autocommit,
    # so a LOCAL timeout has nothing to bind to and a scoping transaction's own `BEGIN` would itself
    # run under the short default. Best-effort: engines without statement_timeout (e.g. DuckDB)
    # reject the SET, so clear any aborted transaction and fall back to the default.
    try:
        cursor.execute(
            sql.SQL("SET statement_timeout = {timeout}").format(timeout=sql.Literal(METADATA_STATEMENT_TIMEOUT_MS))
        )
    except psycopg.Error:
        cursor.connection.rollback()

    is_mat_view_query = sql.SQL(
        "select {table} in (select matviewname from pg_matviews where schemaname = {schema}) as res"
    ).format(schema=sql.Literal(schema), table=sql.Literal(table_name))
    is_mat_view_res = cursor.execute(is_mat_view_query).fetchone()
    is_mat_view = is_mat_view_res is not None and is_mat_view_res[0] is True
    is_view = False
    if not is_mat_view:
        is_view_query = sql.SQL(
            "select {table} in (select viewname from pg_views where schemaname = {schema}) as res"
        ).format(schema=sql.Literal(schema), table=sql.Literal(table_name))
        is_view_res = cursor.execute(is_view_query).fetchone()
        is_view = is_view_res is not None and is_view_res[0] is True

    if is_mat_view:
        # Table is a materialised view, column info doesn't exist in information_schema.columns
        query = sql.SQL("""
            SELECT
                a.attname AS column_name,
                pg_catalog.format_type(a.atttypid, a.atttypmod) AS data_type,
                NOT a.attnotnull AS is_nullable,
                CASE
                    WHEN t.typcategory = 'N' THEN
                        CASE
                            WHEN a.atttypmod = -1 THEN NULL
                            ELSE ((a.atttypmod - 4) >> 16) & 65535
                        END
                    ELSE NULL
                END AS numeric_precision,
                CASE
                    WHEN t.typcategory = 'N' THEN
                        CASE
                            WHEN a.atttypmod = -1 THEN NULL
                            ELSE (a.atttypmod - 4) & 65535
                        END
                    ELSE NULL
                END AS numeric_scale
            FROM pg_attribute a
            JOIN pg_class c ON a.attrelid = c.oid
            JOIN pg_namespace n ON c.relnamespace = n.oid
            JOIN pg_type t ON a.atttypid = t.oid
            WHERE c.relname = {table}
            AND n.nspname = {schema}
            AND a.attnum > 0
            AND NOT a.attisdropped""").format(schema=sql.Literal(schema), table=sql.Literal(table_name))
    else:
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
                AND table_name = {table}""").format(schema=sql.Literal(schema), table=sql.Literal(table_name))

    _explain_query(cursor, query, logger)
    logger.debug(f"Running query: {query.as_string()}")
    cursor.execute(query)
    metadata_rows = cursor.fetchall()

    numeric_data_types = {"numeric", "decimal"}

    # For unconstrained numeric columns (declared as `numeric` with no precision/scale),
    # postgres returns NULL for numeric_precision/numeric_scale in information_schema. Falling
    # back to a static default scale (18) causes the delta column to be created with less scale
    # than the actual data requires, which later breaks merges when a chunk contains values with
    # trailing non-zero digits past that default scale. Probe the actual data for its max used
    # scale so the delta column is sized correctly from the start.
    unconstrained_numeric_columns = [
        name
        for name, data_type, _nullable, _np, numeric_scale_candidate in metadata_rows
        if data_type in numeric_data_types and numeric_scale_candidate is None
    ]
    probed_scales: dict[str, int | None] = {}
    # Alongside scale, we also probe the max integer digits per column so we can size precision
    # to cover BOTH dimensions. Freezing the delta column at `decimal128(38, probed_scale)` when
    # the observed data has `int_digits + scale > 38` would cause later arrow casts to fail — the
    # probe alone cannot protect the integer side because precision is hard-capped at 38 for
    # decimal128.
    probed_int_digits: dict[str, int | None] = {}
    # Only probe when a fresh delta column is about to be created. On incremental syncs the
    # delta column type is already set and probing wastes a full-table aggregation per sync.
    # Skip regular views: `MAX(scale(col))` on a view forces the view definition to execute,
    # which can be arbitrarily expensive for join/aggregate views. Materialized views are
    # already materialized on disk and behave like tables here.
    if unconstrained_numeric_columns and probe_unconstrained_numeric_scale and not is_view:
        try:
            # Own transaction so the 30s `SET LOCAL statement_timeout` below scopes to this
            # aggregation and auto-resets (a self-contained BEGIN/COMMIT under autocommit).
            with cursor.connection.transaction():
                # Scope a short statement_timeout to the probe so a pathologically large table
                # or slow aggregation can't hang schema discovery. Without this the probe would
                # inherit the generous discovery-phase timeout set at the top of `_get_table`,
                # which is deliberately too loose for a full-table aggregation.
                cursor.execute(
                    sql.SQL("SET LOCAL statement_timeout = {timeout}").format(
                        timeout=sql.Literal(30 * 1000)  # 30 seconds
                    )
                )
                # `abs(col)` strips the minus sign before `::text` so negative values don't
                # inflate the measured integer-digit count. `trunc` drops the fractional part;
                # the result is always numeric (never scientific notation), so `length(::text)`
                # is the integer-digit count. Pairs: (MAX(scale), MAX(int_digits)) per column,
                # emitted in the same order as `unconstrained_numeric_columns`.
                select_parts = sql.SQL(", ").join(
                    sql.SQL("MAX(scale({col})), MAX(length(trunc(abs({col}))::text))").format(
                        col=sql.Identifier(col_name)
                    )
                    for col_name in unconstrained_numeric_columns
                )
                probe_query = sql.SQL("SELECT {parts} FROM {table}").format(
                    parts=select_parts,
                    table=sql.Identifier(schema, table_name),
                )
                logger.debug(f"Probing numeric dimensions: {probe_query.as_string()}")
                cursor.execute(probe_query)
                row = cursor.fetchone()
                if row is not None:
                    for i, col_name in enumerate(unconstrained_numeric_columns):
                        probed_scales[col_name] = row[2 * i]
                        probed_int_digits[col_name] = row[2 * i + 1]
        except Exception as e:
            # Probe is best-effort. Fall back to DEFAULT_NUMERIC_SCALE and let the downstream
            # `_process_batch` fallback chain infer the right type at row-fetching time.
            logger.warning(
                "Failed to probe numeric dimensions",
                schema=schema,
                table=table_name,
                error=str(e),
            )

    columns = []
    for name, data_type, nullable, numeric_precision_candidate, numeric_scale_candidate in metadata_rows:
        if data_type in numeric_data_types:
            if numeric_scale_candidate is not None:
                # Constrained `NUMERIC(p, s)`: trust the declared precision and scale directly.
                numeric_precision = numeric_precision_candidate or DEFAULT_NUMERIC_PRECISION
                numeric_scale = numeric_scale_candidate
            else:
                probed_scale = probed_scales.get(name)
                probed_int = probed_int_digits.get(name)
                # Intentionally fall back to DEFAULT_NUMERIC_SCALE when probed_scale is 0 or
                # missing. A scale of 0 means every row we saw today happens to be integer-valued,
                # but the source column is declared as unconstrained `numeric` — meaning the schema
                # makes no scale promise. Freezing the delta column at scale=0 based on a transient
                # all-integer snapshot would reintroduce this PR's original bug the moment a future
                # sync sees a fractional value. DEFAULT_NUMERIC_SCALE leaves room for that future.
                if probed_scale is not None and probed_scale > 0:
                    # MAX_NUMERIC_SCALE bounds the scale we're willing to write into delta.
                    effective_scale = min(probed_scale, MAX_NUMERIC_SCALE)
                    # Precision must cover BOTH integer digits and scale — if `int_digits +
                    # effective_scale` fits within the decimal128 budget (38), keep precision at
                    # 38 to leave maximum integer headroom for future rows. Otherwise escalate
                    # precision past 38 so `build_pyarrow_decimal_type` promotes the column to
                    # decimal256. That column will then be collapsed to `string` at delta write
                    # time (see `ensure_delta_compatible_arrow_schema` in dlt's deltalake libs) —
                    # a known fidelity loss that's preferable to silently truncating either
                    # integer digits (undersized precision) or fractional digits (undersized
                    # scale).
                    total_needed = (probed_int or 0) + effective_scale
                    if total_needed <= DEFAULT_NUMERIC_PRECISION:
                        numeric_precision = DEFAULT_NUMERIC_PRECISION
                    else:
                        numeric_precision = total_needed
                        logger.warning(
                            "Unconstrained numeric column exceeds decimal128 budget; "
                            "will be stored as string in delta to preserve fidelity",
                            schema=schema,
                            table=table_name,
                            column=name,
                            total_digits_needed=total_needed,
                            integer_digits=probed_int,
                            scale=effective_scale,
                            decimal128_budget=DEFAULT_NUMERIC_PRECISION,
                        )
                    numeric_scale = effective_scale
                else:
                    numeric_precision = DEFAULT_NUMERIC_PRECISION
                    numeric_scale = DEFAULT_NUMERIC_SCALE
        else:
            numeric_precision = None
            numeric_scale = None

        columns.append(
            PostgreSQLColumn(
                name=name,
                data_type=data_type,
                nullable=nullable,
                numeric_precision=numeric_precision,
                numeric_scale=numeric_scale,
            )
        )

    table_type: Literal["materialized_view", "view", "table"] = "table"
    if is_mat_view:
        table_type = "materialized_view"
    elif is_view:
        table_type = "view"

    return Table(name=table_name, parents=(schema,), columns=columns, type=table_type)


def _project_table_columns(
    table: Table[PostgreSQLColumn],
    retained: list[str] | None,
) -> Table[PostgreSQLColumn]:
    """Return a new `Table` whose columns are filtered to `retained` (in source order).

    `None` retained returns the table unchanged. Columns missing from `retained` are dropped from
    the Arrow schema so projected SELECT output zips correctly into the schema."""
    if retained is None:
        return table

    retained_set = set(retained)
    filtered = [column for column in table.columns if column.name in retained_set]
    return Table(name=table.name, parents=table.parents, columns=filtered, type=table.type, alias=table.alias)


# paramiko raises a bare, message-less EOFError from `start_client` when the SSH gateway accepts
# the TCP connection but closes it during the SSH handshake — a non-SSH service on the port, a
# bastion refusing PostHog's IPs, or a proxy that resets the stream. sshtunnel doesn't wrap it (it
# only translates *auth* failures into BaseSSHTunnelForwarderError), so it escapes with an empty
# `str()`, matching no non-retryable rule and retrying forever. `_tunnel_with_handshake_translation`
# turns it into this stable, classifiable message (see `PostgresSource.get_non_retryable_errors`) —
# same gateway-configuration class as a wrapped "Could not establish session to SSH gateway".
_SSH_HANDSHAKE_EOF_ERROR = "SSH gateway closed the connection during the SSH handshake"


@contextmanager
def _tunnel_with_handshake_translation(
    tunnel: Callable[[], _GeneratorContextManager[tuple[str, int]]],
) -> Iterator[tuple[str, int]]:
    """Enter `tunnel()`, translating a bare paramiko handshake EOFError into a classifiable message.

    The `yield` sits outside the `except` so a failure raised by the body can never be
    misattributed to the tunnel handshake.
    """
    with ExitStack() as stack:
        try:
            host, port = stack.enter_context(tunnel())
        except EOFError as e:
            raise Exception(_SSH_HANDSHAKE_EOF_ERROR) from e
        yield host, port


def postgres_source(
    tunnel: Callable[[], _GeneratorContextManager[tuple[str, int]]],
    user: str,
    password: str,
    database: str,
    sslmode: str,
    schema: str,
    table_names: list[str],
    should_use_incremental_field: bool,
    logger: FilteringBoundLogger,
    db_incremental_field_last_value: Optional[Any],
    chunk_size_override: Optional[int] = None,
    team_id: Optional[int] = None,
    incremental_field: Optional[str] = None,
    incremental_field_type: Optional[IncrementalFieldType] = None,
    require_ssl: bool = False,
    is_initial_sync: bool = False,
    enabled_columns: Optional[list[str]] = None,
    row_filters: Optional[list[ValidatedRowFilter]] = None,
    is_xmin: bool = False,
    xmin_last_value: Optional[int] = None,
    xmin_num_wraparound: Optional[int] = None,
) -> SourceResponse:
    table_name = table_names[0]
    if not table_name:
        raise ValueError("Table name is missing")

    effective_sslmode = _get_sslmode(require_ssl)

    with _tunnel_with_handshake_translation(tunnel) as (host, port):

        def _open_setup_connection() -> psycopg.Connection:
            try:
                conn = _connect_with_options_fallback(
                    host=host,
                    port=port,
                    dbname=database,
                    user=user,
                    password=password,
                    sslmode=effective_sslmode,
                    connect_timeout=15,
                    sslrootcert="/tmp/no.txt",
                    sslcert="/tmp/no.txt",
                    sslkey="/tmp/no.txt",
                    keepalives=1,
                    keepalives_idle=30,
                    keepalives_interval=10,
                    keepalives_count=5,
                    options=FORCE_UTF8_CLIENT_ENCODING,
                )
            except psycopg.OperationalError as e:
                if (
                    require_ssl
                    and "SSL" in str(e)
                    and not _is_invalid_ssl_negotiation_response(e)
                    and not _is_connection_dropped_error(e)
                ):
                    raise SSLRequiredError(
                        "SSL/TLS connection is required but your database does not support it. "
                        "Please enable SSL/TLS on your PostgreSQL server or contact your database administrator."
                    ) from e
                raise

            # Autocommit so each best-effort probe is its own transaction: one that fails — a
            # read-replica recovery conflict on a slow COUNT(*), or syntax the source rejects like
            # TABLESAMPLE on CockroachDB — can't poison the rest. Replaces the per-probe savepoints.
            conn.autocommit = True
            return conn

        # A hot-standby recovery conflict ("conflict with recovery") cancels or terminates the probe
        # mid-flight, so autocommit alone can't isolate it — the connection is left unusable and
        # every subsequent probe on it fails too. Reconnect and retry the metadata probes a bounded
        # number of times with backoff, mirroring how the read loop recovers from the same conflict.
        # Only once the conflicts are sustained do we raise the non-retryable
        # "successive SerializationFailure errors" abort the read path already uses, rather than
        # letting Temporal re-run setup straight back into the same wall.
        setup_recovery_conflicts = 0
        setup_connection_dropped_errors = 0
        # Captured once at sync start on the row-serving connection (see `_capture_xmin_ceiling`).
        # Re-derived on each setup retry, which is harmless — a later ceiling just reads a slightly
        # wider window. Persisted only at job completion (see the pipeline's xmin advance).
        xmin_bounds: XminBounds | None = None
        while True:
            # Opening the setup connection can itself hit a transient drop ("server closed the
            # connection unexpectedly", idle cull, failover) — the same class of error the read
            # path already recovers from. Retry the connect in-process with bounded backoff,
            # mirroring `offset_chunking`, so a momentary blip during setup doesn't fail the whole
            # activity. Permanent errors (auth failures, SSL-required) re-raise immediately.
            connection = _connect_with_dropped_retry(_open_setup_connection, logger)
            try:
                with connection:
                    with connection.cursor() as cursor:
                        logger.debug("Getting table types...")
                        # Only probe the actual data for numeric scale when a fresh delta column is
                        # about to be created — either a first-ever sync or a post-reset full scan
                        # (watermark cleared). On normal incremental syncs the delta column already
                        # exists, so probing would be a wasted full-table aggregation. Mirrors the
                        # `is_initial_sync or full_table_scan` gating used a few lines below for
                        # partitioned-table row estimation.
                        fresh_schema_being_created = is_initial_sync or db_incremental_field_last_value is None
                        full_table = _get_table(
                            cursor,
                            schema,
                            table_name,
                            logger,
                            probe_unconstrained_numeric_scale=fresh_schema_being_created,
                        )

                        # Session, not LOCAL: under autocommit a LOCAL timeout has no transaction to bind to.
                        cursor.execute(
                            sql.SQL("SET statement_timeout = {timeout}").format(
                                timeout=sql.Literal(1000 * 60 * 10)  # 10 mins
                            )
                        )

                        # Capture the xmin ceiling on this row-serving connection before streaming.
                        if is_xmin:
                            xmin_bounds = _capture_xmin_ceiling(cursor, xmin_last_value, xmin_num_wraparound, logger)

                        try:
                            logger.debug("Checking if source is a read replica...")
                            using_read_replica = _is_read_replica(cursor)
                            logger.debug(f"using_read_replica = {using_read_replica}")
                            logger.debug("Getting primary keys...")
                            primary_keys = _get_primary_keys(cursor, schema, table_name, logger)
                            if primary_keys:
                                logger.debug(f"Found primary keys: {primary_keys}")

                            # Fallback on checking for an `id` field on the table. Resolve the PKs
                            # before building queries so chunk-size sampling and the actual reader
                            # project the same columns.
                            used_id_pk_fallback = False
                            if primary_keys is None and "id" in full_table:
                                logger.debug("Falling back to ['id'] for primary keys...")
                                primary_keys = ["id"]
                                used_id_pk_fallback = True

                            # xmin reads deltas and relies on an idempotent upsert to dedupe a
                            # re-read window after a crash, so it requires a primary key.
                            if is_xmin and not primary_keys:
                                raise XminUnsupportedError(
                                    f"Table {schema}.{table_name} has no primary key, which xmin replication "
                                    "requires. Add a primary key or choose a different sync type."
                                )

                            # Project both the Arrow schema and the SELECT clause so the cursor's row shape
                            # matches what downstream consumers expect.
                            retained_columns: list[str] | None = None
                            if enabled_columns is not None:
                                retained_set: set[str] = set(enabled_columns)
                                for pk in primary_keys or []:
                                    retained_set.add(pk)
                                if incremental_field:
                                    retained_set.add(incremental_field)
                                retained_columns = [
                                    column.name for column in full_table.columns if column.name in retained_set
                                ]
                                # Mirror `compute_projected_columns` fallback to `SELECT *` so Arrow stays full-table.
                                if not retained_columns:
                                    retained_columns = None

                            table = _project_table_columns(full_table, retained_columns)
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
                                xmin_bounds=xmin_bounds,
                            )

                            count_query = _build_count_query(
                                schema,
                                table_name,
                                should_use_incremental_field,
                                incremental_field,
                                incremental_field_type,
                                db_incremental_field_last_value,
                                xmin_bounds=xmin_bounds,
                            )

                            logger.debug("Checking if table is partitioned...")
                            is_partitioned = False
                            child_partitions: list = []
                            try:
                                is_partitioned = _is_partitioned_table(cursor, schema, table_name)
                                if is_partitioned:
                                    child_partitions = list_child_partitions(cursor, schema, table_name)
                            except Exception as e:
                                logger.debug(f"Partition detection failed: {e}")

                            # A single global ceiling can't span a partitioned parent's independent
                            # per-partition xid spaces, so xmin is refused on parents (and hidden in
                            # discovery for them). Partition/window chunking below is gated on
                            # `should_use_incremental_field`, which is False for xmin, so xmin always
                            # takes the non-partitioned single-cursor path.
                            if is_xmin and is_partitioned:
                                raise XminUnsupportedError(
                                    f"Table {schema}.{table_name} is a partitioned parent, which xmin replication "
                                    "does not support. Choose a different sync type."
                                )
                            logger.debug("Getting table chunk size...")
                            if chunk_size_override is not None:
                                chunk_size = chunk_size_override
                                logger.debug(f"Using chunk_size_override: {chunk_size_override}")
                            else:
                                chunk_size = _get_table_chunk_size(cursor, inner_query_with_limit, logger)

                            logger.debug("Getting rows to sync...")
                            # For partitioned tables without an incremental cursor (initial
                            # sync, re-sync, or non-incremental), use pg_class.reltuples
                            # estimate to avoid scanning all partitions with a COUNT(*).
                            # `is_initial_sync` only reflects the first-ever sync; a forced
                            # re-sync keeps initial_sync_complete=True but still scans the
                            # whole table, so we gate on the filter actually being a full
                            # scan (no incremental cursor value).
                            rows_to_sync: int | None = None
                            full_table_scan = db_incremental_field_last_value is None
                            if is_partitioned and (is_initial_sync or full_table_scan):
                                try:
                                    logger.debug(
                                        f"Partitioned table detected (is_initial_sync={is_initial_sync}, "
                                        f"full_table_scan={full_table_scan}), using estimated row count"
                                    )
                                    rows_to_sync = _get_estimated_row_count_for_partitioned_table(
                                        cursor, schema, table_name, logger
                                    )
                                except Exception as e:
                                    logger.debug(f"Estimated row count failed, falling back to exact count: {e}")
                            if rows_to_sync is None:
                                rows_to_sync = _get_rows_to_sync(
                                    cursor,
                                    count_query,
                                    logger,
                                    should_use_incremental_field=should_use_incremental_field,
                                )

                            if _role_subject_to_rls(cursor, schema, table_name, logger):
                                logger.warning(
                                    f"Row-level security is active for the sync role on {schema}.{table_name} "
                                    f"(rows visible to this sync: {rows_to_sync}). Grant the role BYPASSRLS "
                                    f"or a permissive policy if it should see all rows."
                                )

                            logger.debug("Getting partition settings...")
                            partition_settings = (
                                _get_partition_settings(
                                    cursor, schema, table_name, logger, is_partitioned=is_partitioned
                                )
                                if should_use_incremental_field
                                else None
                            )

                            # Bounded date/numeric window chunking for partitioned parents keeps
                            # each query small so statement_timeout stays comfortable and partition
                            # pruning can drop empty partitions server-side. Non-partitioned tables
                            # continue through the legacy single-cursor path below.
                            use_window_chunking = (
                                is_partitioned
                                and should_use_incremental_field
                                and is_supported_incremental_type_for_window(incremental_field_type)
                            )
                            # When the parent is range-partitioned on the incremental field, we can
                            # query each child relation directly instead of routing through the parent
                            # and forcing the planner to Append + sort across all children. One cursor
                            # per child = no cross-partition merge sort, trivial pruning, and child-sized
                            # query plans that fit comfortably under statement_timeout.
                            use_per_partition_chunking = False
                            if use_window_chunking and child_partitions:
                                try:
                                    partition_strategy = get_partition_strategy(cursor, schema, table_name)
                                except Exception as e:
                                    partition_strategy = None
                                    logger.debug(f"Partition strategy detection failed: {e}")
                                use_per_partition_chunking = (
                                    partition_strategy is not None
                                    and partition_strategy.strategy == "r"
                                    and incremental_field is not None
                                    and incremental_field in partition_strategy.key_columns
                                )
                            logger.debug(
                                f"Postgres read strategy: use_window_chunking={use_window_chunking}, "
                                f"use_per_partition_chunking={use_per_partition_chunking}, "
                                f"child_partitions={len(child_partitions)}"
                            )

                            has_duplicate_primary_keys = False
                            if used_id_pk_fallback:
                                logger.debug("Checking duplicate primary keys...")
                                try:
                                    has_duplicate_primary_keys = _has_duplicate_primary_keys(
                                        cursor, schema, table_name, primary_keys, logger
                                    )
                                except psycopg.errors.QueryCanceled as e:
                                    # Surface a message about the assumed `id` primary key rather than
                                    # falling through to the generic incremental-field timeout below.
                                    raise _pk_uniqueness_probe_timeout_error() from e
                        except psycopg.errors.QueryCanceled:
                            if should_use_incremental_field:
                                raise QueryTimeoutException(
                                    f"10 min timeout statement reached. Please ensure your incremental field ({incremental_field}) has an appropriate index created"
                                )
                            raise
                        except Exception:
                            raise

                    # If a transient drop killed the connection during one of the best-effort
                    # savepoint probes above, the implicit commit on `with connection:` exit would
                    # otherwise raise a misleading "Explicit commit() forbidden within a Transaction
                    # context" (psycopg leaves the transaction-nesting counter incremented when it
                    # tears a savepoint down on a no-longer-OK connection). Surface the real,
                    # retryable dropped-connection error instead.
                    _raise_if_setup_connection_broken(connection)
                break
            except (psycopg.errors.SerializationFailure, psycopg.errors.QueryCanceled) as e:
                # A hot-standby recovery conflict surfaces as either SerializationFailure (the
                # transaction was aborted — "terminating connection due to conflict with recovery")
                # or QueryCanceled (the statement was canceled — "canceling statement due to conflict
                # with recovery", e.g. a replica reconnect) depending on the conflict and the server.
                # Both are the same transient condition and recover on reconnect. Any other
                # QueryCanceled here is a statement_timeout and must re-raise. QueryCanceled subclasses
                # OperationalError, so this clause must precede the connection-dropped handler below.
                if "conflict with recovery" not in "".join(e.args):
                    raise
                # Connection is dead; close defensively before reconnecting.
                _safe_close_connection(connection)
                setup_recovery_conflicts += 1
                if setup_recovery_conflicts >= _MAX_SETUP_RECOVERY_CONFLICT_RETRIES:
                    raise _recovery_conflict_abort_error(setup_recovery_conflicts) from e
                logger.debug(
                    f"Recovery conflict during table setup ({e}). Reconnecting and retrying "
                    f"(attempt {setup_recovery_conflicts}/{_MAX_SETUP_RECOVERY_CONFLICT_RETRIES})"
                )
                time.sleep(min(2 * setup_recovery_conflicts, 30))
            except _CONNECTION_DROPPED_ERROR_TYPES as e:
                # A transient drop *during* the metadata probes (e.g. a Supavisor pooler "DbHandler
                # exited" or a libpq "server closed the connection unexpectedly" while running
                # `_get_table`) leaves the connection dead. `_connect_with_dropped_retry` only guards
                # the initial connect, so without this the probe-time drop escapes and fails the
                # whole activity. Reconnect and retry the probes in-process with bounded backoff,
                # mirroring the recovery-conflict handler above and the read path's offset-chunking
                # recovery. Permanent errors (auth failures, SSL-required, genuine XX000 internal
                # errors) aren't connection drops, so they re-raise immediately.
                if not _is_connection_dropped_error(e):
                    raise
                _safe_close_connection(connection)
                setup_connection_dropped_errors += 1
                if setup_connection_dropped_errors >= _MAX_SETUP_CONNECTION_DROPPED_RETRIES:
                    raise
                logger.debug(
                    f"Connection dropped during table setup ({e}). Reconnecting and retrying "
                    f"(attempt {setup_connection_dropped_errors}/{_MAX_SETUP_CONNECTION_DROPPED_RETRIES})"
                )
                time.sleep(min(2 * setup_connection_dropped_errors, 30))

    def get_rows(chunk_size: int) -> Iterator[Any]:
        arrow_schema = table.to_arrow_schema()
        if xmin_bounds is not None:
            # The forced `_ph_xmin` projection isn't part of the discovered columns, so add it to
            # the Arrow schema (as the leading field, matching the SELECT) for a clean zip.
            arrow_schema = arrow_schema.insert(0, pa.field(XMIN_PROJECTED_COLUMN, pa.int64(), nullable=False))
        with _tunnel_with_handshake_translation(tunnel) as (host, port):
            cursor_factory = psycopg.ServerCursor if not using_read_replica else None

            def get_connection():
                try:
                    connection = _connect_with_options_fallback(
                        host=host,
                        port=port,
                        dbname=database,
                        user=user,
                        password=password,
                        sslmode=effective_sslmode,
                        connect_timeout=15,
                        sslrootcert="/tmp/no.txt",
                        sslcert="/tmp/no.txt",
                        sslkey="/tmp/no.txt",
                        cursor_factory=cursor_factory,
                        keepalives=1,
                        keepalives_idle=30,
                        keepalives_interval=10,
                        keepalives_count=5,
                        options=FORCE_UTF8_CLIENT_ENCODING,
                    )
                except psycopg.OperationalError as e:
                    if (
                        require_ssl
                        and "SSL" in str(e)
                        and not _is_invalid_ssl_negotiation_response(e)
                        and not _is_connection_dropped_error(e)
                    ):
                        raise SSLRequiredError(
                            "SSL/TLS connection is required but your database does not support it. "
                            "Please enable SSL/TLS on your PostgreSQL server or contact your database administrator."
                        ) from e
                    raise
                connection.adapters.register_loader("json", JsonAsStringLoader)
                connection.adapters.register_loader("jsonb", JsonAsStringLoader)
                connection.adapters.register_loader("int4range", RangeAsStringLoader)
                connection.adapters.register_loader("int8range", RangeAsStringLoader)
                connection.adapters.register_loader("numrange", RangeAsStringLoader)
                connection.adapters.register_loader("tsrange", RangeAsStringLoader)
                connection.adapters.register_loader("tstzrange", RangeAsStringLoader)
                connection.adapters.register_loader("daterange", RangeAsStringLoader)
                connection.adapters.register_loader("date", SafeDateLoader)
                connection.adapters.register_loader("timestamp", SafeTimestampLoader)
                connection.adapters.register_loader("timestamptz", SafeTimestamptzLoader)
                connection.adapters.register_loader("time", SafeTimeLoader)
                connection.adapters.register_loader("timetz", SafeTimetzLoader)
                # Bump statement_timeout for the streaming connection. A server
                # cursor FETCH inherits the session statement_timeout, and on
                # wide/partitioned scans the source's default (often 30-60s)
                # kills the fetch before rows come back.
                try:
                    # Use psycopg.Cursor directly to bypass cursor_factory (which may be
                    # ServerCursor and requires a `name` arg, breaking an unnamed cursor()).
                    with psycopg.Cursor(connection) as setup_cursor:
                        setup_cursor.execute(
                            sql.SQL("SET statement_timeout = {timeout}").format(
                                timeout=sql.Literal(SYNC_STATEMENT_TIMEOUT_MS)
                            )
                        )
                except Exception as e:
                    logger.debug(f"Failed to set statement_timeout on sync connection: {e}")
                # The SET above opens an implicit transaction in psycopg's default
                # non-autocommit mode, leaving the connection INTRANS. Commit so the
                # connection is returned IDLE: callers that flip on autocommit (offset
                # chunking) would otherwise hit "can't change autocommit state:
                # connection in transaction". SET statement_timeout has session scope,
                # so committing preserves it.
                connection.commit()
                return connection

            def offset_chunking(offset: int, chunk_size: int, *, from_recovery_conflict: bool = False):
                # If the db is a read replica and we're running into `conflict with recovery errors,
                # we create a new query for each chunk. This is due to how the primary replicates
                # over, we often run into errors when vacuums are happening
                logger.debug(
                    f"Using offset chunking to read from read replica. offset = {offset}, chunk_size = {chunk_size}"
                )

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
                    xmin_bounds=xmin_bounds,
                )

                successive_errors = 0
                successive_conn_errors = 0
                floor_retries = 0
                # Open lazily inside the loop so a recovery conflict (or connection drop) raised by
                # the connect itself is caught by the handlers below. A hot standby can cancel the
                # connection's own startup with "conflict with recovery" (SerializationFailure) when
                # we reconnect mid-recovery — opening outside the loop let that escape the whole
                # fallback even though it's the same transient condition the loop already retries.
                connection: psycopg.Connection | None = None
                while True:
                    try:
                        if connection is None or connection.closed:
                            logger.debug("Opening Postgres connection for offset chunking...")
                            connection = get_connection()
                            # Autocommit so each LIMIT/OFFSET query runs as its own statement and no
                            # transaction stays open across the slow delta-merge that happens between
                            # yields. A held transaction is what gets the backend culled by
                            # idle_in_transaction_session_timeout, producing the "server conn
                            # crashed?" ProtocolViolation on the next fetch.
                            connection.autocommit = True

                        # Use psycopg.Cursor directly to bypass cursor_factory: on a
                        # non-read-replica source it is ServerCursor (set in get_rows),
                        # which requires a `name` and makes an unnamed connection.cursor()
                        # raise "ServerCursor.__init__() missing 1 required positional
                        # argument: 'name'". This LIMIT/OFFSET fetchall path wants an
                        # unnamed client cursor.
                        with psycopg.Cursor(connection) as cursor:
                            query_with_limit_sql = query + sql.SQL(" LIMIT {limit} OFFSET {offset}").format(
                                limit=sql.Literal(chunk_size),
                                offset=sql.Literal(offset),
                            )
                            logger.debug(f"Postgres query: {query_with_limit_sql}")
                            cursor.execute(query_with_limit_sql)

                            column_names = [column.name for column in cursor.description or []]
                            rows = cursor.fetchall()

                            if not rows or len(rows) == 0:
                                break

                            offset += len(rows)

                            yield table_from_iterator((dict(zip(column_names, row)) for row in rows), arrow_schema)

                            successive_errors = 0
                            successive_conn_errors = 0
                            floor_retries = 0
                    except psycopg.errors.SerializationFailure as e:
                        if "due to conflict with recovery" not in "".join(e.args):
                            raise

                        logger.debug(f"SerializationFailure error: {e}. Retrying chunk at offset {offset}")

                        successive_errors += 1
                        # Shrink toward the floor first; only once stuck at the floor do we count down to
                        # the abort.
                        reduced_chunk_size = _next_recovery_conflict_chunk_size(chunk_size, successive_errors)
                        if reduced_chunk_size < chunk_size:
                            chunk_size = reduced_chunk_size
                            logger.debug(f"Reducing chunk size to {chunk_size} to reduce load on read replica")
                            floor_retries = 0
                        elif chunk_size <= _MIN_RECOVERY_CONFLICT_CHUNK_SIZE:
                            floor_retries += 1
                            if floor_retries >= _MAX_READ_RECOVERY_CONFLICT_RETRIES:
                                _safe_close_connection(connection)
                                raise _recovery_conflict_abort_error(floor_retries) from e
                        time.sleep(min(2 * successive_errors, 30))
                    except psycopg.errors.QueryCanceled as e:
                        # A chunk hit the 10-min statement_timeout. QueryCanceled
                        # subclasses OperationalError, so this clause must precede the
                        # connection-dropped handler below.
                        if _raised_while_closing_generator(e):
                            # The generator is being closed and the cursor teardown
                            # round-trip hit the statement_timeout — irrelevant to the
                            # sync outcome, so swallow it and let close() complete cleanly.
                            _safe_close_connection(connection)
                            return
                        # Retrying won't help, so map it to the same non-retryable
                        # QueryTimeoutException the server-cursor and windowed paths
                        # raise instead of leaking a raw, retryable QueryCanceled that
                        # Temporal keeps re-attempting.
                        _safe_close_connection(connection)
                        timeout_error = _statement_timeout_as_non_retryable(
                            e,
                            should_use_incremental_field=should_use_incremental_field,
                            incremental_field=incremental_field,
                        )
                        if timeout_error is not None:
                            raise timeout_error from e
                        if from_recovery_conflict:
                            # We only reach offset chunking here because the read replica just
                            # canceled our reads with a recovery conflict. Hitting the statement
                            # timeout on top of that means the chunked fallback can't finish a chunk
                            # either, and a whole-activity retry just re-reads from the start into the
                            # same conflicting, overloaded replica — so stop retrying. QueryTimeoutException
                            # is already non-retryable (see source.py), unlike the raw QueryCanceled.
                            raise QueryTimeoutException(
                                "Reading from your read replica timed out: Postgres canceled the initial "
                                "read with a recovery conflict, and the chunked fallback read still couldn't "
                                "finish within the 10 minute statement timeout. Increase "
                                "max_standby_streaming_delay or enable hot_standby_feedback on the replica, "
                                "or sync from the primary database instead."
                            ) from e
                        raise
                    except _CONNECTION_DROPPED_ERROR_TYPES as e:
                        if not _is_dropped_or_connect_timeout(e):
                            _safe_close_connection(connection)
                            raise

                        # The upstream connection died (idle cull, failover, etc.) or the
                        # reconnect that bootstraps this fallback timed out establishing the
                        # socket. offset only advances after a fully fetched+yielded chunk,
                        # so reopening and retrying the same offset resumes cleanly.
                        successive_conn_errors += 1
                        _safe_close_connection(connection)
                        if successive_conn_errors >= 10:
                            raise Exception(
                                f"Hit {successive_conn_errors} successive connection errors. Aborting."
                            ) from e
                        logger.debug(
                            f"Transient connection error ({e}). Reconnecting and retrying chunk at offset {offset} "
                            f"(attempt {successive_conn_errors})"
                        )
                        time.sleep(min(2 * successive_conn_errors, 30))
                        connection = _connect_with_dropped_retry(get_connection, logger)
                        connection.autocommit = True
                    except Exception:
                        _safe_close_connection(connection)
                        raise

                _safe_close_connection(connection)

            def connect_for_partition_iteration() -> psycopg.Connection:
                # Each window/partition opens its own connection. A transient drop on that connect —
                # idle cull, failover, an SSL EOF, or a freshly opened socket dying before the setup
                # commit ("the connection is lost") — is the same recoverable class the initial
                # server-cursor connect and the offset-chunking bootstrap already retry in-process.
                # Retry it here too so a blip resumes the next window/partition instead of escaping
                # and failing the whole activity. Only the connect is retried; a drop mid-fetch still
                # propagates, so a partially read window/partition is never re-yielded.
                return _connect_with_dropped_retry(get_connection, logger)

            if use_per_partition_chunking and incremental_field is not None and incremental_field_type is not None:

                def _build_per_partition_query(child_schema: str, child_name: str) -> sql.Composed:
                    return build_partition_query(
                        child_schema,
                        child_name,
                        should_use_incremental_field,
                        incremental_field,
                        incremental_field_type,
                        db_incremental_field_last_value,
                        enabled_columns=enabled_columns,
                        primary_keys=primary_keys,
                        row_filters=row_filters,
                    )

                yield from iterate_partitions(
                    get_connection=connect_for_partition_iteration,
                    build_partition_query=_build_per_partition_query,
                    schema=schema,
                    table_name=table_name,
                    child_partitions=child_partitions,
                    chunk_size=chunk_size,
                    arrow_schema=arrow_schema,
                    logger=logger,
                    incremental_field=incremental_field,
                    incremental_field_type=incremental_field_type,
                    db_incremental_field_last_value=db_incremental_field_last_value,
                )
                return

            if use_window_chunking and incremental_field is not None and incremental_field_type is not None:

                def _build_windowed_query(lo: Any, hi: Any) -> sql.Composed:
                    return _build_query(
                        schema,
                        table_name,
                        should_use_incremental_field,
                        table.type,
                        incremental_field,
                        incremental_field_type,
                        lo,
                        upper_bound_inclusive=hi,
                        enabled_columns=enabled_columns,
                        primary_keys=primary_keys,
                        row_filters=row_filters,
                    )

                yield from iterate_date_windows(
                    get_connection=connect_for_partition_iteration,
                    build_windowed_query=_build_windowed_query,
                    schema=schema,
                    table_name=table_name,
                    incremental_field=incremental_field,
                    incremental_field_type=incremental_field_type,
                    db_incremental_field_last_value=db_incremental_field_last_value,
                    child_partitions=child_partitions,
                    chunk_size=chunk_size,
                    arrow_schema=arrow_schema,
                    logger=logger,
                    using_read_replica=using_read_replica,
                    is_connection_dropped=_is_connection_dropped_error,
                )
                return

            offset = 0
            try:
                # Retry transient connection-dropped errors (e.g. "server closed the
                # connection unexpectedly") on the initial connect, matching the
                # offset-chunking bootstrap above. Retrying here is always safe: offset
                # is still 0 and no rows have been yielded, so the unsafe-resume concern
                # in the except clause below doesn't apply. Permanent errors (auth,
                # SSL-required) still surface immediately — _is_connection_dropped_error
                # only matches transient drops.
                with _connect_with_dropped_retry(get_connection, logger) as connection:
                    with connection.cursor(name=f"posthog_{team_id}_{schema}.{table_name}") as cursor:
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
                            xmin_bounds=xmin_bounds,
                        )
                        logger.debug(f"Postgres query: {query.as_string()}")

                        cursor.execute(query)

                        column_names = [column.name for column in cursor.description or []]

                        while True:
                            rows = cursor.fetchmany(chunk_size)
                            if not rows:
                                break

                            dicts = [dict(zip(column_names, row)) for row in rows]
                            del rows
                            yield table_from_iterator(iter(dicts), arrow_schema)
                            offset += len(dicts)
            except psycopg.errors.SerializationFailure as e:
                # If we hit a SerializationFailure and we're reading from a read replica, we fallback to offset chunking
                if using_read_replica and "conflict with recovery" in "".join(e.args):
                    logger.debug(f"Falling back to offset chunking for table due to SerializationFailure error: {e}.")
                    yield from offset_chunking(offset, chunk_size, from_recovery_conflict=True)
                    return

                raise
            except psycopg.errors.QueryCanceled as e:
                # A FETCH against the server cursor exhausted the 10-min
                # statement_timeout. QueryCanceled subclasses OperationalError, so
                # this clause must precede the connection-dropped handler below.
                if _raised_while_closing_generator(e):
                    # Not a real read timeout: the generator is being closed and the
                    # cursor/connection teardown round-trip hit the statement_timeout.
                    # Swallow it so close() completes cleanly instead of masking the
                    # real outcome (e.g. an activity cancellation) with a phantom timeout.
                    _safe_close_connection(connection)
                    return
                # Retrying is futile (usually a missing index on the incremental
                # field or a scan too large to finish in time), so map it to the
                # same non-retryable QueryTimeoutException the offset-chunking and
                # windowed paths raise instead of leaking a raw, retryable
                # QueryCanceled that Temporal keeps re-attempting.
                timeout_error = _statement_timeout_as_non_retryable(
                    e,
                    should_use_incremental_field=should_use_incremental_field,
                    incremental_field=incremental_field,
                )
                if timeout_error is not None:
                    raise timeout_error from e
                raise
            except _CONNECTION_DROPPED_ERROR_TYPES as e:
                # The server cursor holds a transaction open across the slow
                # delta-merge between yields; the source can cull the backend
                # (idle_in_transaction_session_timeout / PgBouncer) and the next
                # fetch fails with "server conn crashed?". Resume from the current
                # offset via offset_chunking, which runs in autocommit so it never
                # holds a transaction open across the merge.
                if not _is_connection_dropped_error(e):
                    raise
                # Offset-based resume is only safe when the query has a stable
                # ORDER BY (added by _build_query for incremental syncs, and by the
                # xmin branch). A full-table scan has no ORDER BY, so Postgres may
                # return rows in a different order on the resumed query and OFFSET
                # would skip or duplicate rows. In that case re-raise and let the
                # sync restart.
                if not should_use_incremental_field and xmin_bounds is None:
                    raise
                logger.debug(f"Connection dropped ({e}). Falling back to offset chunking at offset {offset}.")
                yield from offset_chunking(offset, chunk_size)
                return

    name = NamingConvention.normalize_identifier(table_name)

    return SourceResponse(
        name=name,
        items=lambda: get_rows(chunk_size),
        primary_keys=primary_keys,
        partition_count=partition_settings.partition_count if partition_settings else None,
        partition_size=partition_settings.partition_size if partition_settings else None,
        rows_to_sync=rows_to_sync,
        has_duplicate_primary_keys=has_duplicate_primary_keys,
        xmin_ceiling_xid=xmin_bounds.upper if xmin_bounds is not None else None,
        xmin_ceiling_xid8=xmin_bounds.ceiling_xid8 if xmin_bounds is not None else None,
        xmin_num_wraparound=xmin_bounds.num_wraparound if xmin_bounds is not None else None,
    )


# psycopg's `Cursor.execute` accepts `sql.Composable`/`bytes` in addition to `str`, so it
# does not satisfy the narrow `_CursorLike(execute(query: str, ...))` protocol on the base.
# Use `Any` for the cursor type variable.
class PostgresImplementation(SQLSourceImplementation[PostgresSourceConfig, psycopg.Connection, Any]):
    """Minimal `SQLSourceImplementation` stub paired with `PostgresSource`.

    `PostgresSource` overrides `get_schemas` and `source_for_pipeline` end to
    end — multi-schema discovery, `enabled_columns` column selection, CDC
    dispatch, SSL cutoff, and storage-key naming all live there because none of
    them fit `SourceInputs` or the base template. This impl only exists to
    satisfy the `SQLSource` type contract; only the four abstract methods are
    implemented. A deeper migration that pushes Postgres onto the base template
    would extend `SourceInputs` and is tracked as future work.
    """

    @contextmanager
    def connect(
        self,
        config: PostgresSourceConfig,
        *,
        require_ssl: bool = False,
    ) -> Iterator[psycopg.Connection]:
        """Open a single psycopg connection (through the SSH tunnel if configured)."""
        with open_ssh_tunnel(config) as (host, port):
            with pg_connection(
                host=host,
                port=port,
                database=config.database,
                user=config.user,
                password=config.password,
                require_ssl=require_ssl,
            ) as conn:
                yield conn

    def get_columns(
        self,
        conn: psycopg.Connection,
        config: PostgresSourceConfig,
        names: list[str] | None,
    ) -> dict[str, list[tuple[str, str, bool]]]:
        discovered = _schemas_from_conn(conn, config.schema, names)
        return {display_name: discovered_schema.columns for display_name, discovered_schema in discovered.items()}

    def get_incremental_filter(self) -> IncrementalFieldFilter:
        return filter_postgres_incremental_fields

    def build_pipeline(self, config: PostgresSourceConfig, inputs: SourceInputs) -> SourceResponse:
        """Postgres syncs go through `PostgresSource.source_for_pipeline`, not this method.

        The production path needs the `ExternalDataSchema` lookup to thread
        `enabled_columns`, `require_ssl` (derived from `source_requires_ssl`),
        `is_initial_sync`, `chunk_size_override`, and the multi-schema /
        CDC-streaming reconciliation into `postgres_source(...)`. None of that is
        available from `SourceInputs` alone, and silently defaulting `require_ssl`
        to `False` here would let new (post-cutoff) sources bypass SSL on the base
        template path. Raise loudly so a refactor that drops the source-level
        override surfaces immediately rather than going to prod unencrypted.
        """
        raise NotImplementedError(
            "PostgresImplementation.build_pipeline is intentionally not implemented — "
            "use PostgresSource.source_for_pipeline which forwards require_ssl, "
            "enabled_columns, chunk_size_override, and CDC reconciliation."
        )
