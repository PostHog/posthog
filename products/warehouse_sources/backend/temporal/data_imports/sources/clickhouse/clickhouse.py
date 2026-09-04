from __future__ import annotations

import re
import ssl
import math
import time
import threading
import collections
from collections.abc import Callable, Iterator
from contextlib import _GeneratorContextManager
from typing import Any, Literal, Optional

import pyarrow as pa
import structlog
from clickhouse_connect import get_client
from clickhouse_connect.driver import httputil
from clickhouse_connect.driver.client import Client as ClickHouseClient
from clickhouse_connect.driver.exceptions import ClickHouseError, ProgrammingError
from dlt.common.normalizers.naming.snake_case import NamingConvention
from structlog.types import FilteringBoundLogger
from urllib3 import PoolManager
from urllib3.response import HTTPResponse

from posthog.exceptions_capture import capture_exception

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import (
    build_pyarrow_decimal_type,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.consts import DEFAULT_CHUNK_SIZE
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.partitioning import (
    DEFAULT_PARTITION_TARGET_SIZE_IN_BYTES,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.helpers import incremental_type_to_initial_value
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import _require_loopback
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql import (
    Column,
    Table,
    compute_projected_columns,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.identifiers import (
    BacktickIdentifierQuoter,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.predicates import (
    ValidatedRowFilter,
    render_named_conditions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.types import IncrementalFieldType, PartitionSettings

# Why a connection is allowed to skip the egress proxy, or None to stay proxied. A reason
# rather than a bool so `_get_client` — where every call site converges — can check the
# claim against the address it was given instead of trusting the caller's pairing.
BypassEnvProxy = Literal["tunnel_loopback", "internal_team"] | None

# ClickHouse default ports
CLICKHOUSE_HTTP_PORT = 8123
CLICKHOUSE_HTTPS_PORT = 8443

# Connect timeout for the HTTP client
CONNECT_TIMEOUT_SECONDS = 15
# Cloud cold-resume (idle services routinely take 30–60s to wake on the
# first request) and to leave headroom over the server-side `max_execution_time`
# caps on bounded probes
METADATA_QUERY_TIMEOUT_SECONDS = 120
# Per-query timeout for the main data extraction query
DATA_QUERY_TIMEOUT_SECONDS = 60 * 60  # 1 hour

# Batch accumulation targets for streaming to Delta Lake. ClickHouse yields
# one Arrow block per `max_block_size` rows (20k default); writing each to
# Delta unchanged produces one commit per block, which murders large-table
# performance. We accumulate blocks until we hit either target, then
# concat and yield a single pa.Table to the pipeline.
YIELD_TARGET_BYTES = 200 * 1024 * 1024  # 200 MiB, matches pipeline partition target
YIELD_TARGET_ROWS = 100_000

# Quoter for user-supplied row-filter column names — the allowlist-validated
# safety rail the shared predicate renderer expects. Trusted internal
# identifiers (table/incremental columns) keep using `_quote_identifier`.
_ROW_FILTER_IDENTIFIER_QUOTER = BacktickIdentifierQuoter()


class ClickHouseConnectionError(Exception):
    """Raised when we cannot establish or use a ClickHouse connection."""

    pass


# clickhouse-connect probes the server with `SELECT version(), timezone()` while
# constructing the client and unpacks the reply into exactly two tab-separated
# values (BaseClient._init_common_settings). A host that answers 2xx with a body
# that isn't a ClickHouse response — a proxy/load-balancer landing page, or a
# different service listening on the host/port — splits into a different shape, so
# the driver raises a bare `ValueError` ("too many values to unpack") before we ever
# run a query. The endpoint isn't serving the ClickHouse HTTP interface, so a retry
# replays the identical failure; we surface it as a connection error rather than
# leaking the cryptic ValueError.
NOT_A_CLICKHOUSE_HTTP_RESPONSE = (
    "The host answered but did not return a valid ClickHouse response, so it isn't serving the "
    "ClickHouse HTTP interface on that host/port. Check the host, port, and HTTPS setting "
    "(and any tunnel or proxy in front of it)."
)


def _quote_identifier(identifier: str) -> str:
    """Quote a ClickHouse identifier with backticks.

    ClickHouse allows arbitrary identifiers when wrapped in backticks. We
    escape backticks inside the name and refuse identifiers containing
    null bytes — both of which would be unusable in any sane schema.
    """
    if "\x00" in identifier:
        raise ValueError(f"identifier contains null byte: {identifier!r}")
    escaped = identifier.replace("`", "``")
    return f"`{escaped}`"


def _qualified_table(database: str, table_name: str) -> str:
    return f"{_quote_identifier(database)}.{_quote_identifier(table_name)}"


# Number of times we re-open the client before giving up on a transient drop during connect.
_MAX_CONNECT_ATTEMPTS = 3

# Substrings of a connect-time failure that denote the connection being dropped before/during the
# TLS read (ClickHouse Cloud cold-resume hanging up the first request, a proxy/LB idle cull, a
# network blip) rather than a deterministic config error. A fresh attempt recovers. The TLS config
# failures we never retry (`certificate verify failed`, `SSL: WRONG_VERSION_NUMBER`) don't contain
# any of these, so the allowlist can't catch them.
_TRANSIENT_CONNECT_DROP_SUBSTRINGS = (
    # OpenSSL 3.x and 1.x wordings for the peer closing the socket without a clean TLS close_notify.
    "UNEXPECTED_EOF_WHILE_READING",
    "EOF occurred in violation of protocol",
    "Connection reset by peer",
    "Connection aborted",
    # The egress proxy answered our CONNECT with a transient gateway status
    # (`http.client` raises `OSError("Tunnel connection failed: <code> ...")`).
    # 502/503/504 are the proxy or its upstream being briefly unreachable or
    # overloaded, so a fresh attempt recovers. We match only these gateway
    # codes, not deterministic proxy responses like 407 (auth required).
    "Tunnel connection failed: 502",
    "Tunnel connection failed: 503",
    "Tunnel connection failed: 504",
    # The ClickHouse host (or a proxy/gateway in front of it) rate-limited the
    # request with HTTP 429 ("HTTPDriver for <url> returned response code 429").
    # A 429 is a transient "back off and retry" signal, not a config error.
    # clickhouse-connect already retries 429 for queries (query_retries), but
    # the probe it runs while constructing the client passes retries=0, so a
    # 429 at connect time reaches us with no retry at all — a bounded backoff
    # retry here recovers the common transient burst. We match only 429; other
    # HTTP statuses keep their existing handling (404 is non-retryable in the
    # source, 5xx stay retryable via Temporal).
    "returned response code 429",
    # urllib3 couldn't open the TCP connection to our own egress proxy at all — it never got far
    # enough to attempt a CONNECT tunnel — and wraps the raw socket timeout as
    # `ProxyError('Cannot connect to proxy.', TimeoutError('timed out'))`. This is our proxy
    # being briefly unreachable, not a customer config problem, so a fresh attempt recovers.
    # Matching the full inner exception keeps this distinct from `Tunnel connection failed:
    # 407` above, which wraps the same "Cannot connect to proxy." prefix around a deterministic
    # proxy-auth response and must stay non-retryable.
    "Cannot connect to proxy.', TimeoutError('timed out')",
)


def _is_transient_connect_drop(error_message: str) -> bool:
    return any(substring in error_message for substring in _TRANSIENT_CONNECT_DROP_SUBSTRINGS)


# clickhouse-connect surfaces an upstream rate-limit as a full HTTP response
# ("HTTPDriver for <url> returned response code 429"), not a dropped connection:
# the request reached the server (or a proxy in front of it) and it told us to
# slow down. A 429 is explicitly "retry later", so a brief backed-off re-attempt
# often clears a short rate-limit burst; if it doesn't, the failing Temporal
# activity stays retryable and recovers later. We match only 429 — other 4xx
# response codes are deterministic (e.g. 404 stays non-retryable). Matching the
# stable status phrase keeps the volatile per-request URL out of the comparison.
_TRANSIENT_RATE_LIMIT_SUBSTRING = "returned response code 429"

# Backoff base between connect retries after a 429. Longer than the connect-drop
# retry (which just re-dials) to give the rate limit room to clear.
_RATE_LIMIT_BACKOFF_BASE_SECONDS = 2


def _is_rate_limited(error_message: str) -> bool:
    return _TRANSIENT_RATE_LIMIT_SUBSTRING in error_message


# The source server's own concurrency limit ("Code: 202. DB::Exception: Too many
# simultaneous queries for all users. Current: N, maximum: N. (TOO_MANY_SIMULTANEOUS_QUERIES)")
# rejects even the client-construction probe query when the server is already at capacity.
# Like a 429, this is the server asking us to back off, not a config error, and it clears on
# its own as other queries finish — so a backed-off retry recovers it the same way. The
# "Current"/"maximum" counts are volatile; the ClickHouse error-code name is stable.
_TRANSIENT_TOO_MANY_QUERIES_SUBSTRING = "TOO_MANY_SIMULTANEOUS_QUERIES"


def _is_too_many_queries(error_message: str) -> bool:
    return _TRANSIENT_TOO_MANY_QUERIES_SUBSTRING in error_message


def _is_retryable_connect_error(error_message: str) -> bool:
    return (
        _is_transient_connect_drop(error_message)
        or _is_rate_limited(error_message)
        or _is_too_many_queries(error_message)
    )


def _apply_session_settings(client: ClickHouseClient, settings: dict[str, Any]) -> None:
    """Apply session settings, tolerating a server that reports one as readonly.

    Our settings are performance and Arrow-output tuning hints. A readonly user
    profile (common on managed ClickHouse) reports every setting as readonly, and
    clickhouse-connect refuses to send those — raising ProgrammingError ("Setting
    <x> is unknown or readonly"). Passing them at client construction turns that
    into a fatal connect error that fails the whole sync. Applying them one by one
    lets us keep the settings the server accepts and fall back to the server
    default for the rest.
    """
    for key, value in settings.items():
        try:
            client.set_client_setting(key, value)
        except ProgrammingError as e:
            structlog.get_logger().warning(
                "ClickHouse rejected session setting; falling back to server default",
                setting=key,
                exc_info=e,
            )


class _NoRedirectPoolManager(PoolManager):
    """A urllib3 manager that refuses to follow redirects.

    Only proxy-bypassing connections use this manager. urllib3 follows a cross-host redirect
    on the same manager, so without this the host we connect to could answer with a redirect
    to an arbitrary address and we would fetch it directly from the worker, which is the
    reachability the egress proxy exists to deny. A ClickHouse HTTP endpoint has no reason to
    redirect us, so refusing costs nothing: the 3xx response goes back to clickhouse-connect,
    which reports it as a connection error.

    Enforced by overriding `urlopen` rather than through the pool's `retries` option because
    clickhouse-connect passes its own `retries` on every request, which would take precedence
    over a pool-level default.
    """

    # The urllib3 1.26 stub types `urlopen` with the generic `RequestMethods` parameters and
    # omits `redirect`, even though it is the real third parameter of `PoolManager.urlopen`.
    # Declaring the stub's parameters instead would forward `encode_multipart` down to
    # `HTTPConnectionPool.urlopen`, which rejects it, so match the runtime signature.
    def urlopen(self, method: str, url: str, redirect: bool = True, **kw: Any) -> HTTPResponse:  # type: ignore[override]
        return super().urlopen(method, url, redirect=False, **kw)


# Bounds the manager cache below. `server_hostname` is user-controlled (the source's
# configured host), so an unbounded cache would let repeated credential validations with
# distinct hostnames retain a manager each for the life of the worker. Far above the number
# of distinct tunneled HTTPS hostnames a worker legitimately serves concurrently.
_POOL_MANAGER_CACHE_MAX = 32
_pool_managers: collections.OrderedDict[tuple[bool, str | None], Any] = collections.OrderedDict()
_pool_managers_lock = threading.Lock()


def _no_env_proxy_pool_manager(verify: bool, server_hostname: str | None = None) -> Any:
    """A shared urllib3 pool manager that never consults HTTP(S)_PROXY env vars.

    clickhouse-connect only checks the proxy env vars when it builds its own
    pool manager, so handing it one is the sanctioned per-code-path opt-out
    from the egress proxy (see posthog/security/outbound_proxy.py for the
    requests/httpx equivalents). Cached because clients don't own an injected
    manager (`close()` leaves it alive), so per-call managers would leak.

    `server_hostname` keeps TLS verification honest through an SSH tunnel: we dial the
    tunnel's loopback bind, but SNI and hostname validation must run against the database's
    own hostname or the certificate can never match. Mirrors what clickhouse-connect does
    with `server_host_name` when it builds its own manager — a branch it skips entirely
    when handed a `pool_mgr`.

    LRU-bounded: eviction closes the manager's pools and removes it from the library's
    process-global registry, the two places that would otherwise retain it forever. An
    evicted manager still held by a live client keeps working — urllib3 rebuilds pools on
    demand — it just stops being shared or expiry-swept.

    Built from clickhouse-connect's own options factory so the TCP keepalive tuning and
    certificate handling match a direct connection, then recorded where the library tracks
    its own managers so connection expiry and interpreter-exit cleanup cover this one too.
    """
    key = (verify, server_hostname)
    with _pool_managers_lock:
        manager = _pool_managers.get(key)
        if manager is not None:
            _pool_managers.move_to_end(key)
            return manager

        options = httputil.get_pool_manager_options(verify=verify)
        if server_hostname:
            if verify:
                options["assert_hostname"] = server_hostname
            options["server_hostname"] = server_hostname
        manager = _NoRedirectPoolManager(**options)
        httputil.all_managers[manager] = int(time.time())
        _pool_managers[key] = manager

        while len(_pool_managers) > _POOL_MANAGER_CACHE_MAX:
            _, evicted = _pool_managers.popitem(last=False)
            httputil.all_managers.pop(evicted, None)
            evicted.clear()
        return manager


def _get_client(
    *,
    host: str,
    port: int,
    database: str,
    user: str,
    password: str | None,
    secure: bool,
    verify: bool,
    query_timeout: int = DATA_QUERY_TIMEOUT_SECONDS,
    settings: Optional[dict[str, Any]] = None,
    bypass_env_proxy: BypassEnvProxy = None,
    server_hostname: str | None = None,
) -> ClickHouseClient:
    """Create a ClickHouse HTTP client.

    Uses clickhouse-connect, which speaks the HTTP/HTTPS interface. This is
    firewall-friendly, easy to tunnel via SSH, and exposes a streaming Arrow
    reader that we use to read very large tables without buffering them in
    memory.

    `bypass_env_proxy` names why the connection may skip the HTTP(S)_PROXY env
    vars: "internal_team" for PostHog-internal teams
    (`is_team_allowlisted_for_internal_hosts`), "tunnel_loopback" for an
    address that came out of our own SSH tunnel — the proxy blocks the tunnel's
    loopback bind, and no request would reach the forwarded port. For a
    customer-supplied host the egress proxy is the SSRF backstop and must stay
    in the path, so the tunnel claim is checked against the address here: the
    flag and the host travel to this point independently, and a caller pairing
    "tunnel_loopback" with a non-loopback host has lost that pairing.

    `server_hostname` (tunnel only) is the database's own hostname, so TLS SNI
    and certificate hostname validation run against it rather than against the
    loopback address we dial — disabling verification is not the supported way
    to make HTTPS work through a tunnel.
    """
    if bypass_env_proxy == "tunnel_loopback":
        _require_loopback(host)
    pool_mgr = None
    if bypass_env_proxy:
        tunnel_tls_hostname = server_hostname if bypass_env_proxy == "tunnel_loopback" and secure else None
        pool_mgr = _no_env_proxy_pool_manager(verify, tunnel_tls_hostname)
    attempt = 0
    while True:
        try:
            client = get_client(
                host=host,
                port=port,
                database=database,
                username=user,
                # clickhouse-connect expects str; passwordless auth is empty string.
                password=password or "",
                secure=secure,
                verify=verify,
                connect_timeout=CONNECT_TIMEOUT_SECONDS,
                send_receive_timeout=query_timeout,
                query_limit=0,  # we manage limits ourselves
                compress=True,
                pool_mgr=pool_mgr,
            )
        except (ClickHouseError, OSError, ssl.SSLError) as e:
            # OSError covers socket.gaierror, ConnectionRefusedError, TimeoutError,
            # and httpx-raised network errors that subclass OSError. ssl.SSLError
            # covers TLS handshake failures that happen before ClickHouse sees
            # the request.
            attempt += 1
            message = str(e)
            if attempt < _MAX_CONNECT_ATTEMPTS and _is_retryable_connect_error(message):
                # A 429 or a too-many-queries rejection is the server asking us to
                # slow down, so back off exponentially to give it room to clear; a
                # dropped connection just needs a re-dial, so a short linear wait
                # is enough.
                wait = (
                    _RATE_LIMIT_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
                    if _is_rate_limited(message) or _is_too_many_queries(message)
                    else attempt
                )
                structlog.get_logger().warning(
                    "Transient ClickHouse connect error; retrying",
                    attempt=attempt,
                    max_attempts=_MAX_CONNECT_ATTEMPTS,
                    wait_seconds=wait,
                    exc_info=e,
                )
                time.sleep(wait)
                continue
            raise ClickHouseConnectionError(message) from e
        except ValueError as e:
            # The construction-time server probe got a response it couldn't parse as a
            # ClickHouse handshake (see NOT_A_CLICKHOUSE_HTTP_RESPONSE). Deterministic, so
            # never retryable — don't spend the transient-retry budget on it.
            raise ClickHouseConnectionError(NOT_A_CLICKHOUSE_HTTP_RESPONSE) from e

        # Apply tuning settings after connect, not at construction, so a readonly
        # source profile that rejects one degrades to the server default instead
        # of failing the whole connection.
        _apply_session_settings(client, settings or {})
        return client


def _strip_type_modifiers(type_name: str) -> tuple[str, bool]:
    """Strip Nullable(...) and LowCardinality(...) wrappers.

    Returns the inner type and whether the original type was Nullable.
    LowCardinality alone does not affect nullability, so we recursively
    unwrap it but never set the nullable flag for it.
    """
    nullable = False
    current = type_name.strip()

    while True:
        if current.startswith("Nullable(") and current.endswith(")"):
            nullable = True
            current = current[len("Nullable(") : -1].strip()
        elif current.startswith("LowCardinality(") and current.endswith(")"):
            current = current[len("LowCardinality(") : -1].strip()
        else:
            break

    return current, nullable


def filter_clickhouse_incremental_fields(
    columns: list[tuple[str, str, bool]],
) -> list[tuple[str, IncrementalFieldType, bool]]:
    """Return columns suitable for use as an incremental cursor.

    ClickHouse type names are case-sensitive in metadata responses (e.g.
    `DateTime64(6)`, `Int64`, `Date`). We unwrap Nullable/LowCardinality
    wrappers first and then match against the bare type.
    """
    results: list[tuple[str, IncrementalFieldType, bool]] = []
    for column_name, raw_type, nullable in columns:
        inner_type, _ = _strip_type_modifiers(raw_type)
        # DateTime, DateTime64, DateTime('UTC'), DateTime64(3, 'UTC'), ...
        if inner_type.startswith("DateTime"):
            results.append((column_name, IncrementalFieldType.Timestamp, nullable))
        elif inner_type in ("Date", "Date32"):
            results.append((column_name, IncrementalFieldType.Date, nullable))
        elif inner_type in (
            "Int8",
            "Int16",
            "Int32",
            "Int64",
            "Int128",
            "Int256",
            "UInt8",
            "UInt16",
            "UInt32",
            "UInt64",
            "UInt128",
            "UInt256",
        ):
            results.append((column_name, IncrementalFieldType.Integer, nullable))

    return results


def get_schemas(
    *,
    host: str,
    port: int,
    database: str,
    user: str,
    password: str | None,
    secure: bool,
    verify: bool,
    names: list[str] | None = None,
    bypass_env_proxy: BypassEnvProxy = None,
    server_hostname: str | None = None,
) -> dict[str, list[tuple[str, str, bool]]]:
    """Discover columns for all tables in the given database.

    Uses `system.columns`, which gives us everything in one round trip.
    Note: ClickHouse columns expose the *original* type string, including
    Nullable/LowCardinality wrappers — we keep the wrappers and parse them
    later, so we can preserve nullability information.
    """
    client = _get_client(
        host=host,
        port=port,
        database=database,
        user=user,
        password=password,
        secure=secure,
        verify=verify,
        query_timeout=METADATA_QUERY_TIMEOUT_SECONDS,
        bypass_env_proxy=bypass_env_proxy,
        server_hostname=server_hostname,
    )

    try:
        params: dict[str, Any] = {"database": database}
        names_filter = ""
        if names:
            # clickhouse-connect formats tuples as `(a, b, c)`, which matches
            # ClickHouse's IN clause syntax. Lists would format as `[a, b, c]`
            # which is valid but less standard.
            params["names"] = tuple(names)
            names_filter = "AND table IN %(names)s"

        # Skip ALIAS and EPHEMERAL columns. A native `SELECT *` never touches them, but our
        # `SELECT *` expands to an explicit column list — so an ALIAS whose defining expression no
        # longer resolves on the server (a dropped/renamed underlying column, or one the connecting
        # user can't read) fails the whole query with UNKNOWN_IDENTIFIER (code 47), and EPHEMERAL
        # columns aren't selectable at all. Ordinary, DEFAULT and MATERIALIZED columns hold real,
        # selectable data and are kept.
        result = client.query(
            f"""
            SELECT table, name, type
            FROM system.columns
            WHERE database = %(database)s {names_filter}
              AND default_kind NOT IN ('ALIAS', 'EPHEMERAL')
            ORDER BY table ASC, position ASC
            """,
            parameters=params,
        )
    finally:
        client.close()

    schema_list: dict[str, list[tuple[str, str, bool]]] = collections.defaultdict(list)
    for row in result.result_rows:
        table_name, column_name, raw_type = row[0], row[1], row[2]
        if _is_inner_table(table_name):
            continue
        _, nullable = _strip_type_modifiers(raw_type)
        schema_list[table_name].append((column_name, raw_type, nullable))

    return schema_list


def _is_inner_table(table_name: str) -> bool:
    """Whether a table is a materialized view's hidden inner table.

    ClickHouse backs a materialized view created without an explicit `TO`
    target with an auto-generated inner table — `.inner.<mv_name>` on older
    Ordinary databases, `.inner_id.<uuid>` on Atomic databases. These are
    implementation details, not user data: their `.inner_id.<uuid>` names
    change whenever the view is recreated, so a sync pointed at one breaks
    the moment the view is rebuilt. Discover the materialized view by its own
    name instead, never its inner table.
    """
    return table_name.startswith(".inner.") or table_name.startswith(".inner_id.")


# Match `TO db.table` or `TO table` clause in MV CREATE statement.
# ClickHouse always emits the target in `system.tables.create_table_query`
# for MVs created with explicit `TO` target.
_MV_TO_TARGET_RE = re.compile(
    r"\bTO\s+(?:`((?:[^`]|``)+)`|(\w+))(?:\.(?:`((?:[^`]|``)+)`|(\w+)))?",
    re.IGNORECASE,
)


def _parse_mv_target(create_query: str | None) -> tuple[str, str] | None:
    """Parse (database, table) target from an MV's CREATE statement.

    Only matches `TO <target>` — not `AS SELECT ... FROM <source>`. If the
    MV has no explicit target, returns None and the caller uses the
    `.inner_id.<uuid>` lookup instead.
    """
    if not create_query:
        return None
    match = _MV_TO_TARGET_RE.search(create_query)
    if match is None:
        return None
    first = (match.group(1) or match.group(2) or "").replace("``", "`")
    second = (match.group(3) or match.group(4) or "").replace("``", "`")
    if second:
        return (first, second)
    # Single identifier means `TO target` without database qualifier — we
    # can't resolve this without knowing the MV's own database; caller
    # passes it in.
    return ("", first)


def get_clickhouse_row_count(
    *,
    host: str,
    port: int,
    database: str,
    user: str,
    password: str | None,
    secure: bool,
    verify: bool,
    names: list[str] | None = None,
    bypass_env_proxy: BypassEnvProxy = None,
    server_hostname: str | None = None,
) -> dict[str, int]:
    """Return total_rows per table from `system.tables`.

    Coverage:
    - MergeTree family: free — ClickHouse keeps a running counter.
    - Distributed: fall back to `SELECT count()` (cheap, distributed).
    - MaterializedView with `TO target`: resolve target, use its total_rows.
    - MaterializedView without TO: resolve `.inner_id.<uuid>` inner table.
    - Plain View / LiveView / WindowView / Memory / Buffer / Log / Kafka /
      URL etc: omitted — count would require executing the view or scanning
      the whole table.
    """
    client = _get_client(
        host=host,
        port=port,
        database=database,
        user=user,
        password=password,
        secure=secure,
        verify=verify,
        query_timeout=METADATA_QUERY_TIMEOUT_SECONDS,
        bypass_env_proxy=bypass_env_proxy,
        server_hostname=server_hostname,
    )

    try:
        params: dict[str, Any] = {"database": database}
        names_filter = ""
        if names:
            params["names"] = tuple(names)
            names_filter = "AND name IN %(names)s"

        result = client.query(
            f"""
            SELECT name, total_rows, engine, uuid, create_table_query
            FROM system.tables
            WHERE database = %(database)s {names_filter}
            """,
            parameters=params,
        )

        counts: dict[str, int] = {}
        distributed_fallbacks: list[str] = []
        mv_targets: dict[str, tuple[str, str]] = {}  # mv_name -> (target_db, target_table)
        mv_inner_lookups: dict[str, str] = {}  # mv_name -> uuid (for .inner_id.<uuid>)

        for row in result.result_rows:
            name, total_rows, engine, uuid_val, create_query = row[0], row[1], row[2], row[3], row[4]
            if total_rows is not None:
                counts[name] = int(total_rows)
                continue
            if engine == "Distributed":
                distributed_fallbacks.append(name)
                continue
            if engine == "MaterializedView":
                target = _parse_mv_target(create_query)
                if target is not None:
                    target_db, target_table = target
                    mv_targets[name] = (target_db or database, target_table)
                elif uuid_val:
                    mv_inner_lookups[name] = str(uuid_val)

        for name in distributed_fallbacks:
            try:
                count_result = client.query(f"SELECT count() FROM {_qualified_table(database, name)}")
                if count_result.result_rows and count_result.result_rows[0][0] is not None:
                    counts[name] = int(count_result.result_rows[0][0])
            except ClickHouseError:
                continue

        # Batch lookup MV targets' total_rows via system.tables.
        if mv_targets:
            target_keys = list({(db, tbl) for db, tbl in mv_targets.values()})
            try:
                target_result = client.query(
                    """
                    SELECT database, name, total_rows
                    FROM system.tables
                    WHERE (database, name) IN %(keys)s AND total_rows IS NOT NULL
                    """,
                    parameters={"keys": tuple(target_keys)},
                )
                target_counts = {(row[0], row[1]): int(row[2]) for row in target_result.result_rows}
                for mv_name, (target_db, target_table) in mv_targets.items():
                    target_count = target_counts.get((target_db, target_table))
                    if target_count is not None:
                        counts[mv_name] = target_count
            except ClickHouseError:
                pass

        # Batch lookup MVs without TO target via .inner_id.<uuid>.
        if mv_inner_lookups:
            inner_names = tuple(f".inner_id.{uuid}" for uuid in mv_inner_lookups.values())
            try:
                inner_result = client.query(
                    """
                    SELECT name, total_rows
                    FROM system.tables
                    WHERE database = %(database)s AND name IN %(names)s AND total_rows IS NOT NULL
                    """,
                    parameters={"database": database, "names": inner_names},
                )
                inner_counts = {row[0]: int(row[1]) for row in inner_result.result_rows}
                for mv_name, uuid in mv_inner_lookups.items():
                    inner_count = inner_counts.get(f".inner_id.{uuid}")
                    if inner_count is not None:
                        counts[mv_name] = inner_count
            except ClickHouseError:
                pass
    except ClickHouseError:
        return {}
    finally:
        client.close()

    return counts


def get_connection_metadata(
    *,
    host: str,
    port: int,
    database: str,
    user: str,
    password: str | None,
    secure: bool,
    verify: bool,
    bypass_env_proxy: BypassEnvProxy = None,
    server_hostname: str | None = None,
) -> dict[str, Any]:
    """Probe the server for version metadata.

    Used during onboarding to surface a sensible error if credentials are
    valid but the database doesn't exist, and to record server version on
    the source for future debugging.
    """
    client = _get_client(
        host=host,
        port=port,
        database=database,
        user=user,
        password=password,
        secure=secure,
        verify=verify,
        query_timeout=METADATA_QUERY_TIMEOUT_SECONDS,
        bypass_env_proxy=bypass_env_proxy,
        server_hostname=server_hostname,
    )

    try:
        result = client.query("SELECT version(), currentDatabase()")
        row = result.result_rows[0] if result.result_rows else (None, None)
        version = str(row[0]) if row[0] is not None else ""
        current_database = str(row[1]) if row[1] is not None else database

        return {
            "database": current_database,
            "version": version,
            "engine": "clickhouse",
        }
    finally:
        client.close()


# Regex helpers for parsing ClickHouse type strings.
# DecimalN(S) variants have fixed precision implied by N — the single
# argument is scale, not precision. Decimal(P, S) / Decimal(P) is the
# explicit form.
_DECIMAL_FIXED_WIDTHS: dict[str, int] = {"32": 9, "64": 18, "128": 38, "256": 76}
_DECIMAL_FIXED_RE = re.compile(r"^Decimal(32|64|128|256)\(\s*(\d+)\s*\)$")
_DECIMAL_VAR_RE = re.compile(r"^Decimal\(\s*(\d+)\s*(?:,\s*(\d+)\s*)?\)$")
_DATETIME64_RE = re.compile(r"^DateTime64\(\s*(\d+)\s*(?:,\s*'([^']*)'\s*)?\)$")
_DATETIME_RE = re.compile(r"^DateTime(?:\(\s*'([^']*)'\s*\))?$")
_FIXED_STRING_RE = re.compile(r"^FixedString\(\s*\d+\s*\)$")
_ENUM_RE = re.compile(r"^Enum(?:8|16)\(.*\)$")


def _datetime_unit_for_precision(precision: int) -> Literal["s", "ms", "us", "ns"]:
    if precision <= 0:
        return "s"
    if precision <= 3:
        return "ms"
    if precision <= 6:
        return "us"
    return "ns"


class ClickHouseColumn(Column):
    """Implementation of the `Column` protocol for a ClickHouse source.

    Attributes:
        name: The column's name.
        data_type: The original ClickHouse type string, possibly wrapped in
            `Nullable(...)` and/or `LowCardinality(...)`.
        nullable: Whether the column is nullable. Derived from the
            `Nullable(...)` wrapper.
    """

    def __init__(self, name: str, data_type: str, nullable: bool) -> None:
        self.name = name
        self.data_type = data_type
        self.nullable = nullable

    def to_arrow_field(self) -> pa.Field[pa.DataType]:
        inner, _ = _strip_type_modifiers(self.data_type)
        arrow_type = self._inner_to_arrow_type(inner)
        return pa.field(self.name, arrow_type, nullable=self.nullable)

    @classmethod
    def _inner_to_arrow_type(cls, inner: str) -> pa.DataType:
        # Integer types
        match inner:
            case "Int8":
                return pa.int8()
            case "Int16":
                return pa.int16()
            case "Int32":
                return pa.int32()
            case "Int64":
                return pa.int64()
            case "UInt8":
                return pa.uint8()
            case "UInt16":
                return pa.uint16()
            case "UInt32":
                return pa.uint32()
            case "UInt64":
                return pa.uint64()
            case "Float32":
                return pa.float32()
            case "Float64":
                return pa.float64()
            case "Bool":
                return pa.bool_()
            case "String":
                return pa.string()
            case "UUID":
                return pa.string()
            case "Date":
                return pa.date32()
            case "Date32":
                return pa.date32()
            case "IPv4" | "IPv6":
                return pa.string()
            # Wide integers we cannot represent natively in Arrow — fall back to
            # string so we don't silently truncate.
            case "Int128" | "Int256" | "UInt128" | "UInt256":
                return pa.string()

        # DateTime / DateTime('UTC')
        match_dt = _DATETIME_RE.match(inner)
        if match_dt is not None:
            # pa.timestamp stubs don't accept tz=None as a typed overload, so
            # we branch instead of passing through Optional[str].
            tz = match_dt.group(1) or None
            return pa.timestamp("s", tz=tz) if tz else pa.timestamp("s")

        # DateTime64(precision[, timezone])
        match_dt64 = _DATETIME64_RE.match(inner)
        if match_dt64 is not None:
            precision = int(match_dt64.group(1))
            tz = match_dt64.group(2) or None
            unit = _datetime_unit_for_precision(precision)
            return pa.timestamp(unit, tz=tz) if tz else pa.timestamp(unit)

        # DecimalN(S) — N fixes precision (9/18/38/76), the lone arg is scale.
        match_fixed = _DECIMAL_FIXED_RE.match(inner)
        if match_fixed is not None:
            precision = _DECIMAL_FIXED_WIDTHS[match_fixed.group(1)]
            scale = int(match_fixed.group(2))
            return build_pyarrow_decimal_type(precision, scale)

        # Decimal(P[, S]) — explicit precision and scale.
        match_dec = _DECIMAL_VAR_RE.match(inner)
        if match_dec is not None:
            precision = int(match_dec.group(1))
            scale = int(match_dec.group(2)) if match_dec.group(2) is not None else 0
            return build_pyarrow_decimal_type(precision, scale)

        # FixedString(N) — bytes-like, but stored as string for portability
        if _FIXED_STRING_RE.match(inner):
            return pa.string()

        # Enum8(...) / Enum16(...) — surface labels as strings
        if _ENUM_RE.match(inner):
            return pa.string()

        # Composite types — Array, Map, Tuple, Nested, JSON, Object — are
        # serialized to a JSON string. We could be smarter about Array of
        # primitives in the future.
        if (
            inner.startswith("Array(")
            or inner.startswith("Map(")
            or inner.startswith("Tuple(")
            or inner.startswith("Nested(")
            or inner.startswith("Variant(")
            or inner.startswith("Dynamic")
            or inner.startswith("JSON")
            or inner.startswith("Object(")
        ):
            return pa.string()

        # Anything we don't recognise is safest as a string.
        return pa.string()


def _is_view_engine(engine: str | None) -> bool:
    if not engine:
        return False
    return engine in ("View", "MaterializedView", "LiveView", "WindowView")


def _is_materialized_view_engine(engine: str | None) -> bool:
    return engine == "MaterializedView"


def _get_table(client: ClickHouseClient, database: str, table_name: str) -> Table[ClickHouseColumn]:
    """Read columns + table type for a single table from system tables."""
    # Skip ALIAS and EPHEMERAL columns, matching `get_schemas`'s discovery query — see its
    # comment for why: our `SELECT *` expands to an explicit column list, and an included
    # ALIAS whose defining expression no longer resolves fails the whole sync query with
    # UNKNOWN_IDENTIFIER (code 47), while EPHEMERAL columns aren't selectable at all.
    cols_result = client.query(
        """
        SELECT name, type
        FROM system.columns
        WHERE database = %(database)s AND table = %(table)s
          AND default_kind NOT IN ('ALIAS', 'EPHEMERAL')
        ORDER BY position ASC
        """,
        parameters={"database": database, "table": table_name},
    )

    columns: list[ClickHouseColumn] = []
    for name, raw_type in cols_result.result_rows:
        _, nullable = _strip_type_modifiers(raw_type)
        columns.append(ClickHouseColumn(name=name, data_type=raw_type, nullable=nullable))

    if not columns:
        raise ValueError(f"Table {database}.{table_name} not found or has no columns")

    engine_result = client.query(
        "SELECT engine FROM system.tables WHERE database = %(database)s AND name = %(table)s",
        parameters={"database": database, "table": table_name},
    )
    engine = engine_result.result_rows[0][0] if engine_result.result_rows else None

    table_type: str = "table"
    if _is_materialized_view_engine(engine):
        table_type = "materialized_view"
    elif _is_view_engine(engine):
        table_type = "view"

    return Table(name=table_name, parents=(database,), columns=columns, type=table_type)  # type: ignore[arg-type]


def _get_primary_keys(client: ClickHouseClient, database: str, table_name: str) -> list[str] | None:
    """Return the columns of the table's sorting key.

    ClickHouse's primary key is by definition a prefix of the sorting key,
    and is the closest analog to a unique key — though it is *not*
    necessarily unique. Callers must be prepared to handle duplicates.
    """
    result = client.query(
        """
        SELECT name
        FROM system.columns
        WHERE database = %(database)s AND table = %(table)s AND is_in_sorting_key = 1
        ORDER BY position ASC
        """,
        parameters={"database": database, "table": table_name},
    )
    keys = [row[0] for row in result.result_rows]
    return keys if keys else None


def get_primary_keys_for_schemas(
    *,
    host: str,
    port: int,
    database: str,
    user: str,
    password: str | None,
    secure: bool,
    verify: bool,
    table_names: list[str],
    bypass_env_proxy: BypassEnvProxy = None,
    server_hostname: str | None = None,
) -> dict[str, list[str] | None]:
    """Detect primary keys (sorting key columns) for multiple tables.

    Opens a single client and reuses `_get_primary_keys` per table. Returns
    a dict keyed by every input table name, with None for tables where no
    sorting key exists or the lookup failed.
    """
    result: dict[str, list[str] | None] = dict.fromkeys(table_names)
    if not table_names:
        return result

    try:
        client = _get_client(
            host=host,
            port=port,
            database=database,
            user=user,
            password=password,
            secure=secure,
            verify=verify,
            query_timeout=METADATA_QUERY_TIMEOUT_SECONDS,
            bypass_env_proxy=bypass_env_proxy,
            server_hostname=server_hostname,
        )
        try:
            for table_name in table_names:
                try:
                    result[table_name] = _get_primary_keys(client, database, table_name)
                except ClickHouseError as e:
                    structlog.get_logger().warning(
                        "Failed to detect primary keys for ClickHouse table",
                        table=table_name,
                        exc_info=e,
                    )
        finally:
            client.close()
    except Exception as e:
        structlog.get_logger().warning("Failed to detect primary keys for ClickHouse schemas", exc_info=e)

    return result


# Row budget for the duplicate-PK probe. ClickHouse sorting keys are not
# enforced unique, so we need *some* signal before trusting a user-selected
# key for incremental merges — but a full-table GROUP BY (even streamed in
# sort-key order) is too expensive to run every sync on billion-row tables.
# Instead we scan up to this many rows and trust the user if no duplicate
# surfaces. Misconfigured sort keys overwhelmingly surface duplicates in
# any reasonably-sized prefix.
DUPLICATE_PK_CHECK_ROW_BUDGET = 10_000_000

# Settings for the duplicate-PK probe.
# - optimize_aggregation_in_order streams the GROUP BY along the sorting
#   key without building a hash table (bounded memory).
# - max_rows_to_read + read_overflow_mode='break' cap the scan at
#   DUPLICATE_PK_CHECK_ROW_BUDGET and *silently stop* instead of throwing.
# - max_execution_time and max_memory_usage are belt-and-braces bounds.
_DUPLICATE_PK_CHECK_SETTINGS: dict[str, Any] = {
    "optimize_aggregation_in_order": 1,
    "max_rows_to_read": DUPLICATE_PK_CHECK_ROW_BUDGET,
    "read_overflow_mode": "break",
    "max_execution_time": 30,
    "max_memory_usage": 1_000_000_000,
}

# Substrings of probe errors that are expected environment limits or designed
# fallbacks rather than bugs on our side. In every case we fall back to append
# mode, so capturing them only adds error-tracking noise:
#   - "is unknown or readonly": clickhouse-connect validates session settings
#     client-side and refuses any the server reports as readonly or unknown
#     ("Setting <x> is unknown or readonly"), routine on managed offerings
#     (ClickHouse Cloud) and readonly user profiles.
#   - MEMORY_LIMIT_EXCEEDED / TIMEOUT_EXCEEDED: the bounded probe exhausted one
#     of its own budgets (`max_memory_usage` / `max_execution_time`).
#     `optimize_aggregation_in_order` keeps the GROUP BY streaming, but on
#     large/slow (e.g. S3-backed) source tables the scan can still hit these
#     caps before `read_overflow_mode='break'` truncates on rows — the probe
#     behaving exactly as designed. Some managed servers also enforce a memory
#     cap below our `max_memory_usage`, surfacing the same way.
#   - "Read timed out": the probe's `max_execution_time` only bounds server-side
#     execution, not ClickHouse Cloud's cold-resume wake-up latency or a scan
#     the server hasn't yet gotten around to capping — so the HTTP client's own
#     read timeout can fire first. Same designed fallback as the budget caps.
_EXPECTED_PROBE_FAILURE_SUBSTRINGS: tuple[str, ...] = (
    "is unknown or readonly",
    "MEMORY_LIMIT_EXCEEDED",
    "TIMEOUT_EXCEEDED",
    "Read timed out",
)


def _is_expected_probe_failure(message: str) -> bool:
    """Whether a duplicate-PK probe failure is an expected environment limit or designed fallback."""
    return any(substring in message for substring in _EXPECTED_PROBE_FAILURE_SUBSTRINGS)


def _has_duplicate_primary_keys(
    client: ClickHouseClient,
    database: str,
    table_name: str,
    primary_keys: list[str] | None,
    logger: FilteringBoundLogger,
) -> bool:
    """Check whether the sorting key has obvious duplicate combinations.

    ClickHouse sorting keys are *not* enforced unique. For incremental syncs
    we need a unique-ish key to do safe merges into Delta. We probe a
    bounded prefix of the table (DUPLICATE_PK_CHECK_ROW_BUDGET rows) rather
    than scanning the whole thing, because:

    1. A user who chose a non-unique sort key will virtually always show
       duplicates inside any reasonably sized prefix.
    2. A full-table GROUP BY every incremental sync is prohibitively
       expensive on the tables this source is designed for.
    3. ClickHouse cannot *prove* uniqueness anyway — only the user can.

    Returns:
        True if duplicates are detected in the probed prefix, or if the
        probe failed in an unexpected way. False when the probe completed
        within budget without finding duplicates.
    """
    if not primary_keys:
        return False

    quoted_keys = ", ".join(_quote_identifier(k) for k in primary_keys)
    # LIMIT 1 lets ClickHouse short-circuit the moment it finds a duplicate.
    query = f"SELECT 1 FROM {_qualified_table(database, table_name)} GROUP BY {quoted_keys} HAVING count() > 1 LIMIT 1"
    try:
        result = client.query(query, settings=_DUPLICATE_PK_CHECK_SETTINGS)
        return len(result.result_rows) > 0
    except ClickHouseError as e:
        # Any server error is treated as "assume duplicates" — safer to force
        # append mode than to merge against a key we couldn't verify. (We don't
        # hit max_rows_to_read here because read_overflow_mode='break' turns
        # that into a silent truncation.)
        logger.warning(
            f"_has_duplicate_primary_keys: assuming duplicates exist (probe failed for {database}.{table_name}): {e}"
        )
        # Only report genuinely unexpected probe failures. Exhausting the
        # probe's own memory/time budget is the designed fallback on large
        # source tables, and managed/readonly ClickHouse servers routinely
        # reject our tuning settings — expected outcomes the append-mode
        # fallback already handles, so capturing them only adds noise.
        if not _is_expected_probe_failure(str(e)):
            capture_exception(e)
        return True


def _get_incremental_row_count(
    client: ClickHouseClient,
    database: str,
    table_name: str,
    incremental_field: str,
    last_value: Any,
    logger: FilteringBoundLogger,
    incremental_field_type: Optional[IncrementalFieldType] = None,
) -> int | None:
    """Count rows the incremental sync will actually pull.

    `system.tables.total_rows` is the size of the entire table, which
    overstates the work for incremental syncs after the initial backfill.
    This query is cheap when the cursor is in the sorting key (primary
    index skip). On error or timeout we return None and the caller falls
    back to the total-table count.
    """
    quoted_field = _quote_identifier(incremental_field)
    last_value_expr = _last_value_expr(incremental_field_type)
    query = f"SELECT count() FROM {_qualified_table(database, table_name)} WHERE {quoted_field} > {last_value_expr}"
    try:
        result = client.query(
            query,
            parameters={"last_value": last_value},
            settings={"max_execution_time": 30},
        )
    except ClickHouseError as e:
        logger.debug(f"_get_incremental_row_count: fell back, count query failed: {e}")
        return None

    if not result.result_rows:
        return None
    count = result.result_rows[0][0]
    return int(count) if count is not None else None


# clickhouse-connect surfaces a non-2xx HTTP status from the server (or a
# proxy/LB in front of it) as `HTTPDriver for <url> returned response code <N>`.
# 429 (rate limited) and the transient gateway codes mean the endpoint can't
# serve us right now, not that anything we sent was wrong — they clear on their
# own. A real ClickHouse query error carries a `Code: NNN` instead. We match
# only these transient statuses so genuine failures still surface.
_TRANSIENT_HTTP_RESPONSE_SUBSTRINGS: tuple[str, ...] = (
    "returned response code 429",
    "returned response code 502",
    "returned response code 503",
    "returned response code 504",
)


def _is_transient_http_response(message: str) -> bool:
    return any(substring in message for substring in _TRANSIENT_HTTP_RESPONSE_SUBSTRINGS)


def _get_partition_settings(
    client: ClickHouseClient, database: str, table_name: str, logger: FilteringBoundLogger
) -> PartitionSettings | None:
    """Compute partition settings using `system.tables.total_bytes`.

    ClickHouse maintains compressed and uncompressed sizes per table — we
    use total_bytes (compressed on disk) as a rough proxy for memory cost
    on the pipeline side. For non-MergeTree engines `total_bytes` may be
    NULL, in which case we return None and the pipeline falls back to its
    default partitioning.
    """
    try:
        result = client.query(
            """
            SELECT total_rows, total_bytes
            FROM system.tables
            WHERE database = %(database)s AND name = %(table)s
            """,
            parameters={"database": database, "table": table_name},
        )
    except ClickHouseError as e:
        # Partitioning is a best-effort optimization; any failure here degrades
        # to default partitioning. A transient rate-limit/gateway response from
        # the source isn't actionable on our side, so don't add error-tracking
        # noise for it — genuine errors are still captured.
        if not _is_transient_http_response(str(e)):
            capture_exception(e)
        logger.debug(f"_get_partition_settings: failed: {e}")
        return None

    if not result.result_rows:
        return None

    total_rows, total_bytes = result.result_rows[0]
    if total_rows is None or total_bytes is None or total_rows == 0 or total_bytes == 0:
        return None

    bytes_per_row = total_bytes / total_rows
    if bytes_per_row <= 0:
        return None

    partition_size = max(1, int(round(DEFAULT_PARTITION_TARGET_SIZE_IN_BYTES / bytes_per_row)))
    partition_count = max(1, math.floor(total_rows / partition_size))

    logger.debug(
        f"_get_partition_settings: total_rows={total_rows} total_bytes={total_bytes} "
        f"partition_size={partition_size} partition_count={partition_count}"
    )
    return PartitionSettings(partition_count=partition_count, partition_size=partition_size)


# ClickHouse types Arrow output can't emit directly — we coerce to String
# via toString() to avoid ClickHouse error 50 "Type is not supported by Arrow".
_ARROW_UNSUPPORTED_EXACT = frozenset(
    {
        "UUID",
        "IPv4",
        "IPv6",
        "Int128",
        "Int256",
        "UInt128",
        "UInt256",
        "Dynamic",
        "JSON",
    }
)
_ARROW_UNSUPPORTED_PREFIXES: tuple[str, ...] = (
    "Enum8(",
    "Enum16(",
    "FixedString(",
    "Array(",
    "Map(",
    "Tuple(",
    "Nested(",
    "Variant(",
    "Object(",
)


def _needs_to_string_cast(inner: str) -> bool:
    if inner in _ARROW_UNSUPPORTED_EXACT:
        return True
    return any(inner.startswith(prefix) for prefix in _ARROW_UNSUPPORTED_PREFIXES)


def _build_select_list(columns: list[ClickHouseColumn]) -> str:
    """Build explicit SELECT list, wrapping Arrow-unsupported types in toString()."""
    parts: list[str] = []
    for col in columns:
        quoted = _quote_identifier(col.name)
        inner, _ = _strip_type_modifiers(col.data_type)
        if _needs_to_string_cast(inner):
            parts.append(f"toString({quoted}) AS {quoted}")
        else:
            parts.append(quoted)
    return ", ".join(parts)


def _project_columns(
    columns: list[ClickHouseColumn],
    enabled_columns: Optional[list[str]],
    primary_keys: Optional[list[str]],
    incremental_field: Optional[str],
) -> list[ClickHouseColumn]:
    """Restrict the SELECT to the user-enabled columns.

    `enabled_columns is None` syncs every column. Otherwise we project to the
    enabled set plus the primary keys and incremental cursor (always synced),
    reusing the shared `compute_projected_columns` ordering and mapping the
    names back to typed `ClickHouseColumn`s so toString casting is preserved.
    Falls back to all columns if nothing resolves, so a sync never selects zero
    columns.
    """
    projected_names = compute_projected_columns(enabled_columns, primary_keys, incremental_field)
    if projected_names is None:
        return columns
    by_name = {column.name: column for column in columns}
    projected = [by_name[name] for name in projected_names if name in by_name]
    return projected or columns


def _last_value_expr(incremental_field_type: Optional[IncrementalFieldType]) -> str:
    """SQL expression binding the `last_value` parameter for the incremental cursor.

    The stored cursor for a `Date` column can arrive as a raw day-count integer
    (ClickHouse's own on-disk representation) rather than a date/string, e.g. after a
    round-trip through JSON. Comparing that integer directly against a `Date` column
    fails with "Illegal types of arguments (Date, UInt16) of function greater". Casting
    through `toDate32` accepts both a day-count integer and a date string, so the
    comparison always type-checks regardless of which shape the cursor is in.
    """
    if incremental_field_type == IncrementalFieldType.Date:
        return "toDate32(%(last_value)s)"
    return "%(last_value)s"


def _build_query(
    *,
    database: str,
    table_name: str,
    columns: list[ClickHouseColumn],
    should_use_incremental_field: bool,
    incremental_field: Optional[str],
    incremental_field_type: Optional[IncrementalFieldType] = None,
    row_filters: Optional[list[ValidatedRowFilter]] = None,
) -> tuple[str, dict[str, Any]]:
    """Build the data extraction query and its bound parameters.

    Returns the SQL string plus the row-filter params dict. We never
    interpolate values — only identifiers (which are validated) end up in the
    SQL string; the incremental cursor and every row-filter value bind as
    parameters. Row filters are ANDed onto the WHERE clause. Column types
    ClickHouse can't emit as Arrow (UUID, IPv4, enums, arrays, ...) are
    wrapped in toString() to avoid error 50.
    """
    qualified = _qualified_table(database, table_name)
    select_list = _build_select_list(columns)

    filter_conditions, filter_params = render_named_conditions(row_filters or [], _ROW_FILTER_IDENTIFIER_QUOTER)

    if not should_use_incremental_field:
        if filter_conditions:
            return f"SELECT {select_list} FROM {qualified} WHERE {' AND '.join(filter_conditions)}", filter_params
        return f"SELECT {select_list} FROM {qualified}", filter_params

    if incremental_field is None:
        raise ValueError("incremental_field can't be None when should_use_incremental_field is True")

    quoted_field = _quote_identifier(incremental_field)
    conditions = [f"{quoted_field} > {_last_value_expr(incremental_field_type)}", *filter_conditions]
    query = f"SELECT {select_list} FROM {qualified} WHERE {' AND '.join(conditions)} ORDER BY {quoted_field} ASC"
    return query, filter_params


def _query_settings(chunk_size: int) -> dict[str, Any]:
    """ClickHouse server-side settings applied to every data query.

    These tune the streaming Arrow output and prevent runaway resource use
    on the source side. They are intentionally conservative — operators
    can override per-source via chunk_size_override on the schema.
    """
    return {
        # Stream Arrow record batches in chunks of `chunk_size` rows. This is
        # the per-batch row limit on the source side and bounds memory.
        "max_block_size": chunk_size,
        # Make Arrow output use real String columns instead of binary buffers,
        # which keeps the resulting RecordBatches readable by Delta Lake.
        "output_format_arrow_string_as_string": 1,
        # Materialize LowCardinality columns into their underlying type, so the
        # PyArrow schema we generate matches what we receive.
        "output_format_arrow_low_cardinality_as_dictionary": 0,
        # Cap query execution time to avoid hanging the worker on a runaway
        # source-side query.
        "max_execution_time": DATA_QUERY_TIMEOUT_SECONDS,
        # When the ORDER BY column is a prefix of the sorting key, read parts
        # in sort order and skip the top-level sort entirely. Free when
        # applicable, harmless otherwise. Critical for incremental syncs on
        # big tables — without this, ORDER BY forces a full external sort.
        "optimize_read_in_order": 1,
        # If we still have to sort (cursor not in sorting key), spill to disk
        # at 500 MB instead of OOMing the server. The hot path stays in
        # memory, slow path degrades gracefully.
        "max_bytes_before_external_sort": 500 * 1024 * 1024,
    }


def clickhouse_source(
    *,
    tunnel: Callable[[], _GeneratorContextManager[tuple[str, int]]],
    user: str,
    password: str | None,
    database: str,
    secure: bool,
    verify: bool,
    table_names: list[str],
    should_use_incremental_field: bool,
    logger: FilteringBoundLogger,
    db_incremental_field_last_value: Optional[Any],
    chunk_size_override: Optional[int] = None,
    incremental_field: Optional[str] = None,
    incremental_field_type: Optional[IncrementalFieldType] = None,
    row_filters: Optional[list[ValidatedRowFilter]] = None,
    enabled_columns: Optional[list[str]] = None,
    bypass_env_proxy: BypassEnvProxy = None,
    server_hostname: str | None = None,
) -> SourceResponse:
    """Build a SourceResponse that pulls a single ClickHouse table.

    Streams the data via Arrow batches so we never materialize the whole
    table in memory. Each yielded `pa.Table` is one Arrow record batch.
    """
    if not table_names or not table_names[0]:
        raise ValueError("Table name is missing")
    table_name = table_names[0]

    chunk_size = chunk_size_override if chunk_size_override is not None else DEFAULT_CHUNK_SIZE

    with tunnel() as (host, port):
        client = _get_client(
            host=host,
            port=port,
            database=database,
            user=user,
            password=password,
            secure=secure,
            verify=verify,
            query_timeout=METADATA_QUERY_TIMEOUT_SECONDS,
            bypass_env_proxy=bypass_env_proxy,
            server_hostname=server_hostname,
        )

        try:
            logger.info(f"Discovering table {database}.{table_name}")
            table = _get_table(client, database, table_name)
            logger.info(f"Source schema: {table.to_arrow_schema()}")

            primary_keys = _get_primary_keys(client, database, table_name)
            if primary_keys:
                logger.debug(f"Found primary keys (sorting key): {primary_keys}")

            # Project to the user-selected columns (always keeping PK + cursor).
            projected_columns = _project_columns(list(table.columns), enabled_columns, primary_keys, incremental_field)

            # Warn when the incremental cursor isn't the sorting-key prefix.
            # ClickHouse can only skip the sort if the ORDER BY column leads
            # the sorting key; otherwise every incremental run does a full
            # server-side sort. `max_bytes_before_external_sort` in
            # `_query_settings` keeps it from OOMing, but it will be slow.
            if should_use_incremental_field and incremental_field and primary_keys:
                if primary_keys[0] != incremental_field:
                    logger.warning(
                        f"Incremental cursor '{incremental_field}' is not the first "
                        f"column of the sorting key {primary_keys} for "
                        f"{database}.{table_name}. Each incremental sync will perform "
                        f"a server-side sort. Consider a cursor that matches the "
                        f"table's sorting key for best performance."
                    )

            row_counts = get_clickhouse_row_count(
                host=host,
                port=port,
                database=database,
                user=user,
                password=password,
                secure=secure,
                verify=verify,
                names=[table_name],
                bypass_env_proxy=bypass_env_proxy,
                server_hostname=server_hostname,
            )
            rows_to_sync: int | None = row_counts.get(table_name)

            # For incremental resumes, pull the filtered count so progress
            # reporting isn't anchored to the full table size.
            if should_use_incremental_field and incremental_field and db_incremental_field_last_value is not None:
                incremental_count = _get_incremental_row_count(
                    client,
                    database,
                    table_name,
                    incremental_field,
                    db_incremental_field_last_value,
                    logger,
                    incremental_field_type=incremental_field_type,
                )
                if incremental_count is not None:
                    rows_to_sync = incremental_count

            partition_settings = (
                _get_partition_settings(client, database, table_name, logger) if should_use_incremental_field else None
            )

            has_duplicate_primary_keys = False
            if should_use_incremental_field and primary_keys:
                has_duplicate_primary_keys = _has_duplicate_primary_keys(
                    client, database, table_name, primary_keys, logger
                )
        finally:
            client.close()

    def get_rows() -> Iterator[Any]:
        logger.info(f"get_rows: starting stream for {database}.{table_name} chunk_size={chunk_size}")
        # Open a fresh tunnel + client for the streaming read so the
        # connection used for discovery isn't held open longer than needed.
        with tunnel() as (stream_host, stream_port):
            stream_client = _get_client(
                host=stream_host,
                port=stream_port,
                database=database,
                user=user,
                password=password,
                secure=secure,
                verify=verify,
                query_timeout=DATA_QUERY_TIMEOUT_SECONDS,
                settings=_query_settings(chunk_size),
                bypass_env_proxy=bypass_env_proxy,
                server_hostname=server_hostname,
            )

            try:
                query, filter_params = _build_query(
                    database=database,
                    table_name=table_name,
                    columns=projected_columns,
                    should_use_incremental_field=should_use_incremental_field,
                    incremental_field=incremental_field,
                    incremental_field_type=incremental_field_type,
                    row_filters=row_filters,
                )

                parameters: dict[str, Any] = dict(filter_params)
                if should_use_incremental_field:
                    last_value = db_incremental_field_last_value
                    if last_value is None and incremental_field_type is not None:
                        last_value = incremental_type_to_initial_value(incremental_field_type)
                    parameters["last_value"] = last_value

                logger.info(f"ClickHouse query: {query}")

                # query_arrow_stream yields pa.RecordBatch chunks — one per
                # ClickHouse block, capped by max_block_size. We accumulate
                # these into ~YIELD_TARGET_BYTES / YIELD_TARGET_ROWS pa.Tables
                # before yielding, so the pipeline's Delta writer sees fewer,
                # larger batches and commits fewer Delta files.
                pending: list[pa.RecordBatch] = []
                pending_rows = 0
                pending_bytes = 0
                with stream_client.query_arrow_stream(query, parameters=parameters) as stream:
                    for chunk in stream:
                        if chunk.num_rows == 0:
                            continue
                        pending.append(chunk)
                        pending_rows += chunk.num_rows
                        pending_bytes += chunk.nbytes
                        if pending_rows >= YIELD_TARGET_ROWS or pending_bytes >= YIELD_TARGET_BYTES:
                            yield pa.Table.from_batches(pending)
                            pending = []
                            pending_rows = 0
                            pending_bytes = 0

                if pending:
                    yield pa.Table.from_batches(pending)
            finally:
                stream_client.close()

    name = NamingConvention().normalize_identifier(table_name)

    return SourceResponse(
        name=name,
        items=get_rows,
        primary_keys=primary_keys,
        partition_count=partition_settings.partition_count if partition_settings else None,
        partition_size=partition_settings.partition_size if partition_settings else None,
        rows_to_sync=rows_to_sync,
        has_duplicate_primary_keys=has_duplicate_primary_keys,
    )
