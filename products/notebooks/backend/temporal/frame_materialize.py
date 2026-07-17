"""Temporal workflow/activity that materializes an SQLV2 frame into the object store.

The data plane dispatches this for `delivery: "object"` requests (whole-frame python-node
inputs): the activity prints the HogQL through the guarded executor (team database +
access controls), executes it over the ClickHouse HTTP interface with `FORMAT ArrowStream`,
and relays the raw response bytes into one object-store multipart upload — no pyarrow
decode in the worker, memory bounded by the part buffer. The existing async-query status
machinery carries a pointer (`{"object_key": ...}`) instead of rows; the status endpoint
turns it into a 302 to a presigned GET.

Load protection mirrors the Celery async path (`process_query_task`): a Redis Lua
concurrency limiter gates activity starts (global + per-team), slot exhaustion and
ClickHouse overload raise retryable errors, and Temporal's retry policy provides the
exponential backoff with a hard schedule-to-close deadline. Queries run on the OFFLINE
pool (batch exports' home) as the dedicated `notebooks` ClickHouse user, so a whale
materialization contends with batch work rather than interactive queries, and the user's
server-side profile/quota is a ceiling no application bug can exceed. ClickHouse
`priority` is deliberately not set: every other query runs at priority 0 (unprioritized),
so a nonzero value here would participate in a scheduling class of one.

With NOTEBOOKS_FRAME_STORE_CH_WRITES on (phase 2 of the design doc, default off),
ClickHouse writes the object itself via `INSERT INTO FUNCTION s3(...)` issued through
the pooled native clients (sync_execute): zero result bytes transit the worker, errors
arrive in-band and typed, and the streaming path's EOS-marker check and query_log
recovery are unnecessary. The worker-relay path below stays the default until the
CH-side prerequisites (node → object-store reachability, the writer-identity grants in
the doc's phase-2 security notes) are provisioned per environment.
"""

import time
import uuid
import hashlib
import datetime as dt
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager, suppress
from dataclasses import dataclass
from typing import IO, cast

from django.conf import settings

import structlog
from prometheus_client import Counter, Histogram
from temporalio import activity, common, exceptions, workflow

from posthog.schema import QueryStatus

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings, LimitContext
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.parser import parse_select
from posthog.hogql.query import HogQLQueryExecutor

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import (
    ClickHouseUser,
    get_clickhouse_creds,
    get_kwargs_for_client,
    make_ch_pool,
)
from posthog.clickhouse.client.execute_async import QueryNotFoundError, QueryStatusManager, get_query_status
from posthog.clickhouse.client.limit import ConcurrencyLimitExceeded, RateLimit
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.clickhouse.workload import Workload
from posthog.errors import ExposedCHQueryError, InternalCHQueryError
from posthog.exceptions import (
    ClickHouseEstimatedQueryExecutionTimeTooLong,
    ClickHouseQueryMemoryLimitExceeded,
    ClickHouseQuerySizeExceeded,
    ClickHouseQueryTimeOut,
)
from posthog.exceptions_capture import capture_exception
from posthog.models import Team, User
from posthog.rbac.user_access_control import UserAccessControl
from posthog.storage.object_storage import ObjectStorageError
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.clickhouse import (
    ClickHouseClient,
    ClickHouseMemoryLimitExceededError,
    ClickHouseTooManyBytesError,
    ClickHouseTooManyRowsOrBytesError,
)

from products.notebooks.backend import frame_store

logger = structlog.get_logger(__name__)

# Concurrency slots for materialize jobs — the actual throttle (notebook workflows share
# the general-purpose Temporal queue, so queue slots alone don't cap us). Same Redis Lua
# mechanism that caps process_query_task at 150 global / 10 per team.
MATERIALIZE_GLOBAL_CONCURRENCY = 10
MATERIALIZE_PER_TEAM_CONCURRENCY = 2
# Safeguard expiry for a slot whose holder died without releasing; comfortably above the
# activity's schedule-to-close so a live run never loses its slot mid-stream.
_SLOT_TTL_SECONDS = 15 * 60

# Standing per-query caps, printed into the SQL's SETTINGS clause. max_execution_time is
# raised to HOGQL_INCREASED_MAX_EXECUTION_TIME by the NOTEBOOK_MATERIALIZE limit context.
_MAX_BYTES_TO_READ = 50_000_000_000  # 50GB scan budget, the logs-queries precedent
_MAX_THREADS = 16  # below interactive traffic (the API query-service cap is 60)
# Output-side cap (applied as a query setting on the HTTP request): row/scan caps don't
# bound the result — `repeat('x', 10000)` over 500k rows makes a ~5GB object from a
# near-zero scan. This bounds object size, storage/bandwidth abuse, and what the kernel
# later decodes into pandas. Overflow throws (never silently truncates).
_MAX_RESULT_BYTES = 2_000_000_000  # 2GB, tier 1

# Client-side timeouts on the ClickHouse stream. Temporal cannot interrupt a sync activity
# thread, so without a read timeout a half-open connection would pin the thread (and its
# concurrency slot) until OS-level TCP gives up — far past every deadline. The read timeout
# bounds each silent gap between socket reads, not the total transfer: a healthy stream of
# any size never trips it. A sparse-filter scan can legitimately produce no output for a
# while, so the value is generous; a false positive is retried like any transient failure.
_STREAM_CONNECT_TIMEOUT_SECONDS = 10.0
_STREAM_READ_TIMEOUT_SECONDS = 120.0

# Socket timeout for the CH-writes INSERT's native client. The pooled clients default to an
# effectively infinite send_receive_timeout in prod, but Temporal cannot interrupt a sync
# activity thread — so a half-open connection during the (minutes-long) INSERT would pin the
# thread and its Redis slot until OS-level TCP gives up, exactly as the streaming path's read
# timeout prevents. Set just above the 600s max_execution_time so the server-side timeout wins
# (returning its error in-band) on a healthy query, while an abandoned connection still unblocks
# shortly after the activity deadline. Clamped in TEST so a misrouted test INSERT fails fast.
_INSERT_SEND_RECEIVE_TIMEOUT_SECONDS = 30 if settings.TEST else 630

# A successful Arrow IPC stream always ends with this 8-byte end-of-stream marker, emitted
# only when the writer finalizes cleanly. ClickHouse streams `200 OK` before execution
# finishes, so a mid-stream failure can't change the status code — depending on version it
# breaks the chunked encoding (the read raises) or appends exception text and closes the
# body cleanly. The marker check catches the clean-close case (and truncation at a batch
# boundary), which would otherwise store a corrupt object and finalize as succeeded.
_ARROW_STREAM_EOS_MARKER = b"\xff\xff\xff\xff\x00\x00\x00\x00"

# system.query_log flushes every ~7.5s, so error recovery after a stream failure polls a
# few times. Only runs on the failure path.
_QUERY_LOG_LOOKUP_ATTEMPTS = 3
_QUERY_LOG_LOOKUP_INTERVAL_SECONDS = 4.0

_RESOURCE_BUDGET_MESSAGE = (
    "This query exceeds the frame materialization limits (scan or memory budget). Narrow it and re-run."
)
_TIME_BUDGET_MESSAGE = "The query hit the frame materialization time limit. Narrow it and re-run."
_QUERY_SIZE_MESSAGE = "The query is too large to materialize. Simplify it (e.g. smaller IN lists) and re-run."
_RESULT_SIZE_MESSAGE = (
    "The materialized result is too large (over the frame size budget). "
    "Select fewer columns or aggregate before materializing."
)
_MID_STREAM_ERROR_MESSAGE = "The query failed while its result was streaming. Adjust it and re-run."
# ClickHouse exception codes worth a specific user-facing message when a query dies
# mid-stream: 158 TOO_MANY_ROWS, 241 MEMORY_LIMIT_EXCEEDED, 307 TOO_MANY_BYTES,
# 159 TIMEOUT_EXCEEDED, 160 TOO_SLOW, 396 TOO_MANY_ROWS_OR_BYTES (the result-bytes cap).
_MID_STREAM_MESSAGES_BY_CODE = {
    158: _RESOURCE_BUDGET_MESSAGE,
    241: _RESOURCE_BUDGET_MESSAGE,
    307: _RESOURCE_BUDGET_MESSAGE,
    159: _TIME_BUDGET_MESSAGE,
    160: _TIME_BUDGET_MESSAGE,
    396: _RESULT_SIZE_MESSAGE,
}
# Codes that do NOT mean the query itself is doomed: 209 SOCKET_TIMEOUT and 210
# NETWORK_ERROR are transport failures, and 394 QUERY_WAS_CANCELLED is what our own
# abandonment produces (a read timeout closes the connection and
# cancel_http_readonly_queries_on_client_close kills the query). All retry on a fresh
# connection instead of failing the cell.
_TRANSIENT_MID_STREAM_CODES = frozenset({209, 210, 394})

FRAME_MATERIALIZATIONS_STARTED_COUNTER = Counter(
    "posthog_notebooks_frame_materializations_started",
    "Number of notebook frame materialize activity attempts started.",
    # Both fallbacks (default creds, online URL) are deliberate and silent, so the labels
    # are the only signal distinguishing "dedicated user on the offline pool engaged"
    # from "provisioning gap, still running as default against interactive nodes". `mode`
    # separates the worker-relay path from the CH-writes path so a flag rollout is legible.
    labelnames=["ch_user", "pool", "mode"],
)
FRAME_MATERIALIZATIONS_FINISHED_COUNTER = Counter(
    "posthog_notebooks_frame_materializations_finished",
    "Number of notebook frame materialize jobs reaching a terminal state.",
    labelnames=["outcome", "mode"],
)
FRAME_MATERIALIZATION_DEDUP_COUNTER = Counter(
    "posthog_notebooks_frame_materializations_deduplicated",
    "Number of materialize requests that joined an identical in-flight job.",
)
FRAME_OBJECT_BYTES_HISTOGRAM = Histogram(
    "posthog_notebooks_frame_object_bytes",
    "Size of stored frame objects in bytes.",
    buckets=[1e5, 1e6, 1e7, 5e7, 1e8, 5e8, 1e9, 5e9],
)
FRAME_MATERIALIZE_SECONDS_HISTOGRAM = Histogram(
    "posthog_notebooks_frame_materialize_seconds",
    "End-to-end wall-clock duration of a successful materialize (print + ClickHouse + upload).",
    buckets=[1, 5, 15, 30, 60, 120, 300, 600],
)
# On the streaming path these two are complementary slices of the relay's wall clock: which
# side the thread was blocked on tells us whether ClickHouse production or object-store
# ingestion is the bottleneck. On the CH-writes path there is no relay — `clickhouse_seconds`
# is the whole INSERT (execution + CH-side S3 upload) and no upload half is emitted — so the
# `mode` label keeps the two distributions from being averaged together.
FRAME_CLICKHOUSE_SECONDS_HISTOGRAM = Histogram(
    "posthog_notebooks_frame_clickhouse_seconds",
    "Time a successful materialize spent on ClickHouse. mode=streaming: response headers plus body reads. "
    "mode=ch_writes: the whole INSERT INTO s3 wall clock (execution plus CH-side upload).",
    buckets=[0.5, 1, 5, 15, 30, 60, 120, 300, 600],
    labelnames=["mode"],
)
FRAME_UPLOAD_SECONDS_HISTOGRAM = Histogram(
    "posthog_notebooks_frame_upload_seconds",
    "Time a successful materialize spent blocked on the object-store side of the relay (part handoff and S3 backpressure).",
    buckets=[0.5, 1, 5, 15, 30, 60, 120, 300, 600],
)


@dataclass
class FrameMaterializeInputs:
    query_id: str
    team_id: int
    notebook_short_id: str
    user_id: int | None
    # The wrapped HogQL (outer LIMIT/OFFSET applied by the data plane). Only ever executed
    # after printing through the guarded HogQL executor — never handed to ClickHouse raw.
    query: str
    query_hash: str
    cache_key: str


__GLOBAL_LIMITER: RateLimit | None = None
__PER_TEAM_LIMITER: RateLimit | None = None


def _get_global_limiter() -> RateLimit:
    global __GLOBAL_LIMITER
    if __GLOBAL_LIMITER is None:
        __GLOBAL_LIMITER = RateLimit(
            max_concurrency=MATERIALIZE_GLOBAL_CONCURRENCY,
            limit_name="notebooks_materialize_global",
            get_task_name=lambda *args, **kwargs: "notebooks:materialize:global",
            get_task_id=lambda *args, **kwargs: kwargs["task_id"],
            ttl=_SLOT_TTL_SECONDS,
        )
    return __GLOBAL_LIMITER


def _get_per_team_limiter() -> RateLimit:
    global __PER_TEAM_LIMITER
    if __PER_TEAM_LIMITER is None:
        __PER_TEAM_LIMITER = RateLimit(
            max_concurrency=MATERIALIZE_PER_TEAM_CONCURRENCY,
            limit_name="notebooks_materialize_per_team",
            get_task_name=lambda *args, **kwargs: f"notebooks:materialize:per-team:{kwargs['team_id']}",
            get_task_id=lambda *args, **kwargs: kwargs["task_id"],
            ttl=_SLOT_TTL_SECONDS,
        )
    return __PER_TEAM_LIMITER


@contextmanager
def _materialize_slots(team_id: int, task_id: str) -> Iterator[None]:
    """Hold one global and one per-team concurrency slot; raise ConcurrencyLimitExceeded when full.

    The raise is retryable on purpose — Temporal's retry policy is the backoff loop.
    """
    global_limiter = _get_global_limiter()
    team_limiter = _get_per_team_limiter()
    global_key, global_task = global_limiter.use(task_id=f"{task_id}:global", team_id=team_id)
    team_key = team_task = None
    try:
        team_key, team_task = team_limiter.use(task_id=f"{task_id}:team", team_id=team_id)
        yield
    finally:
        # Release each slot independently: a Redis blip releasing the team slot must not
        # skip the global release and leak a global slot until its 15-minute TTL.
        if team_key and team_task:
            with suppress(Exception):
                team_limiter.release(team_key, team_task)
        if global_key and global_task:
            with suppress(Exception):
                global_limiter.release(global_key, global_task)


def _generate_sql(
    team: Team,
    user: User | None,
    query: "str | ast.SelectQuery | ast.SelectSetQuery",
    *,
    output_format: str | None,
) -> tuple[str, dict[str, object]]:
    """Print HogQL to guarded ClickHouse SQL with the standing caps applied."""
    executor = HogQLQueryExecutor(
        query=query,
        team=team,
        user=user,
        user_access_control=UserAccessControl(user=user, team=team) if user else None,
        limit_context=LimitContext.NOTEBOOK_MATERIALIZE,
        settings=HogQLGlobalSettings(max_bytes_to_read=_MAX_BYTES_TO_READ, max_threads=_MAX_THREADS),
        pretty=False,
    )
    if output_format:
        executor.context.output_format = output_format
    sql, context = executor.generate_clickhouse_sql()
    return sql, context.values


_DescribeFn = Callable[[str, dict[str, object]], list[tuple[str, str]]]


def _describe_columns(
    client: ClickHouseClient, printed_sql: str, values: dict[str, object], ch_query_id: str
) -> list[tuple[str, str]]:
    """Return the printed query's output columns as (name, ClickHouse type) pairs."""
    describe_sql = f"DESCRIBE TABLE ({printed_sql}) FORMAT TabSeparatedRaw"
    with client.post_query(
        describe_sql,
        query_parameters=values,
        query_id=f"{ch_query_id}_describe",
        timeout=(_STREAM_CONNECT_TIMEOUT_SECONDS, 30.0),
    ) as response:
        text = response.text
    columns: list[tuple[str, str]] = []
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[0]:
            columns.append((parts[0], parts[1]))
    return columns


def _describe_columns_pooled(printed_sql: str, values: dict[str, object], team_id: int) -> list[tuple[str, str]]:
    """`_describe_columns` for the CH-writes path — pooled native client, same routing as the INSERT.

    Bounded socket timeout for the same reason the INSERT is (a half-open connection must not
    pin the uninterruptible activity thread), though a DESCRIBE is metadata-only and fast.
    """
    with _bounded_offline_client(team_id) as client:
        # nosemgrep: clickhouse-fstring-param-audit - printed_sql is HogQL-compiled by the guarded printer, not user input
        rows = sync_execute(
            f"DESCRIBE TABLE ({printed_sql})",
            values,
            workload=Workload.OFFLINE,
            ch_user=ClickHouseUser.NOTEBOOKS,
            team_id=team_id,
            sync_client=client,
        )
    return [(str(row[0]), str(row[1])) for row in rows]


def _stringify_function_for(ch_type: str) -> str | None:
    """The conversion a column needs so ClickHouse's Arrow output stays kernel-friendly.

    CH emits UUID/FixedString/Enum/IP columns as Arrow (fixed-size) binary — pandas then
    holds raw bytes, which break JSON previews and read as bytes in user code (the inline
    path always delivered them as strings). Mirrors the data-modeling materializer's
    conversion table; containers are left native (a stringified array changes its shape).
    """
    lowered = ch_type.lower()
    if lowered.startswith(("array", "map", "tuple")):
        return None
    if "nullable(nothing)" in lowered:
        return "toNullableString"
    if (
        any(marker in lowered for marker in ("uuid", "enum", "ipv4", "ipv6", "fixedstring"))
        or lowered.startswith("json")
        or "object(" in lowered
    ):
        return "toString"
    return None


def _print_clickhouse_sql(
    describe: _DescribeFn, team: Team, user: User | None, query: str, *, output_format: str | None
) -> tuple[str, dict[str, object]]:
    """Print the HogQL to guarded ClickHouse SQL with the standing caps.

    Two passes when needed (the data-modeling recipe): print once, DESCRIBE the printed
    query (metadata only — no execution), and if any output column would leave ClickHouse
    as Arrow binary, wrap the query so those columns are stringified, then print the
    wrapper. Field names go through the HogQL AST/printer, never string splicing.
    `output_format` is "ArrowStream" for the streaming path; None for the CH-writes path,
    where the s3() function argument defines the object format and a FORMAT clause would
    be invalid inside the INSERT.
    """
    plain_sql, plain_values = _generate_sql(team, user, query, output_format=None)
    described = describe(plain_sql, plain_values)
    conversions = [(name, _stringify_function_for(ch_type)) for name, ch_type in described]
    if not any(function for _name, function in conversions):
        if output_format is None:
            return plain_sql, plain_values
        return _generate_sql(team, user, query, output_format=output_format)
    select_fields: list[ast.Expr] = [
        ast.Alias(expr=ast.Call(name=function, args=[ast.Field(chain=[name])]), alias=name)
        if function
        else ast.Field(chain=[name])
        for name, function in conversions
    ]
    stringified = ast.SelectQuery(select=select_fields, select_from=ast.JoinExpr(table=parse_select(query)))
    return _generate_sql(team, user, stringified, output_format=output_format)


class FrameTooLargeError(Exception):
    """The CH-written object exceeds the frame size budget (enforced post-write)."""


def _frame_s3_url(key: str) -> str:
    """The s3() target URL for the frames bucket, reachable from the ClickHouse cluster.

    Mirrors the identity_matching CH-side writer: when a cluster-reachable endpoint is set
    (dev/test/self-hosted S3-compatible storage) use a path-style URL including the bucket;
    on prod the endpoint is empty and the cluster reaches AWS S3 over its IAM role, so emit a
    virtual-hosted HTTPS URL. Reusing OBJECT_STORAGE_ENDPOINT directly would break prod (it is
    empty there → a scheme-less URL CH rejects) and mis-route dev (it may be an app-only host
    CH can't reach), which is why this has its own NOTEBOOKS_FRAME_STORE_S3_ENDPOINT knob.
    """
    bucket = settings.NOTEBOOKS_FRAME_STORE_S3_BUCKET
    endpoint = settings.NOTEBOOKS_FRAME_STORE_S3_ENDPOINT
    if endpoint:
        return f"{endpoint}/{bucket}/{key}"
    return f"https://{bucket}.s3.{settings.NOTEBOOKS_FRAME_STORE_S3_REGION}.amazonaws.com/{key}"


def _insert_into_s3_sql(printed_sql: str, key: str) -> tuple[str, dict[str, object]]:
    """Wrap the printed SELECT in the CH-side object write (design doc phase 2).

    The s3() endpoint/bucket/key and any credentials are bound as query parameters, not
    spliced as literals: sync_execute runs one `%`-substitution pass over the whole
    statement (clickhouse-driver's `escape_param`), so binding gives correct CH-literal
    escaping for free and — unlike hand-rolled quoting — a `%` or quote in an
    operator-configured endpoint/bucket/credential can neither corrupt that format pass nor
    reach the credential zone. The key is already charset-validated by build_frame_key. The
    SELECT is the same guarded-printer artifact the streaming path executes verbatim,
    printed without a FORMAT clause (the s3() argument defines the object format).
    Credentials are emitted only for the path-style (endpoint-set) case; on prod the empty
    endpoint yields a virtual-hosted URL and the cluster authenticates via its IAM role, so
    no secret is ever interpolated into a statement that lands in system.query_log.
    """
    endpoint = settings.NOTEBOOKS_FRAME_STORE_S3_ENDPOINT
    params: dict[str, object] = {"_nb_s3_url": _frame_s3_url(key)}
    target = ["%(_nb_s3_url)s"]
    if endpoint and settings.OBJECT_STORAGE_ACCESS_KEY_ID and settings.OBJECT_STORAGE_SECRET_ACCESS_KEY:
        params["_nb_s3_key"] = settings.OBJECT_STORAGE_ACCESS_KEY_ID
        params["_nb_s3_secret"] = settings.OBJECT_STORAGE_SECRET_ACCESS_KEY
        target.append("%(_nb_s3_key)s")
        target.append("%(_nb_s3_secret)s")
    target.append("'ArrowStream'")
    return f"INSERT INTO FUNCTION s3({', '.join(target)})\n{printed_sql}", params


def _bounded_offline_client(team_id: int) -> AbstractContextManager:
    """A native client for the CH-writes path with a finite socket timeout.

    `sync_execute`'s default pooled client has an effectively infinite send/receive timeout
    in prod, which would let a half-open connection pin the (uninterruptible) activity
    thread. Route through a dedicated pool that shares the offline-host + notebooks-user
    routing but caps the socket timeout just above max_execution_time. `make_ch_pool` is
    cached, so this is one extra pool per (offline, notebooks) combination, not per call.
    (Note: sync_execute enters the client as its own context manager and disconnects it on
    exit, so connections aren't kept warm across calls — the pool's value here is the bounded
    timeout, not connection reuse. Negligible at this path's volume: one reconnect per
    materialization, dwarfed by the INSERT itself.)
    """
    kwargs = get_kwargs_for_client(workload=Workload.OFFLINE, team_id=team_id, ch_user=ClickHouseUser.NOTEBOOKS)
    pool = make_ch_pool(send_receive_timeout=_INSERT_SEND_RECEIVE_TIMEOUT_SECONDS, **kwargs)
    return pool.get_client()


def _execute_insert_to_s3(team: Team, user: User | None, query: str, key: str) -> tuple[int, float]:
    """Materialize by having ClickHouse write the object itself; return (bytes, CH seconds).

    Runs through the pooled native clients (sync_execute) with a bounded socket timeout:
    offline workload and hedging hygiene come from the workload routing, errors arrive
    in-band and typed, and no result bytes transit the worker — so the streaming path's
    EOS-marker check and query_log recovery have no equivalent here.
    """
    printed_sql, values = _print_clickhouse_sql(
        lambda sql, sql_values: _describe_columns_pooled(sql, sql_values, team.pk),
        team,
        user,
        query,
        output_format=None,
    )
    insert_sql, s3_params = _insert_into_s3_sql(printed_sql, key)
    insert_values = {**values, **s3_params}
    ch_settings = {
        # Idempotent retries: a re-attempt overwrites the object, never appends.
        "s3_truncate_on_insert": 1,
        # The client param the streaming path sets on its HTTP client; without it the
        # Arrow file CH writes carries strings as binary and pandas sees bytes.
        "output_format_arrow_string_as_string": 1,
    }
    write_started_at = dt.datetime.now(dt.UTC)
    query_started = time.perf_counter()
    with _bounded_offline_client(team.pk) as client:
        sync_execute(
            insert_sql,
            insert_values,
            settings=ch_settings,
            workload=Workload.OFFLINE,
            ch_user=ClickHouseUser.NOTEBOOKS,
            team_id=team.pk,
            sync_client=client,
        )
    clickhouse_seconds = time.perf_counter() - query_started
    # Freshness margin covers worker↔object-store clock skew without admitting a
    # hours-stale prior-run object (see stat_frame).
    object_bytes = frame_store.stat_frame(key, written_after=write_started_at - dt.timedelta(minutes=5))
    if object_bytes > _MAX_RESULT_BYTES:
        # max_result_bytes bounds result sets returned to a client, not an INSERT's sink —
        # the output cap has to be enforced after the fact on this path. The bytes are
        # ours (this attempt just wrote them), so deleting is safe.
        with suppress(ObjectStorageError):
            frame_store.delete_frame(key)
        raise FrameTooLargeError(f"Frame object is {object_bytes} bytes, over the {_MAX_RESULT_BYTES} budget")
    return object_bytes, clickhouse_seconds


def _finalize_status(
    manager: QueryStatusManager,
    inputs: FrameMaterializeInputs,
    *,
    results: dict[str, object] | None = None,
    error_message: str | None = None,
) -> None:
    """Write the terminal query status and release the dedup mapping."""
    try:
        status = manager.get_query_status()
        if status.complete:
            # First terminal write wins. A slow zombie attempt (one that outlived its Temporal
            # deadline while a retry — or mark-failed — already finalized) must not overwrite
            # what the user has seen: not a success flipping a recorded failure, and not a late
            # error clobbering a genuinely-materialized frame that still exists at the key.
            return
    except QueryNotFoundError:
        status = QueryStatus(id=inputs.query_id, team_id=inputs.team_id)
    status.complete = True
    status.error = error_message is not None
    status.error_message = error_message
    status.results = results
    status.end_time = dt.datetime.now(dt.UTC)
    manager.store_query_status(status)
    manager.unregister_cache_key_mapping(inputs.cache_key)


class MidStreamQueryError(Exception):
    """The ClickHouse response body ended without the Arrow end-of-stream marker."""


class _ArrowTailReader:
    """File-like relay that remembers the final bytes of the stream it forwards.

    Lets the upload stay a bounded-memory passthrough while still allowing an
    end-of-stream integrity check once the body is fully drained. Also accumulates the
    time spent blocked in reads, so the ClickHouse and upload halves of the relay's wall
    clock can be reported separately.
    """

    def __init__(self, fileobj: IO[bytes]) -> None:
        self._fileobj = fileobj
        self.tail = b""
        self.read_seconds = 0.0

    def read(self, size: int = -1) -> bytes:
        read_started = time.perf_counter()
        chunk = self._fileobj.read(size)
        self.read_seconds += time.perf_counter() - read_started
        if chunk:
            self.tail = (self.tail + chunk)[-len(_ARROW_STREAM_EOS_MARKER) :]
        return chunk


def _fetch_query_log_exception(ch_query_id: str) -> tuple[int, str] | None:
    """Best-effort lookup of a failed query's exception in system.query_log.

    Returns (exception_code, exception_message), or None when no exception entry appears
    (log not flushed within the polling window, or the query actually finished — e.g. the
    failure was storage-side or an intermediary truncated the response). Never raises:
    recovery must not mask the original stream failure.
    """
    for lookup_attempt in range(_QUERY_LOG_LOOKUP_ATTEMPTS):
        if lookup_attempt:
            time.sleep(_QUERY_LOG_LOOKUP_INTERVAL_SECONDS)
        try:
            # Deliberately the default CH principal, not the notebooks user: recovery must
            # not share fate with the failing subject (a quota/grant condition that killed
            # the query would reject its own diagnosis too, silently turning terminal
            # failures into whale re-executions). Batch exports run this exact lookup as
            # the default user against offline-executed queries, so both the grants and
            # the clusterAllReplicas topology are production-proven. It's three LIMIT 1
            # metadata reads on the failure path — pool placement is irrelevant.
            rows = sync_execute(
                """
                SELECT exception_code, exception
                FROM clusterAllReplicas(%(cluster)s, system.query_log)
                WHERE query_id = %(query_id)s
                    AND exception_code != 0
                    AND event_date >= yesterday() AND event_time >= now() - INTERVAL 1 HOUR
                ORDER BY event_time DESC
                LIMIT 1
                """,
                {"cluster": settings.CLICKHOUSE_CLUSTER, "query_id": ch_query_id},
            )
        except Exception as exc:
            # A broken lookup silently downgrades error classification (deterministic
            # failures become retries), so it must be visible even though it can't raise.
            logger.warning("notebook_frame_query_log_lookup_failed", ch_query_id=ch_query_id, error=str(exc))
            return None
        if rows:
            return int(rows[0][0]), str(rows[0][1])
    return None


def materialize_frame(inputs: FrameMaterializeInputs) -> str:
    """Stream the frame's ClickHouse result into the object store; return the object key.

    Raises on failure so Temporal retries per policy; user-safe HogQL errors are written
    to the query status here (terminal — retrying can't fix a bad query) before raising.
    """
    # Dedicated `notebooks` CH user (server-side profile/quota backstop no application
    # bug can exceed); falls back to the default credentials where not provisioned.
    # sync_execute on the CH-writes path resolves the same creds via the same enum.
    ch_user, ch_password = get_clickhouse_creds(ClickHouseUser.NOTEBOOKS)
    resolved_default_user = ch_user == settings.CLICKHOUSE_USER
    ch_writes = bool(settings.NOTEBOOKS_FRAME_STORE_CH_WRITES)
    if ch_writes and resolved_default_user and not settings.DEBUG and not settings.TEST:
        # Fail closed in a real deployment: the CH-writes statement is write-capable
        # (readonly=0 + S3 egress), so running it as the broad default user — when the flag
        # was flipped before the confined `notebooks` writer identity was provisioned —
        # defeats the whole containment model. Degrade to the read-only streaming path (which
        # is correct as any user) rather than hand a write+egress statement to the default
        # account. Dev/test keep CH-writes on the default user so the path stays exercisable.
        logger.warning(
            "notebook_frame_ch_writes_missing_writer_identity",
            team_id=inputs.team_id,
            query_id=inputs.query_id,
        )
        ch_writes = False
    mode = "ch_writes" if ch_writes else "streaming"
    # The two paths route offline on different predicates: sync_execute keys on the
    # offline host being set at all; the HTTP client's URL collapses to online under
    # TEST/DEBUG too. The label must report the path actually taken.
    offline = (
        settings.CLICKHOUSE_OFFLINE_CLUSTER_HOST is not None
        if ch_writes
        else settings.CLICKHOUSE_OFFLINE_HTTP_URL != settings.CLICKHOUSE_HTTP_URL
    )
    FRAME_MATERIALIZATIONS_STARTED_COUNTER.labels(
        ch_user="notebooks" if not resolved_default_user else "default",
        pool="offline" if offline else "online",
        mode=mode,
    ).inc()
    manager = QueryStatusManager(inputs.query_id, inputs.team_id)
    team = Team.objects.get(id=inputs.team_id)
    user = User.objects.filter(id=inputs.user_id).first() if inputs.user_id else None
    key = frame_store.build_frame_key(inputs.team_id, inputs.notebook_short_id, inputs.query_hash)

    attempt = activity.info().attempt if activity.in_activity() else 1
    started_at = dt.datetime.now(dt.UTC)

    try:
        status = manager.get_query_status()
        if status.complete:
            if status.error:
                raise exceptions.ApplicationError("Materialization already failed", non_retryable=True)
            return key  # a previous attempt already finished (e.g. retry after a lost ack)
        status.pickup_time = started_at
        manager.store_query_status(status)
    except QueryNotFoundError:
        pass  # status expired mid-flight; still produce the object so the run can be retried

    with tags_context(
        product=Product.NOTEBOOKS,
        feature=Feature.QUERY,
        team_id=inputs.team_id,
        user_id=inputs.user_id,
        client_query_id=inputs.query_id,
    ):
        # Per-attempt CH query id: a retried attempt must not collide with a predecessor
        # ClickHouse may still be draining, and the failure path looks the id up in
        # system.query_log to recover the real error.
        ch_query_id = f"{inputs.query_id}_{attempt}"
        try:
            with _materialize_slots(inputs.team_id, inputs.query_id):
                # Everything that touches ClickHouse or Postgres lives inside the slots —
                # including printing, whose DESCRIBE round-trip would otherwise run ungated
                # on every retry attempt of a slot-blocked job, i.e. exactly when the
                # limiter is saturated. A blocked attempt now costs one Redis eval and
                # nothing else; the extra slot-hold (~100-300ms of print/describe) is noise
                # against the stream duration.
                if ch_writes:
                    object_bytes, clickhouse_seconds = _execute_insert_to_s3(team, user, inputs.query, key)
                    upload_seconds = None  # CH performs the upload; the relay split doesn't exist
                else:
                    client = ClickHouseClient(
                        # The offline pool (batch exports' home): a whale materialization must
                        # not contend with interactive queries. Falls back to the online URL
                        # where no offline cluster exists (EU, self-hosted, dev/test).
                        url=settings.CLICKHOUSE_OFFLINE_HTTP_URL,
                        user=ch_user,
                        password=ch_password,
                        database=settings.CLICKHOUSE_DATABASE,
                        output_format_arrow_string_as_string="true",
                        cancel_http_readonly_queries_on_client_close=1,
                        # sync_execute's offline hygiene: without this, distributed subqueries
                        # of a saturated offline query hedge onto online replicas — bleeding
                        # the whale back into the interactive pool this move exists to protect.
                        use_hedged_requests="0",
                        max_result_bytes=_MAX_RESULT_BYTES,
                        result_overflow_mode="throw",
                    )
                    printed_sql, context_values = _print_clickhouse_sql(
                        lambda sql, sql_values: _describe_columns(client, sql, sql_values, ch_query_id),
                        team,
                        user,
                        inputs.query,
                        output_format="ArrowStream",
                    )
                    query_started = time.perf_counter()
                    with client.post_query(
                        printed_sql,
                        query_parameters=context_values,
                        query_id=ch_query_id,
                        timeout=(_STREAM_CONNECT_TIMEOUT_SECONDS, _STREAM_READ_TIMEOUT_SECONDS),
                    ) as response:
                        headers_received = time.perf_counter()
                        # A torn stream aborts the multipart upload (upload_fileobj), so no
                        # partial object is ever left behind — nothing to clean up on failure.
                        # The key is deterministic per (team, notebook, user, query), so we must
                        # NOT delete it on generic error: that would destroy an object an earlier
                        # successful run's still-live status/presigned URL points at.
                        relay = _ArrowTailReader(response.raw)
                        # boto3's upload_fileobj duck-types read(); the relay is not a full IO[bytes].
                        object_bytes = frame_store.write_stream(key, cast("IO[bytes]", relay))
                        relay_seconds = time.perf_counter() - headers_received
                        if relay.tail != _ARROW_STREAM_EOS_MARKER:
                            # ClickHouse failed mid-stream but closed the body cleanly (or an
                            # intermediary truncated it at a batch boundary): the bytes we just
                            # stored are corrupt and, at a deterministic key, could be served to
                            # an earlier status's presigned fetch — remove them before failing.
                            with suppress(ObjectStorageError):
                                frame_store.delete_frame(key)
                            raise MidStreamQueryError("ClickHouse stream ended without the Arrow end-of-stream marker")
                    # ClickHouse time = waiting for response headers plus every blocking body
                    # read; upload time = the rest of the relay's wall clock (part handoff and
                    # S3 backpressure).
                    clickhouse_seconds = (headers_received - query_started) + relay.read_seconds
                    upload_seconds = max(0.0, relay_seconds - relay.read_seconds)
        except ConcurrencyLimitExceeded:
            raise  # retryable — Temporal backs off and re-attempts
        except ExposedHogQLError as exc:
            # User-safe and terminal: surface the message through the poll, don't retry —
            # a bad query cannot succeed on a second attempt.
            _finalize_status(manager, inputs, error_message=str(exc))
            FRAME_MATERIALIZATIONS_FINISHED_COUNTER.labels(outcome="failed", mode=mode).inc()
            raise exceptions.ApplicationError(str(exc), non_retryable=True) from exc
        except FrameTooLargeError as exc:
            # The CH-writes analog of the result-bytes cap: deterministic, so terminal.
            _finalize_status(manager, inputs, error_message=_RESULT_SIZE_MESSAGE)
            FRAME_MATERIALIZATIONS_FINISHED_COUNTER.labels(outcome="failed", mode=mode).inc()
            raise exceptions.ApplicationError(_RESULT_SIZE_MESSAGE, non_retryable=True) from exc
        except (
            ClickHouseMemoryLimitExceededError,
            ClickHouseTooManyBytesError,
            ClickHouseTooManyRowsOrBytesError,
        ) as exc:
            # Deterministic budget failures ClickHouse rejects before streaming.
            # Re-executing the same heavy query just burns ClickHouse and ends on the same
            # wall: terminal, with a user-facing message.
            message = (
                _RESULT_SIZE_MESSAGE if isinstance(exc, ClickHouseTooManyRowsOrBytesError) else _RESOURCE_BUDGET_MESSAGE
            )
            _finalize_status(manager, inputs, error_message=message)
            FRAME_MATERIALIZATIONS_FINISHED_COUNTER.labels(outcome="failed", mode=mode).inc()
            raise exceptions.ApplicationError(message, non_retryable=True) from exc
        except (
            ClickHouseQueryMemoryLimitExceeded,
            ClickHouseQueryTimeOut,
            ClickHouseEstimatedQueryExecutionTimeTooLong,
            ClickHouseQuerySizeExceeded,
        ) as exc:
            # CH-writes path: sync_execute rewraps some codes (241 MEMORY, 159 TIMEOUT, 160
            # TOO_SLOW, and the query-size overflow) as APIException subclasses — NOT
            # InternalCHQueryError — so they must be caught here or they'd fall through to a
            # retry. All deterministic, so terminal with an actionable message.
            if isinstance(exc, ClickHouseQuerySizeExceeded):
                message = _QUERY_SIZE_MESSAGE
            elif isinstance(exc, ClickHouseQueryMemoryLimitExceeded):
                message = _RESOURCE_BUDGET_MESSAGE
            else:
                message = _TIME_BUDGET_MESSAGE
            logger.warning(
                "notebook_frame_materialize_insert_budget_error",
                team_id=inputs.team_id,
                query_id=inputs.query_id,
                error_type=type(exc).__name__,
            )
            _finalize_status(manager, inputs, error_message=message)
            FRAME_MATERIALIZATIONS_FINISHED_COUNTER.labels(outcome="failed", mode=mode).inc()
            raise exceptions.ApplicationError(message, non_retryable=True) from exc
        except ExposedCHQueryError as exc:
            # A user-safe ClickHouse query error surfaced at DESCRIBE/execution (e.g.
            # TYPE_MISMATCH, UNKNOWN_FUNCTION) that HogQL didn't catch at print time —
            # deterministic, so terminal with the sanitized message (ExposedCHQueryError.__str__
            # strips the stack trace) rather than 10 pointless re-analyses ending generic.
            message = str(exc)
            _finalize_status(manager, inputs, error_message=message)
            FRAME_MATERIALIZATIONS_FINISHED_COUNTER.labels(outcome="failed", mode=mode).inc()
            raise exceptions.ApplicationError(message, non_retryable=True) from exc
        except InternalCHQueryError as exc:
            # CH-writes path: sync_execute surfaces the query's real error in-band and
            # typed, with its ClickHouse code — no 200-before-failure ambiguity, so the
            # streaming path's query_log recovery has no role here. Known budget codes are
            # deterministic and terminal; anything else retries per policy. (Codes 241/159/160
            # arrive as the APIException subclasses handled just above, not here — this catches
            # 158/307/396 and the like.)
            mapped = _MID_STREAM_MESSAGES_BY_CODE.get(exc.code or 0)
            if mapped is None:
                # Unrecognized code — plausibly transient (network, S3 blip), or a deterministic
                # misconfig (e.g. 164 READONLY if the writer identity wasn't re-provisioned).
                # Retry per policy, but log the code so a retry storm is attributable.
                logger.warning(
                    "notebook_frame_materialize_insert_unmapped_error",
                    team_id=inputs.team_id,
                    query_id=inputs.query_id,
                    exception_code=exc.code,
                )
                raise
            message = mapped
            logger.warning(
                "notebook_frame_materialize_insert_error",
                team_id=inputs.team_id,
                query_id=inputs.query_id,
                exception_code=exc.code,
            )
            _finalize_status(manager, inputs, error_message=message)
            FRAME_MATERIALIZATIONS_FINISHED_COUNTER.labels(outcome="failed", mode=mode).inc()
            raise exceptions.ApplicationError(message, non_retryable=True) from exc
        except frame_store.FrameStoreError as exc:
            # Post-write verification failed: the object is missing or predates this write
            # (see stat_frame). Retryable — a transient object-store blip should re-run — but
            # log it, because a deterministic cause (CH wrote to a store the app can't read,
            # endpoint/bucket skew) would otherwise re-scan the whale silently up to 10 times.
            logger.warning(
                "notebook_frame_materialize_object_unverified",
                team_id=inputs.team_id,
                query_id=inputs.query_id,
                error=str(exc),
            )
            raise
        except (MidStreamQueryError, ObjectStorageError) as exc:
            if ch_writes:
                # The query_log recovery below is streaming-only: it looks up ch_query_id,
                # which the CH-writes path never attaches (sync_execute mints its own id). Any
                # ObjectStorageError that reaches here on the CH-writes path is transient —
                # retry rather than chase a nonexistent log entry.
                raise
            # The stream failed after ClickHouse already sent its 200 — either the chunked
            # read tore (multipart aborted, no object; the read error is opaque) or the body
            # closed cleanly without the EOS marker (corrupt object, deleted above). Recover
            # the real error from the query log: a query-side exception is deterministic for
            # an identical retry, so surface it and stop instead of re-running the scan.
            logged = _fetch_query_log_exception(ch_query_id)
            if logged is None:
                raise  # no query-side exception found — plausibly transient, retry per policy
            exception_code, exception_message = logged
            if exception_code in _TRANSIENT_MID_STREAM_CODES:
                raise  # transport failure or our own read-timeout cancellation — retry per policy
            # The raw ClickHouse message may embed query fragments — log it, don't expose it.
            logger.warning(
                "notebook_frame_materialize_mid_stream_error",
                team_id=inputs.team_id,
                query_id=inputs.query_id,
                exception_code=exception_code,
                error=exception_message,
            )
            message = _MID_STREAM_MESSAGES_BY_CODE.get(exception_code, _MID_STREAM_ERROR_MESSAGE)
            _finalize_status(manager, inputs, error_message=message)
            FRAME_MATERIALIZATIONS_FINISHED_COUNTER.labels(outcome="failed", mode=mode).inc()
            raise exceptions.ApplicationError(message, non_retryable=True) from exc

    _finalize_status(manager, inputs, results={"object_key": key})
    FRAME_MATERIALIZATIONS_FINISHED_COUNTER.labels(outcome="succeeded", mode=mode).inc()
    FRAME_OBJECT_BYTES_HISTOGRAM.observe(object_bytes)
    FRAME_MATERIALIZE_SECONDS_HISTOGRAM.observe((dt.datetime.now(dt.UTC) - started_at).total_seconds())
    FRAME_CLICKHOUSE_SECONDS_HISTOGRAM.labels(mode=mode).observe(clickhouse_seconds)
    if upload_seconds is not None:
        # Only the worker-relay path has an observable upload half; a stream of zeros from
        # the CH-writes path would poison the histogram this split exists to interpret.
        FRAME_UPLOAD_SECONDS_HISTOGRAM.observe(upload_seconds)
    logger.info(
        "notebook_frame_materialized",
        team_id=inputs.team_id,
        notebook_short_id=inputs.notebook_short_id,
        query_id=inputs.query_id,
        object_bytes=object_bytes,
        ch_writes=ch_writes,
        clickhouse_seconds=round(clickhouse_seconds, 3),
        upload_seconds=round(upload_seconds, 3) if upload_seconds is not None else None,
    )
    return key


def mark_frame_materialize_failed(inputs: FrameMaterializeInputs) -> None:
    """Terminal-state safety net once the materialize activity exhausts its retries."""
    manager = QueryStatusManager(inputs.query_id, inputs.team_id)
    try:
        if manager.get_query_status().complete:
            manager.unregister_cache_key_mapping(inputs.cache_key)
            return  # the activity already wrote a terminal state (e.g. a user-safe error)
    except QueryNotFoundError:
        pass
    _finalize_status(manager, inputs, error_message="The frame could not be materialized. Try re-running the cell.")
    mode = "ch_writes" if settings.NOTEBOOKS_FRAME_STORE_CH_WRITES else "streaming"
    FRAME_MATERIALIZATIONS_FINISHED_COUNTER.labels(outcome="failed", mode=mode).inc()


@activity.defn(name="notebook-frame-materialize")
def materialize_frame_activity(inputs: FrameMaterializeInputs) -> str:
    return materialize_frame(inputs)


@activity.defn(name="notebook-frame-materialize-mark-failed")
def mark_frame_materialize_failed_activity(inputs: FrameMaterializeInputs) -> None:
    mark_frame_materialize_failed(inputs)


@workflow.defn(name="notebook-frame-materialize")
class NotebookFrameMaterializeWorkflow(PostHogWorkflow):
    inputs_cls = FrameMaterializeInputs

    @workflow.run
    async def run(self, input: FrameMaterializeInputs) -> None:
        try:
            await workflow.execute_activity(
                materialize_frame_activity,
                input,
                start_to_close_timeout=dt.timedelta(minutes=10),
                # The analog of the Celery path's expires=600: under sustained saturation
                # the job fails with a clear error instead of piling onto ClickHouse.
                schedule_to_close_timeout=dt.timedelta(minutes=10),
                retry_policy=common.RetryPolicy(
                    initial_interval=dt.timedelta(seconds=1),
                    backoff_coefficient=2.0,
                    maximum_interval=dt.timedelta(seconds=10),
                    # Bound the storm: a deterministically-failing heavy query (e.g. a
                    # mid-stream resource overrun that can't be caught up front) must not
                    # re-execute for the full schedule_to_close window. Matches the Celery
                    # async path's max_retries=10.
                    maximum_attempts=10,
                ),
            )
        except Exception:
            await workflow.execute_activity(
                mark_frame_materialize_failed_activity,
                input,
                start_to_close_timeout=dt.timedelta(seconds=30),
                retry_policy=common.RetryPolicy(maximum_attempts=3),
            )
            raise


def enqueue_frame_materialization(
    *,
    team: Team,
    user_id: int | None,
    notebook_short_id: str,
    query: str,
    _test_only_inline: bool = False,
) -> QueryStatus:
    """Register a materialize job for `query` and dispatch the workflow; returns its status.

    Dedup happens here: identical concurrent materializations (same team + user + query)
    join the in-flight job through the async manager's running-query mapping instead of
    stacking ClickHouse load.

    The hash folds in `user_id`: the printed SQL applies the enqueuing user's access
    controls, so two differently-permissioned users in one team must NOT share a job or an
    object — otherwise a restricted user could join a privileged user's in-flight job and
    read rows their own access controls would deny (and their objects would collide on the
    same key). Scoping the hash by user keeps both the dedup mapping and the object key
    per-user within the team.
    """
    query_hash = hashlib.sha256(f"{user_id}:{query}".encode()).hexdigest()
    cache_key = f"notebook-frame:{team.id}:{query_hash}"
    query_id = uuid.uuid4().hex
    manager = QueryStatusManager(query_id, team.id)

    try:
        existing_query_id = manager.get_running_query_by_cache_key(cache_key)
        if existing_query_id:
            existing_status = get_query_status(team.id, existing_query_id)
            if not existing_status.complete:
                FRAME_MATERIALIZATION_DEDUP_COUNTER.inc()
                return existing_status
            # The mapped job finished — clean up the stale mapping and enqueue a new one.
            manager.unregister_cache_key_mapping(cache_key)
    except QueryNotFoundError:
        manager.unregister_cache_key_mapping(cache_key)
    except Exception as exc:
        capture_exception(exc, {"cache_key": cache_key})

    query_status = QueryStatus(id=query_id, team_id=team.id, start_time=dt.datetime.now(dt.UTC))
    manager.store_query_status(query_status)
    manager.register_cache_key_mapping(cache_key)

    inputs = FrameMaterializeInputs(
        query_id=query_id,
        team_id=team.id,
        notebook_short_id=notebook_short_id,
        user_id=user_id,
        query=query,
        query_hash=query_hash,
        cache_key=cache_key,
    )
    if _test_only_inline:
        # Tests have no Temporal worker; mirror the workflow's failure handling inline.
        try:
            materialize_frame(inputs)
        except Exception:
            mark_frame_materialize_failed(inputs)
    else:
        # Deferred: client.py imports FrameMaterializeInputs from this module, so a
        # module-level import back at it would be circular.
        from products.notebooks.backend.temporal.client import start_frame_materialize_workflow  # noqa: PLC0415

        try:
            start_frame_materialize_workflow(inputs)
        except Exception:
            # Dispatch failed (e.g. Temporal briefly unreachable). Roll back the status and
            # dedup mapping so identical re-runs don't dedup onto a job that will never run
            # — otherwise every retry polls a dead query_id until the 20-minute TTL.
            manager.delete_query_status()
            manager.unregister_cache_key_mapping(cache_key)
            raise

    return manager.get_query_status()
