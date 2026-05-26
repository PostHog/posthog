"""Lazy precompute path for the Web Analytics Active Hours tile.

Backs the calendar-heatmap view of `$pageview` activity by hour-of-day x
day-of-week. Two metrics share one storage table:

- **Unique users** (math=`dau`): session-attributed. The INSERT groups events
  by `$session_id`, picks each session's earliest event, and emits a row in the
  hourly UTC bucket where the session started. The read merges those buckets
  into the (day-of-week, hour-of-day) grid via `toTimeZone(time_window_start,
  team_tz)`. This mirrors web overview's session-start attribution so the
  Active Hours tile's visitor counts align with the rest of the dashboard.
- **Total pageviews** (math=`total`): event-attributed. The INSERT bins events
  directly into hourly UTC buckets via `sumState(1)`. No session aggregation.

Each metric runs as a separate `ensure_precomputed` invocation with its own
`query_hash`, so the cache entries are independent and a team can populate one
tab without paying for the other.

Scoped to web analytics via `CalendarHeatmapFilter.useWebAnalyticsPrecompute`.
Setting the flag elsewhere has no effect unless the team's org also has the
`web-analytics-precompute-toggle` feature flag enabled.
"""

import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Optional

import structlog
from prometheus_client import Counter

from posthog.schema import (
    CalendarHeatmapQuery,
    EventsHeatMapColumnAggregationResult,
    EventsHeatMapDataResult,
    EventsHeatMapRowAggregationResult,
    EventsHeatMapStructuredResult,
)

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tag_queries

from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import (
    LazyComputationResult,
    LazyComputationTable,
    ensure_precomputed,
)
from products.web_analytics.backend.hogql_queries.web_lazy_precompute_common import (
    LAZY_TTL_SECONDS,
    SESSION_FORWARD_PAD_MINUTES,
    LazyPrecomputeIneligible,
    ceil_utc_day,
    check_common_eligibility,
    floor_utc_day,
    log_eligibility_outcome,
    test_account_filter_expr,
)

if TYPE_CHECKING:
    from posthog.hogql_queries.insights.trends.calendar_heatmap_query_runner import CalendarHeatmapQueryRunner

logger = structlog.get_logger(__name__)

_FAMILY = "web_active_hours"


WEB_ACTIVE_HOURS_LAZY_FAILED = Counter(
    "web_active_hours_lazy_precompute_failed_total",
    "Lazy precompute path (active-hours tile) failures, by error class",
    ["error_type"],
)

WEB_ACTIVE_HOURS_LAZY_FALLBACK = Counter(
    "web_active_hours_lazy_precompute_fallback_total",
    "Lazy precompute fall-throughs after the gate accepted, by reason.",
    ["reason"],
)

WEB_ACTIVE_HOURS_LAZY_SUCCESS = Counter(
    "web_active_hours_lazy_precompute_success_total",
    "Requests served from the lazy precompute path.",
)

WEB_ACTIVE_HOURS_LAZY_REJECTED = Counter(
    "web_active_hours_lazy_precompute_rejected_total",
    "Requests refused by the lazy precompute gate, by reason.",
    ["reason"],
)


class WrongDisplay(LazyPrecomputeIneligible):
    pass


class UnsupportedMath(LazyPrecomputeIneligible):
    def __init__(self, math: object):
        self.math = math
        super().__init__(f"math={math!r}")


class UnsupportedSeriesShape(LazyPrecomputeIneligible):
    pass


class UnsupportedEvent(LazyPrecomputeIneligible):
    def __init__(self, event: object):
        self.event = event
        super().__init__(f"event={event!r}")


# Maths we'll accept. Anything else falls through to the raw path.
_SUPPORTED_MATHS: set[str] = {"dau", "total"}


def can_use_lazy_precompute(runner: "CalendarHeatmapQueryRunner") -> bool:
    """Return True iff this calendar-heatmap query can be served from the
    precompute table. Logs the rejection reason so every fall-through is
    attributable."""
    try:
        _check_eligible(runner)
    except LazyPrecomputeIneligible as exc:
        reason = type(exc).__name__
        WEB_ACTIVE_HOURS_LAZY_REJECTED.labels(reason=reason).inc()
        log_eligibility_outcome(log_prefix="web_active_hours_lazy_precompute", team_id=runner.team.pk, error=exc)
        return False
    log_eligibility_outcome(log_prefix="web_active_hours_lazy_precompute", team_id=runner.team.pk, error=None)
    return True


def _check_eligible(runner: "CalendarHeatmapQueryRunner") -> None:
    query = runner.query
    assert isinstance(query, CalendarHeatmapQuery), "_check_eligible called on non-CalendarHeatmap runner"

    # Active-hours-specific gates first. These are cheaper than the org flag
    # round-trip and let us reject obvious shape mismatches without touching
    # the flag service.
    if not query.series or len(query.series) != 1:
        raise UnsupportedSeriesShape()
    series = query.series[0]
    event = getattr(series, "event", None)
    if event != "$pageview":
        raise UnsupportedEvent(event)
    math = getattr(series, "math", None)
    if math not in _SUPPORTED_MATHS:
        raise UnsupportedMath(math)

    # `useWebAnalyticsPrecompute` is the per-query opt-in. The shared gate
    # below also enforces the org-level feature flag, so both bars have to be
    # met for the precompute to engage.
    use_web_analytics_precompute = bool(
        query.calendarHeatmapFilter and query.calendarHeatmapFilter.useWebAnalyticsPrecompute
    )

    check_common_eligibility(
        team=runner.team,
        use_web_analytics_precompute=use_web_analytics_precompute,
        conversion_goal=query.conversionGoal,
        sampling=None,  # CalendarHeatmapQuery has no top-level sampling field
        # `query.modifiers` (the raw request body) — NOT `runner.modifiers`
        # (the post-default-resolution view). `create_default_modifiers_for_team`
        # injects `sessionsV2JoinMode=UUID` if the request didn't specify one,
        # so passing the resolved view would reject every default request.
        # Production query_log shows ~0 web-analytics queries explicitly set
        # this modifier, so the gate effectively only fires when someone opts
        # into UUID mode by hand (same behaviour as the sibling lazy paths).
        modifiers=query.modifiers,
        properties=query.properties or [],
        resolve_date_range=lambda: (runner.query_date_range.date_from(), runner.query_date_range.date_to()),
    )


# HogQL INSERT template for the unique-users tab. Session-attributed: group
# events by `$session_id`, attribute each session to the hour its first event
# fired, emit one `uniqState(person_id)` row per hourly bucket. Same shape and
# rationale as `web_overview_lazy_precompute.py`'s INSERT (forward-pad to catch
# events spilling past a daily UTC boundary; HAVING gates by session start).
#
# Note: `sum_events_state` is omitted intentionally — the framework derives the
# INSERT column list from SELECT aliases, so missing columns fall back to the
# CH type's default (empty AggregateFunction state). Reads for this metric only
# touch `uniq_users_state`, so the empty `sum_events_state` is never consulted.
_INSERT_UNIQUE_USERS_TEMPLATE = """
SELECT
    toStartOfHour(start_timestamp) AS time_window_start,
    uniqState(session_person_id) AS uniq_users_state
FROM (
    SELECT
        any(events.person_id) AS session_person_id,
        {events_session_id} AS session_id,
        min(session.$start_timestamp) AS start_timestamp
    FROM events
    WHERE and(
        {events_session_id} IS NOT NULL,
        equals(event, '$pageview'),
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


# HogQL INSERT template for the total-pageviews tab. Event-attributed: bin
# events directly into hourly UTC buckets via `sumState(1)`. No session
# aggregation, no forward pad needed — each event independently contributes
# to its own hour. `uniq_users_state` omitted, same rationale as above.
_INSERT_TOTAL_EVENTS_TEMPLATE = """
SELECT
    toStartOfHour(timestamp) AS time_window_start,
    sumState(toInt64(1)) AS sum_events_state
FROM events
WHERE and(
    equals(event, '$pageview'),
    timestamp >= {time_window_min},
    timestamp < {time_window_max},
    {user_filter},
    {test_account_filter}
)
GROUP BY time_window_start
"""


def _events_session_id_expr(runner: "CalendarHeatmapQueryRunner") -> ast.Expr:
    # Mirror what web analytics runners pick: `events.$session_id` in normal
    # mode, `events.$session_id_uuid` would be the UUID variant — gated out
    # by `SessionsV2JoinMode == uuid` upstream.
    return ast.Field(chain=["events", "$session_id"])


def _user_filter_expr(runner: "CalendarHeatmapQueryRunner") -> ast.Expr:
    # `property_to_expr` handles every event/session/person filter type and
    # operator HogQL supports. Empty list returns `True` so the INSERT WHERE
    # remains valid.
    if not runner.query.properties:
        return ast.Constant(value=True)
    return property_to_expr(runner.query.properties, team=runner.team)


def _test_account_filter_for_runner(runner: "CalendarHeatmapQueryRunner") -> ast.Expr:
    # Convert the runner's resolved test-account filter list into an AST. Empty
    # list returns `True`.
    if not runner.query.filterTestAccounts:
        return ast.Constant(value=True)
    test_account_filters = runner.team.test_account_filters or []
    return test_account_filter_expr(test_account_filters=test_account_filters, team=runner.team)


def ensure_active_hours_precomputed(
    runner: "CalendarHeatmapQueryRunner",
    time_range_start: datetime,
    time_range_end: datetime,
    math: str,
) -> LazyComputationResult:
    """Run the INSERT side. `math` picks the template; the resulting query_hash
    differs by template so unique-users and total-pageviews jobs are isolated."""
    placeholders: dict[str, ast.Expr] = {
        "events_session_id": _events_session_id_expr(runner),
        "user_filter": _user_filter_expr(runner),
        "test_account_filter": _test_account_filter_for_runner(runner),
        "pad_minutes": ast.Constant(value=SESSION_FORWARD_PAD_MINUTES),
    }

    if math == "dau":
        insert_query = _INSERT_UNIQUE_USERS_TEMPLATE
        query_type = "web_active_hours_lazy_insert_dau"
    else:
        insert_query = _INSERT_TOTAL_EVENTS_TEMPLATE
        query_type = "web_active_hours_lazy_insert_total"

    return ensure_precomputed(
        team=runner.team,
        insert_query=insert_query,
        time_range_start=time_range_start,
        time_range_end=time_range_end,
        ttl_seconds=LAZY_TTL_SECONDS,
        table=LazyComputationTable.WEB_ACTIVE_HOURS_PREAGGREGATED,
        placeholders=placeholders,
        query_type=query_type,
    )


# Read template — single outer SELECT returning one row with four columns:
#   - `cells`: array of (day, hour, value) tuples per (day-of-week, hour-of-day) cell
#   - `days`:  array of (day, value) tuples per day-of-week (across all hours)
#   - `hours`: array of (hour, value) tuples per hour-of-day (across all days)
#   - `total`: scalar overall aggregate
#
# uniq cannot be derived from cell sums (HLL state doesn't add up), so each
# aggregation shape needs its own `GROUP BY` over `web_active_hours_preaggregated`.
# Inline subqueries in the projection list keep this as one SELECT and one
# HogQL round-trip; ClickHouse evaluates each subquery independently with the
# same per-row filters.
#
# `toTimeZone(time_window_start, {team_tz})` shifts the stored UTC hour to the
# team's local time before binning. Reads stay correct for any whole-hour-offset
# timezone; half-hour-offset teams are gated out upstream via
# `is_integer_timezone`.
#
# Settings (`load_balancing=in_order`, `optimize_skip_unused_shards`) come for
# free from `WebActiveHoursPreaggregatedTable.top_level_settings` — registered
# in `posthog/hogql/database/schema/web_active_hours_preaggregated.py`.
_READ_TEMPLATE = """
SELECT
    (
        SELECT groupArray(tuple(day, hour, value))
        FROM (
            SELECT
                toDayOfWeek(toTimeZone(time_window_start, {team_tz})) AS day,
                toHour(toTimeZone(time_window_start, {team_tz})) AS hour,
                {metric_expr} AS value
            FROM web_active_hours_preaggregated
            WHERE team_id = {team_id}
              AND job_id IN {job_ids}
              AND time_window_start >= {cur_start}
              AND time_window_start < {cur_end}
            GROUP BY day, hour
        )
    ) AS cells,
    (
        SELECT groupArray(tuple(day, value))
        FROM (
            SELECT
                toDayOfWeek(toTimeZone(time_window_start, {team_tz})) AS day,
                {metric_expr} AS value
            FROM web_active_hours_preaggregated
            WHERE team_id = {team_id}
              AND job_id IN {job_ids}
              AND time_window_start >= {cur_start}
              AND time_window_start < {cur_end}
            GROUP BY day
        )
    ) AS days,
    (
        SELECT groupArray(tuple(hour, value))
        FROM (
            SELECT
                toHour(toTimeZone(time_window_start, {team_tz})) AS hour,
                {metric_expr} AS value
            FROM web_active_hours_preaggregated
            WHERE team_id = {team_id}
              AND job_id IN {job_ids}
              AND time_window_start >= {cur_start}
              AND time_window_start < {cur_end}
            GROUP BY hour
        )
    ) AS hours,
    (
        SELECT {metric_expr}
        FROM web_active_hours_preaggregated
        WHERE team_id = {team_id}
          AND job_id IN {job_ids}
          AND time_window_start >= {cur_start}
          AND time_window_start < {cur_end}
    ) AS total
"""


def _metric_expr_ast(math: str) -> ast.Expr:
    if math == "dau":
        return ast.Call(name="uniqMerge", args=[ast.Field(chain=["uniq_users_state"])])
    return ast.Call(name="sumMerge", args=[ast.Field(chain=["sum_events_state"])])


def _execute_read_query(
    *,
    runner: "CalendarHeatmapQueryRunner",
    job_ids: list[str],
    current_start_utc: datetime,
    current_end_utc: datetime,
    math: str,
) -> EventsHeatMapStructuredResult:
    """Run one HogQL UNION ALL query that returns all four aggregation shapes
    and assemble the response shape the frontend expects."""
    metric_expr = _metric_expr_ast(math)
    placeholders: dict[str, ast.Expr] = {
        "team_tz": ast.Constant(value=runner.team.timezone),
        "team_id": ast.Constant(value=runner.team.pk),
        "job_ids": ast.Tuple(exprs=[ast.Constant(value=str(jid)) for jid in job_ids]),
        "cur_start": ast.Constant(value=current_start_utc),
        "cur_end": ast.Constant(value=current_end_utc),
        "metric_expr": metric_expr,
    }

    tag_queries(product=Product.WEB_ANALYTICS, feature=Feature.QUERY, query_type=f"web_active_hours_lazy_query_{math}")

    response = execute_hogql_query(
        query=parse_select(_READ_TEMPLATE, placeholders=placeholders),
        team=runner.team,
        timings=runner.timings,
        modifiers=runner.modifiers,
        query_type=f"web_active_hours_lazy_query_{math}",
    )

    # Single row, four columns: (cells_array, days_array, hours_array, total_scalar).
    # Each array element is a tuple from the corresponding `groupArray(tuple(...))`.
    if not response.results:
        return EventsHeatMapStructuredResult(data=[], rowAggregations=[], columnAggregations=[], allAggregations=0)

    cells_raw, days_raw, hours_raw, total_raw = response.results[0]
    cells = [
        EventsHeatMapDataResult(row=int(day), column=int(hour), value=int(value))
        for day, hour, value in cells_raw or []
    ]
    day_aggs = [EventsHeatMapRowAggregationResult(row=int(day), value=int(value)) for day, value in days_raw or []]
    hour_aggs = [
        EventsHeatMapColumnAggregationResult(column=int(hour), value=int(value)) for hour, value in hours_raw or []
    ]
    overall = int(total_raw or 0)

    return EventsHeatMapStructuredResult(
        data=cells, rowAggregations=day_aggs, columnAggregations=hour_aggs, allAggregations=overall
    )


def execute_lazy_precomputed_read(
    runner: "CalendarHeatmapQueryRunner",
) -> Optional[EventsHeatMapStructuredResult]:
    """Orchestrate the lazy precompute + read. Returns the heatmap result, or
    None on any failure (caller falls through to the raw path)."""
    # Tag the whole lazy path (INSERT + read) with product/feature so the
    # INSERT `sync_execute` inside `ensure_active_hours_precomputed` doesn't
    # trip DEBUG-mode `UntaggedQueryError`. The read query overrides
    # `query_type` later inside `_execute_read_query`.
    tag_queries(product=Product.WEB_ANALYTICS, feature=Feature.QUERY)
    team_id = runner.team.pk
    overall_started = time.perf_counter()

    try:
        date_from = runner.query_date_range.date_from()
        date_to = runner.query_date_range.date_to()
        assert date_from is not None and date_to is not None

        # Convert team-tz bounds to tz-aware UTC. We keep `tzinfo` so the HogQL
        # printer doesn't fall back to host-local interpretation when escaping
        # the datetime constants in the filter.
        current_start_utc = date_from.astimezone(UTC)
        current_end_utc = date_to.astimezone(UTC)

        # Expand the precompute span to UTC day boundaries so the framework's
        # daily-window jobs fully cover the team-tz request.
        time_range_start = floor_utc_day(current_start_utc)
        time_range_end = ceil_utc_day(current_end_utc)

        if time_range_start >= time_range_end:
            WEB_ACTIVE_HOURS_LAZY_FALLBACK.labels(reason="empty_range").inc()
            return None

        math = runner.query.series[0].math
        assert isinstance(math, str)

        logger.info(
            "web_active_hours_lazy_precompute_started",
            team_id=team_id,
            math=math,
            time_range_start=time_range_start.isoformat(),
            time_range_end=time_range_end.isoformat(),
            time_range_days=(time_range_end - time_range_start).days,
        )

        ensure_started = time.perf_counter()
        result = ensure_active_hours_precomputed(
            runner=runner,
            time_range_start=time_range_start,
            time_range_end=time_range_end,
            math=math,
        )
        ensure_duration_ms = int((time.perf_counter() - ensure_started) * 1000)

        if not result.job_ids:
            WEB_ACTIVE_HOURS_LAZY_FALLBACK.labels(reason="no_job_ids").inc()
            return None
        if not result.ready:
            WEB_ACTIVE_HOURS_LAZY_FALLBACK.labels(reason="current_not_ready").inc()
            return None

        read_started = time.perf_counter()
        response = _execute_read_query(
            runner=runner,
            job_ids=[str(jid) for jid in result.job_ids],
            current_start_utc=current_start_utc,
            current_end_utc=current_end_utc,
            math=math,
        )
        read_duration_ms = int((time.perf_counter() - read_started) * 1000)

        WEB_ACTIVE_HOURS_LAZY_SUCCESS.inc()
        logger.info(
            "web_active_hours_lazy_precompute_completed",
            team_id=team_id,
            math=math,
            job_count=len(result.job_ids),
            cells_returned=len(response.data),
            ensure_duration_ms=ensure_duration_ms,
            read_duration_ms=read_duration_ms,
            total_duration_ms=int((time.perf_counter() - overall_started) * 1000),
        )
        return response
    except Exception as exc:
        WEB_ACTIVE_HOURS_LAZY_FAILED.labels(error_type=type(exc).__name__).inc()
        logger.exception(
            "web_active_hours_lazy_precompute_failed",
            team_id=team_id,
            error_type=type(exc).__name__,
            total_duration_ms=int((time.perf_counter() - overall_started) * 1000),
        )
        return None
