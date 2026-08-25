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
ClickHouse overload raise retryable errors, Temporal's retry policy provides the
exponential backoff with a hard schedule-to-close deadline, and the ClickHouse kill switch
lowers the per-query caps during an incident on both transports (see `_capped_settings` —
the streaming one needs it because it never passes through sync_execute).

For a run whose user has the
`notebooks-frame-store-ch-writes` flag, the query goes to the OFFLINE pool (batch exports'
home) as the dedicated `notebooks` ClickHouse user, so a whale materialization contends
with batch work rather than interactive queries, and the user's server-side profile/quota
is a ceiling no application bug can exceed. Without the flag it stays on the interactive
pool as the default user, which is what has always served these frames. ClickHouse
`priority` is deliberately not set: every other query runs at priority 0 (unprioritized),
so a nonzero value here would participate in a scheduling class of one.

That same flag also hands the object write to ClickHouse (phase 2 of the design doc): it
issues `INSERT INTO FUNCTION s3(...)` through the pooled native clients (sync_execute), so
zero result bytes transit the worker, errors arrive in-band and typed, and the streaming
path's EOS-marker check and query_log recovery are unnecessary. One flag carries both
halves, so a run is either entirely the old path or entirely the new one. The worker-relay
path below still runs whenever the flag is off, and as the fail-closed fallback when the
confined writer identity is missing.
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
    ClickHouseCredentials,
    ClickHouseUser,
    get_clickhouse_creds,
    get_kwargs_for_client,
    make_ch_pool,
)
from posthog.clickhouse.client.execute import kill_switch_overrides
from posthog.clickhouse.client.execute_async import QueryNotFoundError, QueryStatusManager, get_query_status
from posthog.clickhouse.client.limit import ConcurrencyLimitExceeded, ConcurrencySlot, RateLimit
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen
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
# The scan budget matches the kill switch's most severe ceiling, so a frame is never held to a
# standing limit tighter than the one ClickHouse imposes on everything else during an incident.
_MAX_BYTES_TO_READ = 1_000_000_000_000  # 1TB
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
# The pre-query window, which dominates a materialization's wall clock and which
# clickhouse_seconds/upload_seconds do not cover: those start once the query is issued.
# Buckets run finer at the bottom than the transport histograms — these phases are expected
# to be sub-second, and the interesting signal is one of them quietly not being.
FRAME_PHASE_SECONDS_HISTOGRAM = Histogram(
    "posthog_notebooks_frame_phase_seconds",
    "Wall-clock of one phase of a successful materialize. setup: activity start to the write "
    "branch (team/user reads, status round-trip, slot acquisition). print: every HogQL print "
    "pass. describe: the DESCRIBE round-trip. stat: the post-write object HEAD.",
    labelnames=["phase"],
    buckets=[0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60],
)
FRAME_PRINT_PASSES_COUNTER = Counter(
    "posthog_notebooks_frame_print_passes",
    "Materializations by how many HogQL print passes they needed. A frame selecting a column "
    "ClickHouse emits as Arrow binary (UUID, Enum, IP, FixedString) needs a second pass, so "
    "this is how often the expensive shape is hit.",
    labelnames=["passes"],
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
    # Resolved from the per-user flag in the web process, because the worker has no request
    # user to evaluate it against. Defaulted so a history recorded before this field existed
    # decodes to the streaming path on the interactive pool, which keeps in-flight runs
    # replayable across the deploy.
    ch_writes: bool = False


@frozen
class _ResolvedWriter:
    """Which write path a run really takes, once the writer identity is known."""

    # The path actually taken, which is not always the one the flag asked for.
    ch_writes: bool
    # The confined `notebooks` writer identity is not provisioned here.
    is_default_user: bool
    # None on the streaming path, which runs as the default user by design.
    creds: ClickHouseCredentials | None


def _resolve_writer(inputs: FrameMaterializeInputs) -> _ResolvedWriter:
    """Resolve the requested transport against the writer identity this deployment has.

    Shared with the terminal safety net so a run that degraded is not counted under the
    transport it asked for — the metric that separates the two transports is the whole point
    of the rollout, and a failure filed under the wrong one is worse than no sample.
    """
    creds = get_clickhouse_creds(ClickHouseUser.NOTEBOOKS) if inputs.ch_writes else None
    is_default_user = creds is None or creds.user == settings.CLICKHOUSE_USER
    # Fail closed in a real deployment: the CH-writes statement is write-capable (readonly=0
    # + S3 egress), so running it as the broad default user — when the flag was flipped before
    # the confined `notebooks` writer identity was provisioned — defeats the whole containment
    # model. Degrade to the read-only streaming path (correct as any user) rather than hand a
    # write+egress statement to the default account. Dev/test keep CH-writes on the default
    # user so the path stays exercisable.
    degraded = is_default_user and not settings.DEBUG and not settings.TEST
    return _ResolvedWriter(ch_writes=inputs.ch_writes and not degraded, is_default_user=is_default_user, creds=creds)


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
    global_slot = global_limiter.use(task_id=f"{task_id}:global", team_id=team_id)
    team_slot: ConcurrencySlot | None = None
    try:
        team_slot = team_limiter.use(task_id=f"{task_id}:team", team_id=team_id)
        yield
    finally:
        # Release each slot independently: a Redis blip releasing the team slot must not
        # skip the global release and leak a global slot until its 15-minute TTL.
        if team_slot is not None:
            with suppress(Exception):
                team_limiter.release(team_slot)
        if global_slot is not None:
            with suppress(Exception):
                global_limiter.release(global_slot)


def _capped_settings(team_id: int) -> HogQLGlobalSettings:
    """The standing caps, lowered to whatever ceilings the ClickHouse kill switch imposes.

    The streaming transport reaches ClickHouse over raw HTTP, so it never passes through
    sync_execute, which is where every other caller picks the kill switch up. Applying the
    ceilings here stops a frame from being the one notebook query that ignores an incident, and
    makes both transports behave the same whatever the rollout flag says.

    They belong in the printed SETTINGS clause, not in the HTTP params: a query-level SETTINGS
    clause outranks a URL param, so params alone would lose to the caps HogQL prints.

    max_execution_time is the exception. HogQLQueryExecutor raises it to
    HOGQL_INCREASED_MAX_EXECUTION_TIME for this limit context *after* it reads these settings, so
    a ceiling set here is discarded. That is a general HogQL gap rather than a notebook one:
    every HogQL query prints its own max_execution_time, and so outranks the kill switch on
    that one key.
    """
    settings = HogQLGlobalSettings(max_bytes_to_read=_MAX_BYTES_TO_READ, max_threads=_MAX_THREADS)
    for name, ceiling in kill_switch_overrides(team_id).items():
        if name not in type(settings).model_fields:
            # A kill-switch key HogQL has no field for. Running with the remaining ceilings beats
            # failing the frame, but the dropped one must not pass silently.
            logger.warning("notebook_frame_kill_switch_setting_unprintable", setting=name, team_id=team_id)
            continue
        current = getattr(settings, name)
        setattr(settings, name, ceiling if current is None else min(current, ceiling))
    return settings


@frozen
class _GeneratedSQL:
    sql: str
    values: dict[str, object]
    seconds: float
    # The executor's own split of that wall clock. Resolving is the step expected to dominate
    # and the one a wrapper pass repeats in full, so it is worth separating from parsing and
    # from emitting the string.
    parse_seconds: float
    resolve_seconds: float
    print_ast_seconds: float


def _generate_sql(
    team: Team,
    user: User | None,
    query: "str | ast.SelectQuery | ast.SelectSetQuery",
    *,
    output_format: str | None,
) -> _GeneratedSQL:
    """Print HogQL to guarded ClickHouse SQL with the standing caps applied."""
    executor = HogQLQueryExecutor(
        query=query,
        team=team,
        user=user,
        user_access_control=UserAccessControl(user=user, team=team) if user else None,
        limit_context=LimitContext.NOTEBOOK_MATERIALIZE,
        settings=_capped_settings(team.pk),
        pretty=False,
    )
    if output_format:
        executor.context.output_format = output_format
    started = time.perf_counter()
    sql, context = executor.generate_clickhouse_sql()
    seconds = time.perf_counter() - started
    recorded = executor.timings.to_dict()
    return _GeneratedSQL(
        sql=sql,
        values=context.values,
        seconds=seconds,
        parse_seconds=_hogql_leaf_seconds(recorded, "query"),
        resolve_seconds=_hogql_leaf_seconds(recorded, "prepare_ast_for_printing"),
        print_ast_seconds=_hogql_leaf_seconds(recorded, "print_prepared_ast"),
    )


def _hogql_leaf_seconds(recorded: dict[str, float], leaf: str) -> float:
    """Sum every span the executor recorded under `leaf`.

    Keys are hierarchical (`./a/b/prepare_ast_for_printing`) and one print records the step
    once per dialect, plus once more per subquery, so match the leaf rather than a fixed path.
    Deliberately not `create_hogql_database`: the executor builds the schema itself before the
    printer's guarded span, so that key is never recorded on this path and would read as 0.
    """
    return sum(seconds for key, seconds in recorded.items() if key.rsplit("/", 1)[-1] == leaf)


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


@frozen
class _PrintedFrameSQL:
    sql: str
    values: dict[str, object]
    # 2 whenever the query is re-printed through a stringifying wrapper. Reported rather than
    # kept internal: the second pass is its own full parse/resolve/print, so it is the largest
    # controllable slice of the pre-query window and worth watching per-run.
    passes: int
    print_seconds: float
    describe_seconds: float
    resolve_seconds: float


def _print_clickhouse_sql(
    describe: _DescribeFn, team: Team, user: User | None, query: str, *, output_format: str | None
) -> _PrintedFrameSQL:
    """Print the HogQL to guarded ClickHouse SQL with the standing caps.

    Two passes when needed (the data-modeling recipe): print once, DESCRIBE the printed
    query (metadata only — no execution), and if any output column would leave ClickHouse
    as Arrow binary, wrap the query so those columns are stringified, then print the
    wrapper. Field names go through the HogQL AST/printer, never string splicing.
    `output_format` is "ArrowStream" for the streaming path; None for the CH-writes path,
    where the s3() function argument defines the object format and a FORMAT clause would
    be invalid inside the INSERT.
    """
    plain = _generate_sql(team, user, query, output_format=None)
    describe_started = time.perf_counter()
    described = describe(plain.sql, plain.values)
    describe_seconds = time.perf_counter() - describe_started
    conversions = [(name, _stringify_function_for(ch_type)) for name, ch_type in described]

    def printed(second: _GeneratedSQL | None) -> _PrintedFrameSQL:
        last = second or plain
        return _PrintedFrameSQL(
            sql=last.sql,
            values=last.values,
            passes=2 if second else 1,
            print_seconds=plain.seconds + (second.seconds if second else 0.0),
            describe_seconds=describe_seconds,
            resolve_seconds=plain.resolve_seconds + (second.resolve_seconds if second else 0.0),
        )

    if not any(function for _name, function in conversions):
        if output_format is None:
            return printed(None)
        return printed(_generate_sql(team, user, query, output_format=output_format))
    select_fields: list[ast.Expr] = [
        ast.Alias(expr=ast.Call(name=function, args=[ast.Field(chain=[name])]), alias=name)
        if function
        else ast.Field(chain=[name])
        for name, function in conversions
    ]
    stringified = ast.SelectQuery(select=select_fields, select_from=ast.JoinExpr(table=parse_select(query)))
    return printed(_generate_sql(team, user, stringified, output_format=output_format))


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

    The region is OBJECT_STORAGE_REGION, not a frames-specific one: whatever region this write
    lands in is the region the app's presigning client signs the read with.
    """
    bucket = settings.NOTEBOOKS_FRAME_STORE_S3_BUCKET
    endpoint = settings.NOTEBOOKS_FRAME_STORE_S3_ENDPOINT
    if endpoint:
        return f"{endpoint}/{bucket}/{key}"
    return f"https://{bucket}.s3.{settings.OBJECT_STORAGE_REGION}.amazonaws.com/{key}"


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


@frozen
class _WrittenFrame:
    object_bytes: int
    clickhouse_seconds: float
    stat_seconds: float
    printed: _PrintedFrameSQL


def _execute_insert_to_s3(team: Team, user: User | None, query: str, key: str) -> _WrittenFrame:
    """Materialize by having ClickHouse write the object itself.

    Runs through the pooled native clients (sync_execute) with a bounded socket timeout:
    offline workload and hedging hygiene come from the workload routing, errors arrive
    in-band and typed, and no result bytes transit the worker — so the streaming path's
    EOS-marker check and query_log recovery have no equivalent here.
    """
    printed = _print_clickhouse_sql(
        lambda sql, sql_values: _describe_columns_pooled(sql, sql_values, team.pk),
        team,
        user,
        query,
        output_format=None,
    )
    insert_sql, s3_params = _insert_into_s3_sql(printed.sql, key)
    insert_values = {**printed.values, **s3_params}
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
    stat_started = time.perf_counter()
    object_bytes = frame_store.stat_frame(key, written_after=write_started_at - dt.timedelta(minutes=5))
    stat_seconds = time.perf_counter() - stat_started
    if object_bytes > _MAX_RESULT_BYTES:
        # max_result_bytes bounds result sets returned to a client, not an INSERT's sink —
        # the output cap has to be enforced after the fact on this path. The bytes are
        # ours (this attempt just wrote them), so deleting is safe.
        with suppress(ObjectStorageError):
            frame_store.delete_frame(key)
        raise FrameTooLargeError(f"Frame object is {object_bytes} bytes, over the {_MAX_RESULT_BYTES} budget")
    return _WrittenFrame(
        object_bytes=object_bytes,
        clickhouse_seconds=clickhouse_seconds,
        stat_seconds=stat_seconds,
        printed=printed,
    )


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
    # The new flow rides one flag, resolved per user in the web process and carried on the
    # job. Off, this run is the path that has been serving frames all along: interactive
    # pool, default credentials, hedging left alone.
    offline = inputs.ch_writes
    # Dedicated `notebooks` CH user (server-side profile/quota backstop no application
    # bug can exceed); falls back to the default credentials where not provisioned.
    # sync_execute on the CH-writes path resolves the same creds via the same enum.
    resolved = _resolve_writer(inputs)
    creds = resolved.creds
    resolved_default_user = resolved.is_default_user
    ch_writes = resolved.ch_writes
    if inputs.ch_writes and not ch_writes:
        logger.warning(
            "notebook_frame_ch_writes_missing_writer_identity",
            team_id=inputs.team_id,
            query_id=inputs.query_id,
        )
    mode = "ch_writes" if ch_writes else "streaming"
    ch_url = settings.CLICKHOUSE_OFFLINE_HTTP_URL if offline else settings.CLICKHOUSE_HTTP_URL
    # Reports where the query actually went, not what the flag asked for, and the two paths
    # answer that differently: sync_execute keys on the offline host being set at all, while
    # the HTTP client's URL collapses to the online one under TEST/DEBUG as well.
    pool_offline = (
        settings.CLICKHOUSE_OFFLINE_CLUSTER_HOST is not None if ch_writes else ch_url != settings.CLICKHOUSE_HTTP_URL
    )
    FRAME_MATERIALIZATIONS_STARTED_COUNTER.labels(
        ch_user="notebooks" if not resolved_default_user else "default",
        pool="offline" if pool_offline else "online",
        mode=mode,
    ).inc()
    manager = QueryStatusManager(inputs.query_id, inputs.team_id)
    team = Team.objects.get(id=inputs.team_id)
    user = User.objects.filter(id=inputs.user_id).first() if inputs.user_id else None
    key = frame_store.build_frame_key(inputs.team_id, inputs.notebook_short_id, inputs.query_hash)

    attempt = activity.info().attempt if activity.in_activity() else 1
    started_at = dt.datetime.now(dt.UTC)
    activity_started = time.perf_counter()

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
                # Everything before the write branch: team/user reads, the status round-trip,
                # and slot acquisition. Measured because the pre-query window dominates a
                # materialization's wall clock and was previously indivisible.
                setup_seconds = time.perf_counter() - activity_started
                stat_seconds = 0.0
                if ch_writes:
                    written = _execute_insert_to_s3(team, user, inputs.query, key)
                    object_bytes = written.object_bytes
                    clickhouse_seconds = written.clickhouse_seconds
                    stat_seconds = written.stat_seconds
                    printed = written.printed
                    upload_seconds = None  # CH performs the upload; the relay split doesn't exist
                else:
                    client = ClickHouseClient(
                        # With the flag on this is the offline pool (batch exports' home), so a
                        # whale materialization does not contend with interactive queries. It
                        # falls back to the online URL where no offline cluster exists (EU,
                        # self-hosted, dev/test), and stays online entirely without the flag.
                        url=ch_url,
                        user=creds.user if creds is not None else settings.CLICKHOUSE_USER,
                        password=creds.password if creds is not None else settings.CLICKHOUSE_PASSWORD,
                        database=settings.CLICKHOUSE_DATABASE,
                        output_format_arrow_string_as_string="true",
                        cancel_http_readonly_queries_on_client_close=1,
                        max_result_bytes=_MAX_RESULT_BYTES,
                        result_overflow_mode="throw",
                    )
                    if offline:
                        # sync_execute's offline hygiene, and only meaningful off the
                        # interactive pool: without it, distributed subqueries of a saturated
                        # offline query hedge onto online replicas, bleeding the whale back
                        # into the pool this move protects. Set after construction rather than
                        # as a kwarg so the online path sends no such setting at all, exactly
                        # as it did before this flag existed.
                        client.params["use_hedged_requests"] = "0"
                    printed = _print_clickhouse_sql(
                        lambda sql, sql_values: _describe_columns(client, sql, sql_values, ch_query_id),
                        team,
                        user,
                        inputs.query,
                        output_format="ArrowStream",
                    )
                    query_started = time.perf_counter()
                    with client.post_query(
                        printed.sql,
                        query_parameters=printed.values,
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
            # The CH-writes analog of the result-bytes cap: deterministic, so terminal. The
            # user-facing message is deliberately vague about the limit, so log the actual
            # size: it is the only record of how far over the cap ClickHouse ran before the
            # post-write check caught it, which is what tells us whether the cap is set right.
            logger.warning(
                "notebook_frame_materialize_object_too_large",
                team_id=inputs.team_id,
                query_id=inputs.query_id,
                error=str(exc),
            )
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
                if not exc.is_per_query_limit:
                    # "(total)" or "(for user)": the cluster was under pressure, this query was
                    # not too big. classify_failure() draws the same line. Retrying is what
                    # fixes it, and telling the user to narrow a fine query would be wrong.
                    logger.warning(
                        "notebook_frame_materialize_insert_cluster_memory_pressure",
                        team_id=inputs.team_id,
                        query_id=inputs.query_id,
                    )
                    raise
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
            # Budget overruns arrive here too (TOO_MANY_BYTES for the scan cap is an
            # ExposedCHQueryError), so consult the shared code table first: the same failure
            # must read the same way whichever transport produced it.
            message = _MID_STREAM_MESSAGES_BY_CODE.get(exc.code, "") or str(exc)
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
            # endpoint/bucket skew) would otherwise re-scan the whale silently on every attempt.
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

    # The bucket travels with the key: a status outlives the deploy that changes
    # NOTEBOOKS_FRAME_STORE_S3_BUCKET, and the key alone does not say where the object went.
    _finalize_status(manager, inputs, results={"object_key": key, "bucket": settings.NOTEBOOKS_FRAME_STORE_S3_BUCKET})
    FRAME_MATERIALIZATIONS_FINISHED_COUNTER.labels(outcome="succeeded", mode=mode).inc()
    FRAME_OBJECT_BYTES_HISTOGRAM.observe(object_bytes)
    FRAME_MATERIALIZE_SECONDS_HISTOGRAM.observe((dt.datetime.now(dt.UTC) - started_at).total_seconds())
    FRAME_CLICKHOUSE_SECONDS_HISTOGRAM.labels(mode=mode).observe(clickhouse_seconds)
    if upload_seconds is not None:
        # Only the worker-relay path has an observable upload half; a stream of zeros from
        # the CH-writes path would poison the histogram this split exists to interpret.
        FRAME_UPLOAD_SECONDS_HISTOGRAM.observe(upload_seconds)
    FRAME_PHASE_SECONDS_HISTOGRAM.labels(phase="setup").observe(setup_seconds)
    FRAME_PHASE_SECONDS_HISTOGRAM.labels(phase="print").observe(printed.print_seconds)
    FRAME_PHASE_SECONDS_HISTOGRAM.labels(phase="describe").observe(printed.describe_seconds)
    FRAME_PHASE_SECONDS_HISTOGRAM.labels(phase="stat").observe(stat_seconds)
    FRAME_PRINT_PASSES_COUNTER.labels(passes=str(printed.passes)).inc()
    logger.info(
        "notebook_frame_materialized",
        team_id=inputs.team_id,
        notebook_short_id=inputs.notebook_short_id,
        query_id=inputs.query_id,
        object_bytes=object_bytes,
        ch_writes=ch_writes,
        clickhouse_seconds=round(clickhouse_seconds, 3),
        upload_seconds=round(upload_seconds, 3) if upload_seconds is not None else None,
        setup_seconds=round(setup_seconds, 3),
        print_seconds=round(printed.print_seconds, 3),
        print_passes=printed.passes,
        describe_seconds=round(printed.describe_seconds, 3),
        resolve_seconds=round(printed.resolve_seconds, 3),
        stat_seconds=round(stat_seconds, 3),
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
    # The effective transport, not the requested one: a run that fell back to streaming must
    # not land in the ch_writes bucket, or the rollout comparison counts its failures twice over.
    mode = "ch_writes" if _resolve_writer(inputs).ch_writes else "streaming"
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
                    # Slot exhaustion raises before the activity touches ClickHouse, so this
                    # backoff is the only queue a blocked job gets. The intervals are wide
                    # enough that a job blocked behind a short frame still gets a turn inside
                    # the small attempt budget below.
                    initial_interval=dt.timedelta(seconds=5),
                    backoff_coefficient=2.0,
                    maximum_interval=dt.timedelta(seconds=30),
                    # Bound the storm. A transient failure re-runs the entire scan on either
                    # transport, and schedule_to_close only caps that for queries slow enough to
                    # fill the window, so a fast query could otherwise repeat its scan on every
                    # attempt. The deterministic failures are already non-retryable in the activity.
                    maximum_attempts=3,
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
    ch_writes: bool = False,
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
        ch_writes=ch_writes,
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
