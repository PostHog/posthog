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
exponential backoff with a hard schedule-to-close deadline. ClickHouse `priority` is
deliberately not set: every other query runs at priority 0 (unprioritized), so a nonzero
value here would participate in a scheduling class of one.
"""

import uuid
import hashlib
import datetime as dt
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass

from django.conf import settings

import structlog
from prometheus_client import Counter, Histogram
from temporalio import activity, common, exceptions, workflow

from posthog.schema import QueryStatus

from posthog.hogql.constants import HogQLGlobalSettings, LimitContext
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.query import HogQLQueryExecutor

from posthog.clickhouse.client.execute_async import QueryNotFoundError, QueryStatusManager, get_query_status
from posthog.clickhouse.client.limit import ConcurrencyLimitExceeded, RateLimit
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.exceptions_capture import capture_exception
from posthog.models import Team, User
from posthog.rbac.user_access_control import UserAccessControl
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.clickhouse import (
    ClickHouseClient,
    ClickHouseMemoryLimitExceededError,
    ClickHouseTooManyBytesError,
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

FRAME_MATERIALIZATIONS_STARTED_COUNTER = Counter(
    "posthog_notebooks_frame_materializations_started",
    "Number of notebook frame materialize activity attempts started.",
)
FRAME_MATERIALIZATIONS_FINISHED_COUNTER = Counter(
    "posthog_notebooks_frame_materializations_finished",
    "Number of notebook frame materialize jobs reaching a terminal state.",
    labelnames=["outcome"],
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
    "Wall-clock duration of a successful materialize (ClickHouse execution + upload).",
    buckets=[1, 5, 15, 30, 60, 120, 300, 600],
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


def _print_clickhouse_sql(team: Team, user: User | None, query: str) -> tuple[str, dict[str, object]]:
    """Print the HogQL to guarded ClickHouse SQL with `FORMAT ArrowStream` and the standing caps."""
    executor = HogQLQueryExecutor(
        query=query,
        team=team,
        user=user,
        user_access_control=UserAccessControl(user=user, team=team) if user else None,
        limit_context=LimitContext.NOTEBOOK_MATERIALIZE,
        settings=HogQLGlobalSettings(max_bytes_to_read=_MAX_BYTES_TO_READ, max_threads=_MAX_THREADS),
        pretty=False,
    )
    executor.context.output_format = "ArrowStream"
    sql, context = executor.generate_clickhouse_sql()
    return sql, context.values


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
    except QueryNotFoundError:
        status = QueryStatus(id=inputs.query_id, team_id=inputs.team_id)
    status.complete = True
    status.error = error_message is not None
    status.error_message = error_message
    status.results = results
    status.end_time = dt.datetime.now(dt.UTC)
    manager.store_query_status(status)
    manager.unregister_cache_key_mapping(inputs.cache_key)


def materialize_frame(inputs: FrameMaterializeInputs) -> str:
    """Stream the frame's ClickHouse result into the object store; return the object key.

    Raises on failure so Temporal retries per policy; user-safe HogQL errors are written
    to the query status here (terminal — retrying can't fix a bad query) before raising.
    """
    FRAME_MATERIALIZATIONS_STARTED_COUNTER.inc()
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
        try:
            printed_sql, context_values = _print_clickhouse_sql(team, user, inputs.query)
        except ExposedHogQLError as exc:
            # User-safe and terminal: surface the message through the poll, don't retry —
            # a bad query cannot succeed on a second attempt.
            _finalize_status(manager, inputs, error_message=str(exc))
            FRAME_MATERIALIZATIONS_FINISHED_COUNTER.labels(outcome="failed").inc()
            raise exceptions.ApplicationError(str(exc), non_retryable=True) from exc

        try:
            with _materialize_slots(inputs.team_id, inputs.query_id):
                client = ClickHouseClient(
                    url=settings.CLICKHOUSE_HTTP_URL,
                    user=settings.CLICKHOUSE_USER,
                    password=settings.CLICKHOUSE_PASSWORD,
                    database=settings.CLICKHOUSE_DATABASE,
                    output_format_arrow_string_as_string="true",
                    cancel_http_readonly_queries_on_client_close=1,
                )
                # Per-attempt CH query id: a retried attempt must not collide with a
                # predecessor ClickHouse may still be draining.
                ch_query_id = f"{inputs.query_id}_{attempt}"
                with client.post_query(printed_sql, query_parameters=context_values, query_id=ch_query_id) as response:
                    # A torn stream aborts the multipart upload (upload_fileobj), so no
                    # partial object is ever left behind — nothing to clean up on failure.
                    # The key is deterministic per (team, notebook, user, query), so we must
                    # NOT delete it on error: that would destroy an object an earlier
                    # successful run's still-live status/presigned URL points at.
                    object_bytes = frame_store.write_stream(key, response.raw)
        except ConcurrencyLimitExceeded:
            raise  # retryable — Temporal backs off and re-attempts
        except (ClickHouseMemoryLimitExceededError, ClickHouseTooManyBytesError) as exc:
            # Deterministic resource-budget failures: re-executing the same heavy query just
            # burns ClickHouse and ends on the same wall. Terminal, with a user-facing
            # message. (Only failures ClickHouse rejects up front surface as typed errors
            # here; a mid-stream overrun tears the Arrow stream and is instead bounded by
            # the workflow's maximum_attempts.)
            message = (
                "This query exceeds the frame materialization limits (scan or memory budget). Narrow it and re-run."
            )
            _finalize_status(manager, inputs, error_message=message)
            FRAME_MATERIALIZATIONS_FINISHED_COUNTER.labels(outcome="failed").inc()
            raise exceptions.ApplicationError(message, non_retryable=True) from exc

    _finalize_status(manager, inputs, results={"object_key": key})
    FRAME_MATERIALIZATIONS_FINISHED_COUNTER.labels(outcome="succeeded").inc()
    FRAME_OBJECT_BYTES_HISTOGRAM.observe(object_bytes)
    FRAME_MATERIALIZE_SECONDS_HISTOGRAM.observe((dt.datetime.now(dt.UTC) - started_at).total_seconds())
    logger.info(
        "notebook_frame_materialized",
        team_id=inputs.team_id,
        notebook_short_id=inputs.notebook_short_id,
        query_id=inputs.query_id,
        object_bytes=object_bytes,
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
    FRAME_MATERIALIZATIONS_FINISHED_COUNTER.labels(outcome="failed").inc()


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
