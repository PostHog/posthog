import time
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Optional

import structlog
import posthoganalytics
from prometheus_client import Counter

from posthog.schema import EventPropertyFilter, PropertyOperator

from posthog.hogql import ast
from posthog.hogql.property import property_to_expr
from posthog.hogql.transforms.preaggregated_table_transformation import is_integer_timezone

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.preaggregation.web_overview_preaggregated_sql import (
    DISTRIBUTED_WEB_OVERVIEW_PREAGGREGATED_TABLE,
)
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.settings import DEBUG, TEST

from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import (
    LazyComputationResult,
    LazyComputationTable,
    ensure_precomputed,
)

if TYPE_CHECKING:
    from products.web_analytics.backend.hogql_queries.web_overview import WebOverviewQueryRunner

logger = structlog.get_logger(__name__)

# Bucketing the precompute hourly keeps reads correct for any whole-hour-offset
# timezone — boundaries line up exactly when the team-local window is converted
# to UTC before filtering on `time_window_start`. Half-hour-offset timezones
# (IST, Newfoundland, Nepal, etc.) are explicitly gated out below.
LAZY_TTL_SECONDS: dict[str, int] = {
    "0d": 15 * 60,
    "1d": 60 * 60,
    "7d": 24 * 60 * 60,
    "default": 7 * 24 * 60 * 60,
}

# Today the gate accepts: empty user filters, or a single EventPropertyFilter
# on `$host` with operator `exact`. Test-account filters are always allowed
# (their content is hashed into the cache key).
SUPPORTED_USER_FILTER_KEYS: set[str] = {"$host"}

# Upper bound on the precompute span. Above this, the framework would create
# enough daily jobs that the first request burns INSERT slots for minutes.
MAX_PRECOMPUTE_DAYS = 90

# Hard cap on the post-INSERT "are my writes visible yet?" poll. Empirically the
# fetch lag on `sharded_web_overview_preaggregated` is sub-second for parts we
# just wrote; 5s is comfortably above p99. On timeout the caller falls through
# to the live path (correct but slower) so this only bounds the wait — not
# correctness.
DATA_VISIBILITY_TIMEOUT_SECONDS = 5.0

# Initial poll interval. We expand on each iteration up to a small ceiling so
# we don't hammer ClickHouse if replication is genuinely slow.
DATA_VISIBILITY_POLL_INITIAL_INTERVAL = 0.05
DATA_VISIBILITY_POLL_MAX_INTERVAL = 0.5


WEB_OVERVIEW_LAZY_FAILED = Counter(
    "web_overview_lazy_precompute_failed_total",
    "Lazy precompute path failures, by error class",
    ["error_type"],
)

WEB_OVERVIEW_LAZY_VISIBILITY_WAIT = Counter(
    "web_overview_lazy_precompute_visibility_wait_total",
    "Post-INSERT visibility polls before the lazy precompute read, by outcome",
    ["outcome"],
)


class LazyPrecomputeIneligible(Exception):
    """Base class for reasons the lazy precompute path is not eligible.

    Raised by `_check_lazy_precompute_eligible` and caught by
    `can_use_lazy_precompute`, which logs the exception class name. Subclass
    names are the canonical identifiers used in logs/metrics — keep them
    stable across releases.
    """


class OrgFeatureFlagDisabled(LazyPrecomputeIneligible):
    pass


class PerQueryOptInNotSet(LazyPrecomputeIneligible):
    pass


class NonIntegerTimezone(LazyPrecomputeIneligible):
    pass


class ConversionGoalUnsupported(LazyPrecomputeIneligible):
    pass


class SamplingEnabled(LazyPrecomputeIneligible):
    pass


class SessionsV2UuidMode(LazyPrecomputeIneligible):
    pass


class TooManyFilters(LazyPrecomputeIneligible):
    pass


class NonEventPropertyFilter(LazyPrecomputeIneligible):
    pass


class UnsupportedFilterKey(LazyPrecomputeIneligible):
    def __init__(self, key: str):
        self.key = key
        super().__init__(f"key={key!r}")


class UnsupportedFilterOperator(LazyPrecomputeIneligible):
    def __init__(self, operator: object):
        self.operator = operator
        super().__init__(f"operator={operator!r}")


class NonStringOrEmptyFilterValue(LazyPrecomputeIneligible):
    pass


class MissingDateRange(LazyPrecomputeIneligible):
    pass


class DateRangeOverMax(LazyPrecomputeIneligible):
    def __init__(self, days: int):
        self.days = days
        super().__init__(f"days={days} max={MAX_PRECOMPUTE_DAYS}")


def can_use_lazy_precompute(runner: "WebOverviewQueryRunner") -> bool:
    """Return True iff the lazy precompute path is eligible. Logs rejection
    reason at INFO level so we can attribute every fall-through after deploy."""
    try:
        _check_lazy_precompute_eligible(runner)
    except LazyPrecomputeIneligible as exc:
        logger.info(
            "web_overview_lazy_precompute_rejected",
            team_id=runner.team.pk,
            reason=type(exc).__name__,
            detail=str(exc) or None,
        )
        return False
    logger.info(
        "web_overview_lazy_precompute_eligible",
        team_id=runner.team.pk,
    )
    return True


def _check_lazy_precompute_eligible(runner: "WebOverviewQueryRunner") -> None:
    """Raise a `LazyPrecomputeIneligible` subclass if the query can't go through
    the lazy path. Returns None on success."""
    query = runner.query

    # Rollout gate: shared PostHog feature flag AND per-query opt-in.
    #   - `web-analytics-precompute-toggle` (PostHog feature flag): the same
    #     flag the frontend already uses to show/hide the "Allow precompute"
    #     button in the Web Analytics ScenePanel. One switch controls both the
    #     UI surface and the backend gate. The flag is evaluated at the
    #     organization level — set up an org-level release condition on the
    #     flag to enable rollout per org. The SDK swallows its own exceptions
    #     and returns None (falsy) on failure, so a flag-service outage
    #     fails-closed (gate raised, fall back to v2 / raw) automatically.
    #   - `query.useWebAnalyticsPrecompute` (per-query parameter set by the
    #     "Allow precompute" toggle).
    if not posthoganalytics.feature_enabled(
        "web-analytics-precompute-toggle",
        str(runner.team.uuid),
        groups={
            "organization": str(runner.team.organization_id),
            "project": str(runner.team.id),
        },
        group_properties={
            "organization": {"id": str(runner.team.organization_id)},
            "project": {"id": str(runner.team.id)},
        },
        only_evaluate_locally=True,
        send_feature_flag_events=False,
    ):
        raise OrgFeatureFlagDisabled()

    if query.useWebAnalyticsPrecompute is not True:
        raise PerQueryOptInNotSet()

    # Half-hour-offset timezones (IST +5:30, Newfoundland -3:30, Nepal +5:45, etc.)
    # can't be served by UTC hourly buckets without sub-hour precision. Skip them
    # rather than return wrong totals on the boundary days.
    if not is_integer_timezone(runner.team.timezone):
        raise NonIntegerTimezone()

    if query.conversionGoal is not None:
        raise ConversionGoalUnsupported()

    if query.sampling is not None and getattr(query.sampling, "enabled", False):
        raise SamplingEnabled()

    # UUID session-id mode produces `uniqState(UUID)` from
    # `events.$session_id_uuid`, which fails to insert into the schema's
    # `AggregateFunction(uniq, String)` column. Gate out until the column
    # is re-typed in a follow-up.
    if query.modifiers and query.modifiers.sessionsV2JoinMode == "uuid":
        raise SessionsV2UuidMode()

    properties = query.properties or []
    if len(properties) > 1:
        raise TooManyFilters()
    for prop in properties:
        if not isinstance(prop, EventPropertyFilter):
            raise NonEventPropertyFilter()
        if prop.key not in SUPPORTED_USER_FILTER_KEYS:
            raise UnsupportedFilterKey(prop.key)
        if prop.operator != PropertyOperator.EXACT:
            raise UnsupportedFilterOperator(prop.operator)
        if not isinstance(prop.value, str) or not prop.value:
            raise NonStringOrEmptyFilterValue()

    date_from = runner.query_date_range.date_from()
    date_to = runner.query_date_range.date_to()
    if date_from is None or date_to is None:
        raise MissingDateRange()

    days = (date_to - date_from).days
    if days > MAX_PRECOMPUTE_DAYS:
        raise DateRangeOverMax(days)


def _user_filter_expr(runner: "WebOverviewQueryRunner") -> ast.Expr:
    """Build the AST expression that gets substituted into the INSERT's WHERE clause.

    The substituted AST is what `ensure_precomputed` hashes into the cache key —
    different filter values therefore become different precomputed jobs.
    """
    if not runner.query.properties:
        return ast.Constant(value=True)

    # Gate already enforces single EventPropertyFilter with $host exact + string value.
    host_filter = runner.query.properties[0]
    assert isinstance(host_filter, EventPropertyFilter)
    return ast.Call(
        name="equals",
        args=[
            ast.Field(chain=["events", "properties", host_filter.key]),
            ast.Constant(value=host_filter.value),
        ],
    )


def _test_account_filter_expr(runner: "WebOverviewQueryRunner") -> ast.Expr:
    """Test-account filters land in the placeholder set, so they also shape the cache key.

    `_test_account_filters` may be an empty list when filterTestAccounts is False
    or the project has none configured.
    """
    if not runner._test_account_filters:
        return ast.Constant(value=True)
    return property_to_expr(runner._test_account_filters, team=runner.team)


def _events_session_id_expr(runner: "WebOverviewQueryRunner") -> ast.Expr:
    return runner.events_session_property


# Forward pad on the per-job event-scan window. The lazy_computation framework
# chunks the precompute span into daily UTC jobs; each job covers
# `[time_window_min, time_window_max)`. A session starting at 23:50 with events
# spilling past midnight would lose its trailing events without a forward pad —
# the HAVING clause attributes the session to its start hour, but the events
# table scan needs to see those trailing events to compute correct
# `$session_duration` / `$pageview_count` / `$is_bounce`.
#
# Forward-only is sufficient. The HAVING clause keeps only sessions whose
# `min(session.$start_timestamp)` falls inside `[time_window_min, time_window_max)`.
# Every event of such a session has `timestamp >= session.$start_timestamp >=
# time_window_min`, so backward scanning never picks up anything that survives
# HAVING — it only burns I/O on sessions that get discarded.
#
# Session length isn't bounded server-side: `$session_id` is generated by the
# client SDK (default 30 min inactivity, 24 h hard cap in posthog-js), and the
# threshold is per-site-configurable. Measured prod distribution (raw_sessions,
# 1 h slice, 8.3M sessions): p99 = 79 min, p99.9 = 111 min. For team_id=2
# (posthog.com, docs left open for days) over 7 days: p95 = 75 min,
# p99 = 19 h, 0.6% of sessions > 24 h. The 24 h hard cap is the meaningful
# ceiling for ~99.4% of dogfood sessions and effectively 100% of the wider
# population; anything past it is rare enough to be a documented limitation
# rather than a sizing target.
#
# Trade-off: +24 h forward costs ~2× the events scanned per daily job vs +60 min,
# but 60 min undercounts 1.45% of sessions site-wide and 4.17% on posthog.com.
# Correctness wins over INSERT cost at this scale.
#
# Sessions longer than `SESSION_FORWARD_PAD_MINUTES` are silently undercounted
# on cross-boundary days. The long-term fix is to drive the INSERT from
# `raw_sessions` (bounded by `session_id_v7`'s embedded UUIDv7 timestamp) and
# source `$session_duration` / `$is_bounce` / `$pageview_count` from the
# sessions table — same approach as the v2 preagg DAG. That removes the pad
# entirely.
SESSION_FORWARD_PAD_MINUTES = 24 * 60


# HogQL template for the precompute INSERT. The lazy_computation framework
# substitutes the listed placeholders (including `time_window_min`/`time_window_max`),
# parses the result, and INSERTs into `web_overview_preaggregated`. The framework
# automatically prepends `team_id`, `job_id` and appends `expires_at` to the SELECT.
INSERT_QUERY_TEMPLATE = """
SELECT
    toStartOfHour(start_timestamp) AS time_window_start,
    uniqState(session_person_id) AS uniq_users_state,
    uniqState(session_id) AS uniq_sessions_state,
    sumState(assumeNotNull(toInt(filtered_pageview_count))) AS sum_pageviews_state,
    avgState(assumeNotNull(toFloat(session_duration))) AS avg_duration_state,
    avgState(assumeNotNull(toInt(is_bounce))) AS avg_bounce_state
FROM (
    SELECT
        any(events.person_id) AS session_person_id,
        {events_session_id} AS session_id,
        min(session.$start_timestamp) AS start_timestamp,
        any(session.$session_duration) AS session_duration,
        countIf(or(equals(event, '$pageview'), equals(event, '$screen'))) AS filtered_pageview_count,
        any(session.$is_bounce) AS is_bounce
    FROM events
    WHERE and(
        {events_session_id} IS NOT NULL,
        {event_type_filter},
        timestamp >= {time_window_min},
        timestamp < ({time_window_max} + toIntervalMinute({pad_minutes})),
        {user_filter},
        {test_account_filter}
    )
    GROUP BY session_id
    HAVING and(
        toStartOfHour(min(session.$start_timestamp)) >= {time_window_min},
        toStartOfHour(min(session.$start_timestamp)) < {time_window_max}
    )
)
GROUP BY time_window_start
"""


def ensure_web_overview_precomputed(
    runner: "WebOverviewQueryRunner",
    time_range_start: datetime,
    time_range_end: datetime,
) -> LazyComputationResult:
    placeholders: dict[str, ast.Expr] = {
        "events_session_id": _events_session_id_expr(runner),
        "event_type_filter": runner.event_type_expr,
        "user_filter": _user_filter_expr(runner),
        "test_account_filter": _test_account_filter_expr(runner),
        "pad_minutes": ast.Constant(value=SESSION_FORWARD_PAD_MINUTES),
    }

    return ensure_precomputed(
        team=runner.team,
        insert_query=INSERT_QUERY_TEMPLATE,
        time_range_start=time_range_start,
        time_range_end=time_range_end,
        ttl_seconds=LAZY_TTL_SECONDS,
        table=LazyComputationTable.WEB_OVERVIEW_PREAGGREGATED,
        placeholders=placeholders,
        query_type="web_overview_lazy_insert",
    )


_READ_SQL = f"""
SELECT
    uniqMergeIf(uniq_users_state, time_window_start >= %(cur_start)s AND time_window_start < %(cur_end)s) AS unique_users,
    uniqMergeIf(uniq_users_state, time_window_start >= %(prev_start)s AND time_window_start < %(prev_end)s) AS previous_unique_users,
    sumMergeIf(sum_pageviews_state, time_window_start >= %(cur_start)s AND time_window_start < %(cur_end)s) AS views,
    sumMergeIf(sum_pageviews_state, time_window_start >= %(prev_start)s AND time_window_start < %(prev_end)s) AS previous_views,
    uniqMergeIf(uniq_sessions_state, time_window_start >= %(cur_start)s AND time_window_start < %(cur_end)s) AS sessions,
    uniqMergeIf(uniq_sessions_state, time_window_start >= %(prev_start)s AND time_window_start < %(prev_end)s) AS previous_sessions,
    avgMergeIf(avg_duration_state, time_window_start >= %(cur_start)s AND time_window_start < %(cur_end)s) AS avg_duration,
    avgMergeIf(avg_duration_state, time_window_start >= %(prev_start)s AND time_window_start < %(prev_end)s) AS previous_avg_duration,
    avgMergeIf(avg_bounce_state, time_window_start >= %(cur_start)s AND time_window_start < %(cur_end)s) AS bounce_rate,
    avgMergeIf(avg_bounce_state, time_window_start >= %(prev_start)s AND time_window_start < %(prev_end)s) AS previous_bounce_rate
FROM {DISTRIBUTED_WEB_OVERVIEW_PREAGGREGATED_TABLE()}
WHERE team_id = %(team_id)s AND job_id IN %(job_ids)s
"""


_READ_SETTINGS = {
    # `load_balancing="in_order"` matches the INSERT side so a warm-cache read
    # (no fresh INSERTs in this request) deterministically lands on the same
    # replica that originally wrote the data — see Approach E in
    # `products/analytics_platform/backend/lazy_computation/CONSISTENCY.md`.
    #
    # For the cold-cache case where this read fires right after fresh INSERTs,
    # `in_order` alone is not enough: a transient `errors_count` bump on the
    # preferred replica can reroute either the INSERT coordination or the
    # SELECT to a different replica, and parts may still be mid-fetch on the
    # one we land on. `execute_lazy_precomputed_read` polls
    # `_wait_for_data_visible` (which fires the same shape of SELECT) before
    # issuing this read whenever any job was inserted in this request, so by
    # the time we get here every job_id we'll read is confirmed visible on
    # the same replica.
    "load_balancing": "in_order",
    # Shard pruning: sharding key is `sipHash64(job_id)`; `job_id IN (...)` matches
    # exactly the shards we wrote to.
    "optimize_skip_unused_shards": 1,
}


def _wait_for_data_visible(team_id: int, inserted_job_ids: list[str]) -> bool:
    """Poll the Distributed table until every freshly-INSERTed job_id shows at
    least one bucket — i.e., the part we just wrote has propagated to the same
    replica the downstream SELECT will use (`load_balancing="in_order"`).

    `inserted_job_ids` MUST contain only IDs we INSERTed in this request (see
    `LazyComputationResult.inserted_job_ids`). Passing cached job_ids here
    would conflate "visibility wait" with "is this team's data non-empty",
    producing spurious timeouts for teams whose period contains zero events.

    Returns True when all job_ids are visible. Returns False on timeout — the
    caller MUST then fall through to the live path rather than issue the read,
    since a partial-visibility SELECT silently under-counts (the failure mode
    this whole flow exists to prevent).

    Verifies through the same `optimize_skip_unused_shards=1` / `load_balancing
    ="in_order"` path the real read uses, so we test exactly the visibility
    the read needs — no SYSTEM commands, no cluster-name assumptions.

    Caveat: if any of the just-INSERTed jobs legitimately produced zero rows
    (e.g. a `$host` filter that matched no events in the window), it won't
    show up in `count(DISTINCT job_id)` and this will time out. The fallback
    returns correct (zero) data through the live path, just slower. With the
    `inserted_job_ids` scoping above this only affects requests that both
    triggered a fresh INSERT AND that INSERT was empty for its range — a
    narrow corner of the input space.
    """
    if not inserted_job_ids:
        return True
    # TEST/DEBUG run against a single-node ClickHouse where the race can't
    # happen — every write is immediately visible. Skip the poll so unit tests
    # don't spend the timeout budget waiting for a race that doesn't exist.
    if TEST or DEBUG:
        return True

    expected = len(set(inserted_job_ids))
    job_ids_tuple = tuple(inserted_job_ids)
    table = DISTRIBUTED_WEB_OVERVIEW_PREAGGREGATED_TABLE()
    tag_queries(
        product=Product.WEB_ANALYTICS,
        feature=Feature.QUERY,
        query_type="web_overview_lazy_visibility_check",
    )

    started = time.perf_counter()
    interval = DATA_VISIBILITY_POLL_INITIAL_INTERVAL
    polls = 0
    last_visible = -1
    while True:
        elapsed = time.perf_counter() - started
        if elapsed >= DATA_VISIBILITY_TIMEOUT_SECONDS:
            break
        polls += 1
        try:
            result = sync_execute(
                f"SELECT count(DISTINCT job_id) FROM {table} WHERE team_id = %(team_id)s AND job_id IN %(job_ids)s",
                {"team_id": team_id, "job_ids": job_ids_tuple},
                settings={
                    "load_balancing": "in_order",
                    "optimize_skip_unused_shards": 1,
                },
                team_id=team_id,
            )
            last_visible = int(result[0][0]) if result else 0
            if last_visible >= expected:
                duration_ms = int((time.perf_counter() - started) * 1000)
                WEB_OVERVIEW_LAZY_VISIBILITY_WAIT.labels(outcome="visible").inc()
                logger.info(
                    "web_overview_lazy_precompute_visibility_check",
                    team_id=team_id,
                    outcome="visible",
                    polls=polls,
                    duration_ms=duration_ms,
                    expected=expected,
                    visible=last_visible,
                )
                return True
        except Exception as exc:
            # Don't unwind on transient CH errors — keep polling within the
            # budget. If errors persist past the timeout we report below.
            logger.warning(
                "web_overview_lazy_precompute_visibility_poll_error",
                team_id=team_id,
                error_type=type(exc).__name__,
                error=str(exc)[:200],
            )

        # Sleep, then back off (still bounded by the overall timeout above).
        time.sleep(min(interval, DATA_VISIBILITY_TIMEOUT_SECONDS - elapsed))
        interval = min(interval * 2, DATA_VISIBILITY_POLL_MAX_INTERVAL)

    duration_ms = int((time.perf_counter() - started) * 1000)
    WEB_OVERVIEW_LAZY_VISIBILITY_WAIT.labels(outcome="timeout").inc()
    logger.warning(
        "web_overview_lazy_precompute_visibility_check",
        team_id=team_id,
        outcome="timeout",
        polls=polls,
        duration_ms=duration_ms,
        expected=expected,
        visible=last_visible,
    )
    return False


def execute_read_query(
    *,
    team_id: int,
    job_ids: list[str],
    current_start_utc: datetime,
    current_end_utc: datetime,
    previous_start_utc: Optional[datetime],
    previous_end_utc: Optional[datetime],
) -> list:
    """Run the precompute-read SQL via `sync_execute`.

    Bypasses HogQL so we can set `select_sequential_consistency=1` on the SELECT —
    HogQLGlobalSettings forbids extra keys, and the read query shape is stable
    enough that string parameterization is appropriate.
    """
    # Sentinel for the no-compare case: an unsatisfiable window so the *MergeIf
    # aggregates return 0 / NaN for the "previous" columns without changing shape.
    prev_start = previous_start_utc if previous_start_utc is not None else datetime(1970, 1, 1, tzinfo=UTC)
    prev_end = previous_end_utc if previous_end_utc is not None else datetime(1970, 1, 1, tzinfo=UTC)

    tag_queries(product=Product.WEB_ANALYTICS, feature=Feature.QUERY, query_type="web_overview_lazy_query")
    return sync_execute(
        _READ_SQL,
        {
            "team_id": team_id,
            "job_ids": tuple(str(jid) for jid in job_ids),
            "cur_start": current_start_utc,
            "cur_end": current_end_utc,
            "prev_start": prev_start,
            "prev_end": prev_end,
        },
        settings=_READ_SETTINGS,
        team_id=team_id,
    )


def _floor_utc_day(dt_utc: datetime) -> datetime:
    return datetime(dt_utc.year, dt_utc.month, dt_utc.day, tzinfo=UTC)


def _ceil_utc_day(dt_utc: datetime) -> datetime:
    floor = _floor_utc_day(dt_utc)
    if floor == dt_utc:
        return floor
    return floor + timedelta(days=1)


def _empty_response_row() -> list:
    # 5 metric pairs (current, previous) — previous slots are None and discarded
    # downstream when compareFilter.compare is False. When compare is True, the
    # response gets fully populated from the read query, so this default is only
    # used for genuinely empty windows.
    return [0, None, 0, None, 0, None, 0, None, 0, None]


def execute_lazy_precomputed_read(
    runner: "WebOverviewQueryRunner",
) -> Optional[list]:
    """Orchestrate the lazy precompute + read. Returns the response row, or None
    on any failure (caller falls through to the v2/raw path)."""
    # Tag the whole lazy path (INSERT + read) with product/feature so the INSERT
    # `sync_execute` inside `ensure_web_overview_precomputed` doesn't trip
    # DEBUG-mode `UntaggedQueryError`. The read query overrides `query_type`
    # later via `tag_queries(...)` inside `execute_read_query`.
    tag_queries(product=Product.WEB_ANALYTICS, feature=Feature.QUERY)
    team_id = runner.team.pk
    overall_started = time.perf_counter()
    try:
        date_from = runner.query_date_range.date_from()
        date_to = runner.query_date_range.date_to()
        assert date_from is not None and date_to is not None

        # Convert team-tz bounds to tz-aware UTC. We keep `tzinfo` so the HogQL
        # printer doesn't fall back to host-local timezone interpretation when
        # escaping the datetime constants in the filter.
        current_start_utc = date_from.astimezone(UTC)
        current_end_utc = date_to.astimezone(UTC)

        # Expand the precompute span to UTC day boundaries so the framework's
        # daily-window jobs fully cover the team-tz request. Without this, the
        # 08:00 UTC start of "today PT" would fall outside the framework's UTC
        # day window and have no precomputed buckets to read.
        time_range_start = _floor_utc_day(current_start_utc)
        time_range_end = _ceil_utc_day(current_end_utc)

        if time_range_start >= time_range_end:
            logger.info(
                "web_overview_lazy_precompute_empty_range",
                team_id=team_id,
                time_range_start=time_range_start.isoformat(),
                time_range_end=time_range_end.isoformat(),
            )
            return None

        logger.info(
            "web_overview_lazy_precompute_started",
            team_id=team_id,
            time_range_start=time_range_start.isoformat(),
            time_range_end=time_range_end.isoformat(),
            time_range_days=(time_range_end - time_range_start).days,
        )

        ensure_started = time.perf_counter()
        result = ensure_web_overview_precomputed(
            runner=runner,
            time_range_start=time_range_start,
            time_range_end=time_range_end,
        )
        ensure_duration_ms = int((time.perf_counter() - ensure_started) * 1000)

        logger.info(
            "web_overview_lazy_precompute_ensure_done",
            team_id=team_id,
            job_count=len(result.job_ids),
            ensure_duration_ms=ensure_duration_ms,
        )

        if not result.job_ids:
            return None

        if not result.ready:
            logger.info(
                "web_overview_lazy_precompute_current_not_ready",
                team_id=team_id,
                job_count=len(result.job_ids),
            )
            return None

        job_ids: list[str] = [str(jid) for jid in result.job_ids]
        # Track exactly which job_ids this request INSERTed (current + previous
        # `ensure_*` calls). Only these are at risk of replication lag on the
        # read replica — pre-existing READY jobs returned in `result.job_ids`
        # were written by earlier requests and have long since propagated.
        # `len(job_ids)` cannot serve as the gate because it includes those
        # warm-cache entries: a warm-cache hit returns N cached jobs and no
        # writes, but `len(job_ids) > 0` would still be True and we'd wait
        # needlessly. See `LazyComputationResult.inserted_job_ids` docstring.
        inserted_job_ids: list[str] = [str(jid) for jid in result.inserted_job_ids]

        previous_start_utc: Optional[datetime] = None
        previous_end_utc: Optional[datetime] = None
        if runner.query_compare_to_date_range is not None:
            prev_from = runner.query_compare_to_date_range.date_from()
            prev_to = runner.query_compare_to_date_range.date_to()
            if prev_from is not None and prev_to is not None:
                previous_start_utc = prev_from.astimezone(UTC)
                previous_end_utc = prev_to.astimezone(UTC)

                # Precompute the previous period too — without this, the read
                # query's `WHERE job_id IN %(job_ids)s` filter has no rows
                # covering the previous window and every `*MergeIf(..., prev_*)`
                # returns 0/NaN, silently breaking compare-period metrics.
                prev_range_start = _floor_utc_day(previous_start_utc)
                prev_range_end = _ceil_utc_day(previous_end_utc)
                if prev_range_start < prev_range_end:
                    prev_ensure_started = time.perf_counter()
                    prev_result = ensure_web_overview_precomputed(
                        runner=runner,
                        time_range_start=prev_range_start,
                        time_range_end=prev_range_end,
                    )
                    ensure_duration_ms += int((time.perf_counter() - prev_ensure_started) * 1000)

                    if not prev_result.ready:
                        logger.info(
                            "web_overview_lazy_precompute_previous_not_ready",
                            team_id=team_id,
                            prev_job_count=len(prev_result.job_ids),
                        )
                        return None

                    job_ids.extend(str(jid) for jid in prev_result.job_ids)
                    inserted_job_ids.extend(str(jid) for jid in prev_result.inserted_job_ids)

        # If anything was newly INSERTed during this request, poll the
        # Distributed read path until exactly those fresh parts are visible on
        # the same replica the SELECT will land on. Without this, the SELECT
        # can hit a replica that's still fetching the just-INSERTed parts and
        # silently under-count the period whose data is mid-propagation —
        # observed empirically on first cold-cache load with compareFilter on,
        # where previous-period counts collapse to ~1% of actual then settle
        # on refresh. We pass only `inserted_job_ids` (not all of `job_ids`)
        # so the count expectation matches the parts actually at risk; pre-
        # existing cached jobs are already visible everywhere and would
        # otherwise falsely block this gate if they happen to have zero rows.
        if inserted_job_ids:
            if not _wait_for_data_visible(team_id, inserted_job_ids):
                return None

        read_started = time.perf_counter()
        rows = execute_read_query(
            team_id=team_id,
            job_ids=job_ids,
            current_start_utc=current_start_utc,
            current_end_utc=current_end_utc,
            previous_start_utc=previous_start_utc,
            previous_end_utc=previous_end_utc,
        )
        read_duration_ms = int((time.perf_counter() - read_started) * 1000)
        total_duration_ms = int((time.perf_counter() - overall_started) * 1000)

        logger.info(
            "web_overview_lazy_precompute_completed",
            team_id=team_id,
            job_count=len(result.job_ids),
            jobs_inserted=len(inserted_job_ids),
            rows_returned=len(rows) if rows else 0,
            ensure_duration_ms=ensure_duration_ms,
            read_duration_ms=read_duration_ms,
            total_duration_ms=total_duration_ms,
        )
        if not rows:
            return _empty_response_row()
        return list(rows[0])
    except Exception as exc:
        WEB_OVERVIEW_LAZY_FAILED.labels(error_type=type(exc).__name__).inc()
        logger.exception(
            "web_overview_lazy_precompute_failed",
            team_id=team_id,
            error_type=type(exc).__name__,
            total_duration_ms=int((time.perf_counter() - overall_started) * 1000),
        )
        return None
