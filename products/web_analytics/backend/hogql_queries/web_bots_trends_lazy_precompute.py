"""Serve the AI/Search bots request trend chart from the shared bot precompute buckets.

The chart is a `TrendsQuery` the bots tab builds: one `GroupNode` OR-ing `$pageview`,
`$screen` and `$http_log`, broken down by crawler, category, host, or path. This module
reads the same `web_bots_preaggregated` rows the Crawlers and Most crawled paths tables
read — one job set covers all six tiles — and hands the rows to the live trends runner's
own `build_series_response`, so labels, the "Other" bucket, ordering and the response
contract come from the live path instead of a second implementation of it.

Anything outside the shape the buckets can reproduce stays on the live trends path.
"""

import time
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Optional

import structlog
from prometheus_client import Counter

from posthog.schema import (
    ChartDisplayType,
    DateRange,
    EventPropertyFilter,
    EventsNode,
    FilterLogicalOperator,
    GroupNode,
    HogQLQueryResponse,
    IntervalType,
    PropertyOperator,
    TrendsQuery,
    WebBotsBreakdown,
    WebBotsTableQuery,
)

from posthog.hogql import ast
from posthog.hogql.constants import BREAKDOWN_VALUE_MAX_LENGTH, HogQLGlobalSettings, get_breakdown_limit_for_context
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.hogql_queries.insights.trends.series_with_extras import SeriesWithExtras
from posthog.hogql_queries.utils.breakdowns import BREAKDOWN_NULL_STRING_LABEL, BREAKDOWN_OTHER_STRING_LABEL

from products.web_analytics.backend.hogql_queries.web_bots import BOT_ANALYTICS_EVENTS, WebBotsTableQueryRunner
from products.web_analytics.backend.hogql_queries.web_bots_lazy_precompute import (
    FAMILY as BOTS_FAMILY,
    can_use_lazy_precompute,
    ensure_web_bots_precomputed,
    floor_utc_hour,
)
from products.web_analytics.backend.hogql_queries.web_lazy_precompute_common import handle_stale_served

if TYPE_CHECKING:
    from products.web_analytics.backend.hogql_queries.web_trends import WebTrendsQueryRunner

logger = structlog.get_logger(__name__)

WEB_BOTS_TRENDS_LAZY_FALLBACK = Counter(
    "web_bots_trends_lazy_precompute_fallback_total",
    "Bot trend reads that left the precompute path, by reason.",
    ["reason"],
)

WEB_BOTS_TRENDS_LAZY_SERVED = Counter(
    "web_bots_trends_lazy_precompute_served_total",
    "Bot trend reads served from the precompute buckets.",
)

WEB_BOTS_TRENDS_LAZY_FAILED = Counter(
    "web_bots_trends_lazy_precompute_failed_total",
    "Bot trend precompute path failures, by error class.",
    ["error_type"],
)

# Breakdown property → the precompute column holding it, and the events expression the live
# partial-hour branch reads it from. A breakdown outside this map has no stored dimension.
_DIMENSIONS: dict[str, tuple[str, str]] = {
    "$virt_bot_name": ("bot_name", "`$virt_bot_name`"),
    "$virt_traffic_category": ("category", "`$virt_traffic_category`"),
    "$host": ("host", "properties.$host"),
    "$pathname": ("pathname", "properties.$pathname"),
}

# Interval → the grain the read query buckets on. Hour intervals need hourly buckets; every
# longer interval is folded into the series axis in Python, from `QueryDateRange.all_values()`
# itself, so week start day and month lengths are never re-derived here.
_BUCKET_GRAIN: dict[str, str] = {
    "hour": "toStartOfHour",
    "day": "toStartOfDay",
    "week": "toStartOfDay",
    "month": "toStartOfDay",
}

# The bot scope the tab appends to every tile's filter list. The precompute insert already
# hardcodes both conditions, so dropping exactly these two shapes lets the trend chart share
# job identity with the Crawlers and Most crawled paths tables. Any other filter on the same
# keys is kept, which just gives that query its own job namespace.
_SCOPE_FILTERS: tuple[EventPropertyFilter, ...] = (
    EventPropertyFilter(key="$virt_is_bot", value=["true"], operator=PropertyOperator.EXACT),
    EventPropertyFilter(key="$virt_bot_name", value=[""], operator=PropertyOperator.IS_NOT),
)

SOURCE_QUERY = """
SELECT time_window_start AS bucket_time, {stored_dimension} AS dimension, requests AS requests
FROM posthog.web_bots_preaggregated
WHERE job_id IN {job_ids}
    AND time_window_start >= {full_start}
    AND time_window_start < {full_end}
UNION ALL
SELECT
    toStartOfHour(timestamp) AS bucket_time,
    {live_dimension} AS dimension,
    count() AS requests
FROM events
WHERE and(
    event IN {bot_events},
    `$virt_is_bot` = true,
    `$virt_bot_name` != '',
    timestamp >= {range_start},
    timestamp <= {range_end},
    (timestamp < {full_start} OR timestamp >= {full_end}),
    {all_properties}
)
GROUP BY bucket_time, dimension
"""

# Ranking and truncation mirror the live trends outer query: rank on (ordering, total desc,
# value asc), keep the top `breakdown_limit`, and fold the rest into one "Other" row. The
# null bucket carries ordering 1, so it only wins a rank slot once every real value has one.
READ_QUERY = """
WITH
    bot_requests AS ({source}),
    per_bucket AS (
        SELECT
            formatDateTime({bucket_expr}, '%Y-%m-%d %H:%i:%S') AS bucket,
            ifNull(nullIf(left(toString(dimension), {max_length}), ''), {null_label}) AS breakdown_value,
            sum(requests) AS value
        FROM bot_requests
        GROUP BY bucket, breakdown_value
    ),
    totals AS (
        SELECT
            breakdown_value AS breakdown_value,
            sum(value) AS series_total,
            {ordering} AS ordering
        FROM per_bucket
        GROUP BY breakdown_value
    ),
    ranked AS (
        SELECT
            breakdown_value AS breakdown_value,
            row_number() OVER (ORDER BY ordering ASC, series_total DESC, breakdown_value ASC) AS breakdown_rank
        FROM totals
    )
SELECT
    if(ranked.breakdown_rank <= {breakdown_limit}, per_bucket.breakdown_value, {other_label}) AS breakdown_value,
    per_bucket.bucket AS bucket,
    sum(per_bucket.value) AS value
FROM per_bucket
INNER JOIN ranked ON ranked.breakdown_value = per_bucket.breakdown_value
GROUP BY breakdown_value, bucket
"""


def _fall_back(team_id: int, reason: str) -> None:
    """Count and log a read that left the precompute path, so one Loki query attributes them all."""
    WEB_BOTS_TRENDS_LAZY_FALLBACK.labels(reason=reason).inc()
    logger.info("web_bots_trends_lazy_precompute_fallback", team_id=team_id, reason=reason)


def bots_trends_breakdown(query: TrendsQuery) -> Optional[str]:
    """The breakdown property this trend can be served on, or None to stay on the live path.

    The allowlist is deliberately narrow: it admits only the bots tab's own chart shape, so a
    trend the buckets cannot reproduce exactly never reaches the read query.
    """
    breakdown_filter = query.breakdownFilter
    if breakdown_filter is None or breakdown_filter.breakdown is None:
        return None
    if breakdown_filter.breakdowns is not None:
        return None
    if breakdown_filter.breakdown_type != "event":
        return None
    if not isinstance(breakdown_filter.breakdown, str) or breakdown_filter.breakdown not in _DIMENSIONS:
        return None
    # Both rewrite the breakdown value before ranking, and neither is reproducible from the
    # stored dimension without re-deriving the team's path cleaning rules here.
    if breakdown_filter.breakdown_normalize_url or breakdown_filter.breakdown_path_cleaning:
        return None
    if breakdown_filter.breakdown_histogram_bin_count is not None:
        return None
    if breakdown_filter.breakdown_group_type_index is not None:
        return None
    if breakdown_filter.breakdown_limit is not None:
        return None

    if not _is_bot_request_series(query):
        return None
    if query.conversionGoal is not None:
        return None
    if query.aggregation_group_type_index is not None:
        return None
    if query.samplingFactor is not None:
        return None
    if query.compareFilter is not None and query.compareFilter.compare:
        return None

    trends_filter = query.trendsFilter
    if trends_filter is not None:
        if trends_filter.display is not None and trends_filter.display != ChartDisplayType.ACTIONS_LINE_GRAPH:
            return None
        if trends_filter.formula or trends_filter.formulas or trends_filter.formulaNodes:
            return None
        if trends_filter.smoothingIntervals is not None and trends_filter.smoothingIntervals > 1:
            return None
        if trends_filter.hideWeekends:
            return None

    if (query.interval or IntervalType.DAY).value not in _BUCKET_GRAIN:
        return None
    if query.dateRange is not None and (query.dateRange.explicitDate or query.dateRange.daysOfWeek):
        return None
    return breakdown_filter.breakdown


def _is_bot_request_series(query: TrendsQuery) -> bool:
    """Whether the query counts exactly the three bot events as one OR-ed total series."""
    if len(query.series) != 1:
        return False
    series = query.series[0]
    if not isinstance(series, GroupNode) or series.operator != FilterLogicalOperator.OR_:
        return False
    if series.math not in (None, "total"):
        return False
    if len(series.nodes) != len(BOT_ANALYTICS_EVENTS):
        return False
    events = set()
    for node in series.nodes:
        if not isinstance(node, EventsNode) or node.event is None:
            return False
        if node.math not in (None, "total") or node.properties or node.fixedProperties:
            return False
        events.add(node.event)
    return events == set(BOT_ANALYTICS_EVENTS)


def _scoped_properties(query: TrendsQuery) -> list[Any]:
    """The trend's filters minus the redundant bot-scope pair, so job identity matches the tables."""
    scope = {_filter_identity(f) for f in _SCOPE_FILTERS}
    kept: list[Any] = []
    for prop in list(query.properties or []):
        if isinstance(prop, EventPropertyFilter) and _filter_identity(prop) in scope:
            continue
        kept.append(prop)
    return kept


def _filter_identity(prop: EventPropertyFilter) -> tuple[str, Any, str]:
    return (prop.key, prop.operator, repr(prop.value))


def build_inner_bots_query(
    query: TrendsQuery, properties: list[Any], range_start: datetime, range_end: datetime
) -> WebBotsTableQuery:
    """The table query whose insert the trend borrows.

    The date range is the trend's own resolved range, stated explicitly so the interval
    truncation the trends runner already applied is what the ensure sees. `breakdownBy` does
    not reach the insert, so every trend breakdown maps onto one job set.
    """
    return WebBotsTableQuery(
        breakdownBy=WebBotsBreakdown.CRAWLER,
        properties=properties,
        dateRange=DateRange(
            date_from=range_start.isoformat(),
            date_to=range_end.isoformat(),
            explicitDate=True,
        ),
        filterTestAccounts=query.filterTestAccounts,
        # TrendsQuery carries no `useWebAnalyticsPrecompute` field, so the per-query opt-out
        # cannot reach a trend tile; the rollout flag in the runner's cache key is the switch.
        useWebAnalyticsPrecompute=None,
    )


def execute_lazy_precomputed_bots_trends(
    runner: "WebTrendsQueryRunner",
) -> Optional[tuple[list[dict[str, Any]], bool]]:
    """Serve the bot trend series from precompute, or None to fall back to the live path.

    Returns the formatted results and the `hasMore` flag the live path would have reported
    (true when values were folded into "Other").
    """
    started = time.perf_counter()
    team = runner.team
    try:
        breakdown = bots_trends_breakdown(runner.query)
        if breakdown is None:
            return None

        buckets = runner.query_date_range.all_values()
        range_end = runner.query_date_range.date_to()
        if not buckets or range_end is None:
            _fall_back(team.pk, "empty_range")
            return None
        range_start = buckets[0]

        interval = (runner.query.interval or IntervalType.DAY).value
        # An hour-interval range crossing a DST transition collides two local hours onto one
        # bucket key, or asks for one that does not exist. The live path emits 25 or 23 points
        # there; serving a silently different axis is worse than falling back.
        if interval == "hour" and range_start.utcoffset() != range_end.utcoffset():
            _fall_back(team.pk, "dst_transition")
            return None

        full_start = floor_utc_hour(range_start.astimezone(UTC))
        if full_start < range_start.astimezone(UTC):
            full_start += timedelta(hours=1)
        full_end = floor_utc_hour(range_end.astimezone(UTC))
        if full_start >= full_end:
            _fall_back(team.pk, "no_whole_hour")
            return None

        inner_query = build_inner_bots_query(runner.query, _scoped_properties(runner.query), range_start, range_end)
        inner_runner = WebBotsTableQueryRunner(query=inner_query, team=team, modifiers=runner.modifiers)
        if not can_use_lazy_precompute(inner_runner):
            _fall_back(team.pk, "ineligible")
            return None

        coverage = ensure_web_bots_precomputed(runner=inner_runner, full_start=full_start, full_end=full_end)
        if coverage is None:
            _fall_back(team.pk, "not_ready")
            return None
        if coverage.stale:
            # Family web_bots on purpose: one debounced rebuild refreshes the buckets every
            # bot tile reads, rather than one per breakdown tab.
            handle_stale_served(runner=inner_runner, family=BOTS_FAMILY)

        response = _execute_read_query(
            runner=runner,
            inner_runner=inner_runner,
            breakdown=breakdown,
            interval=interval,
            job_ids=[str(job_id) for job_id in coverage.job_ids],
            full_start=full_start,
            full_end=coverage.covered_until,
        )
        results, has_more = _build_results(runner, response, buckets)
        WEB_BOTS_TRENDS_LAZY_SERVED.inc()
        logger.info(
            "web_bots_trends_lazy_precompute_served",
            team_id=team.pk,
            breakdown=breakdown,
            interval=interval,
            job_count=len(coverage.job_ids),
            stale=coverage.stale,
            total_duration_ms=int((time.perf_counter() - started) * 1000),
        )
        return results, has_more
    except Exception as error:
        WEB_BOTS_TRENDS_LAZY_FAILED.labels(error_type=type(error).__name__).inc()
        logger.exception("web_bots_trends_lazy_precompute_failed", team_id=team.pk)
        return None


def build_read_query(
    *,
    runner: "WebTrendsQueryRunner",
    inner_runner: WebBotsTableQueryRunner,
    breakdown: str,
    interval: str,
    job_ids: list[str],
    full_start: datetime,
    full_end: datetime,
) -> ast.SelectQuery:
    stored_dimension, live_dimension = _DIMENSIONS[breakdown]
    date_placeholders = runner.query_date_range.to_placeholders()
    source = parse_select(
        SOURCE_QUERY.replace("{stored_dimension}", stored_dimension).replace("{live_dimension}", live_dimension),
        placeholders={
            "job_ids": ast.Tuple(exprs=[ast.Constant(value=job_id) for job_id in job_ids]),
            "full_start": ast.Constant(value=full_start),
            "full_end": ast.Constant(value=full_end),
            "bot_events": ast.Tuple(exprs=[ast.Constant(value=event) for event in BOT_ANALYTICS_EVENTS]),
            "range_start": date_placeholders["date_from_with_adjusted_start_of_interval"],
            "range_end": date_placeholders["date_to"],
            "all_properties": inner_runner._all_properties(),
        },
    )
    bucket_expr = ast.Call(
        name=_BUCKET_GRAIN[interval],
        args=[
            ast.Call(
                name="toTimeZone",
                args=[ast.Field(chain=["bucket_time"]), ast.Constant(value=runner.team.timezone)],
            )
        ],
    )
    query = parse_select(
        READ_QUERY,
        placeholders={
            "source": source,
            "bucket_expr": bucket_expr,
            "max_length": ast.Constant(value=BREAKDOWN_VALUE_MAX_LENGTH),
            "null_label": ast.Constant(value=BREAKDOWN_NULL_STRING_LABEL),
            "other_label": ast.Constant(value=BREAKDOWN_OTHER_STRING_LABEL),
            "ordering": _ordering_expr(),
            "breakdown_limit": ast.Constant(value=get_breakdown_limit_for_context(runner.limit_context)),
        },
    )
    assert isinstance(query, ast.SelectQuery)
    return query


def _ordering_expr() -> ast.Expr:
    return ast.Call(
        name="if",
        args=[
            ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Field(chain=["breakdown_value"]),
                right=ast.Constant(value=BREAKDOWN_OTHER_STRING_LABEL),
            ),
            ast.Constant(value=2),
            ast.Call(
                name="if",
                args=[
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=ast.Field(chain=["breakdown_value"]),
                        right=ast.Constant(value=BREAKDOWN_NULL_STRING_LABEL),
                    ),
                    ast.Constant(value=1),
                    ast.Constant(value=0),
                ],
            ),
        ],
    )


def _execute_read_query(
    *,
    runner: "WebTrendsQueryRunner",
    inner_runner: WebBotsTableQueryRunner,
    breakdown: str,
    interval: str,
    job_ids: list[str],
    full_start: datetime,
    full_end: datetime,
) -> HogQLQueryResponse:
    query = build_read_query(
        runner=runner,
        inner_runner=inner_runner,
        breakdown=breakdown,
        interval=interval,
        job_ids=job_ids,
        full_start=full_start,
        full_end=full_end,
    )
    return execute_hogql_query(
        query_type="web_bots_trends_lazy_query",
        query=query,
        team=runner.team,
        timings=runner.timings,
        modifiers=runner.modifiers,
        limit_context=runner.limit_context,
        settings=HogQLGlobalSettings(load_balancing="in_order", optimize_skip_unused_shards=True),
    )


def _build_results(
    runner: "WebTrendsQueryRunner", response: HogQLQueryResponse, buckets: list[datetime]
) -> tuple[list[dict[str, Any]], bool]:
    """Turn `(breakdown_value, bucket, value)` rows into the live path's own series objects.

    Read buckets are hourly or daily; the series axis comes from `QueryDateRange`, so each read
    bucket is folded into the axis bucket that contains it. Missing buckets read as zero, which
    is what the live path's date subqueries produce.
    """
    axis = [bucket.replace(tzinfo=None) for bucket in buckets]
    totals: dict[Any, list[float]] = {}
    series_totals: dict[Any, float] = {}
    for breakdown_value, bucket, value in response.results:
        index = _axis_index(axis, datetime.strptime(bucket, "%Y-%m-%d %H:%M:%S"))
        if index is None:
            continue
        data = totals.setdefault(breakdown_value, [0.0] * len(axis))
        data[index] += float(value)
        series_totals[breakdown_value] = series_totals.get(breakdown_value, 0.0) + float(value)

    # Same final order as the live trends outer query: real values by descending total, then
    # the null bucket, then "Other"; ties break on the value itself.
    def sort_key(breakdown_value: Any) -> tuple[int, float, str]:
        if breakdown_value == BREAKDOWN_OTHER_STRING_LABEL:
            ordering = 2
        elif breakdown_value == BREAKDOWN_NULL_STRING_LABEL:
            ordering = 1
        else:
            ordering = 0
        return (ordering, -series_totals[breakdown_value], str(breakdown_value))

    ordered = sorted(totals, key=sort_key)
    synthetic = HogQLQueryResponse(
        columns=["date", "total", "breakdown_value"],
        results=[[buckets, totals[breakdown_value], breakdown_value] for breakdown_value in ordered],
        hogql=response.hogql,
        timings=response.timings,
        types=response.types,
    )
    series = SeriesWithExtras(
        series=runner.query.series[0],
        series_order=0,
        is_previous_period_series=False,
        overriden_query=None,
        aggregate_values=False,
    )
    results = runner.build_series_response(synthetic, series, series_count=1)
    for item in results:
        item["order"] = 0

    has_more = False
    if any(runner._is_other_breakdown(item["breakdown_value"]) for item in results):
        breakdown_filter = runner.query.breakdownFilter
        if breakdown_filter is not None and breakdown_filter.breakdown_hide_other_aggregation:
            results = [item for item in results if not runner._is_other_breakdown(item["breakdown_value"])]
        has_more = True
    return results, has_more


def _axis_index(axis: list[datetime], bucket: datetime) -> Optional[int]:
    """Index of the axis bucket containing `bucket`, or None when it falls outside the axis."""
    if bucket < axis[0]:
        return None
    low, high = 0, len(axis) - 1
    while low < high:
        middle = (low + high + 1) // 2
        if axis[middle] <= bucket:
            low = middle
        else:
            high = middle - 1
    return low
