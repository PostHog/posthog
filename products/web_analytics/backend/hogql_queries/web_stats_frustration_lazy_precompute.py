"""Lazy precompute path for the Web Analytics FRUSTRATION metrics tile.

Mirrors `web_stats_paths_lazy_precompute.py` and shares its eligibility gate
via `web_lazy_precompute_common`. The precomputed table stores one row per
(team, job, UTC hour, breakdown_value) where `breakdown_value` is whatever
the strategy's `_counts_breakdown_value()` emits (typically the URL path
for the only `breakdownBy` the frustration tile ships today). For each
session we sum the per-session rage / dead / exception counts; rows under
the same `(hour, breakdown_value)` are summed via `sumMerge` at read time.
"""

import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Optional

import structlog
from prometheus_client import Counter, Histogram

from posthog.schema import HogQLQueryModifiers, WebAnalyticsOrderByFields, WebStatsBreakdown

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
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
    host_filter_expr,
    log_eligibility_outcome,
    test_account_filter_expr,
)

if TYPE_CHECKING:
    from products.web_analytics.backend.hogql_queries.stats_table import WebStatsTableQueryRunner

logger = structlog.get_logger(__name__)


# Allowlist of exception class names we expect on the lazy path. Anything
# outside this set is collapsed to "other" so dependency-leaking dynamic
# exception names can't blow up Prometheus label cardinality.
_KNOWN_FAILED_ERROR_TYPES: set[str] = {
    "ServerException",
    "NetworkError",
    "OperationalError",
    "IntegrityError",
    "AssertionError",
    "AttributeError",
    "KeyError",
    "ValueError",
    "TypeError",
    "TimeoutError",
}


def _bucket_error_label(exc: BaseException) -> str:
    name = type(exc).__name__
    return name if name in _KNOWN_FAILED_ERROR_TYPES else "other"


WEB_STATS_FRUSTRATION_LAZY_FAILED = Counter(
    "web_stats_frustration_lazy_precompute_failed_total",
    "Lazy precompute path (frustration tile) failures, by error class",
    ["error_type"],
)

WEB_STATS_FRUSTRATION_LAZY_EMPTY = Counter(
    "web_stats_frustration_lazy_precompute_empty_total",
    "Lazy precompute reads that returned zero rows.",
)

WEB_STATS_FRUSTRATION_LAZY_ROWS = Histogram(
    "web_stats_frustration_lazy_precompute_rows",
    "Distinct `breakdown_value` rows returned by the lazy precompute read (post-LIMIT cap).",
    buckets=(1, 10, 100, 500, 1000, 2500, 5000, 7500, 10000, float("inf")),
)


class WrongBreakdown(LazyPrecomputeIneligible):
    pass


class UnsupportedOrderBy(LazyPrecomputeIneligible):
    def __init__(self, field: object):
        self.field = field
        super().__init__(f"field={field!r}")


# Order-by fields the lazy read can produce. The live strategy hard-codes
# (errors DESC, rage_clicks DESC, dead_clicks DESC); we mirror that as the
# default and accept the same three as user-driven overrides.
SUPPORTED_ORDER_BY_FIELDS: set = {
    WebAnalyticsOrderByFields.ERRORS,
    WebAnalyticsOrderByFields.RAGE_CLICKS,
    WebAnalyticsOrderByFields.DEAD_CLICKS,
}


def can_use_lazy_precompute(runner: "WebStatsTableQueryRunner") -> bool:
    """Return True iff the FRUSTRATION tile can be served from precompute."""
    try:
        _check_eligible(runner)
    except LazyPrecomputeIneligible as exc:
        log_eligibility_outcome(log_prefix="web_stats_frustration_lazy_precompute", team_id=runner.team.pk, error=exc)
        return False
    log_eligibility_outcome(log_prefix="web_stats_frustration_lazy_precompute", team_id=runner.team.pk, error=None)
    return True


def _check_eligible(runner: "WebStatsTableQueryRunner") -> None:
    query = runner.query
    if query.breakdownBy != WebStatsBreakdown.FRUSTRATION_METRICS:
        raise WrongBreakdown(f"breakdownBy={query.breakdownBy!r}")
    if query.orderBy:
        order_field = query.orderBy[0]
        if order_field not in SUPPORTED_ORDER_BY_FIELDS:
            raise UnsupportedOrderBy(order_field)

    check_common_eligibility(
        team=runner.team,
        use_web_analytics_precompute=query.useWebAnalyticsPrecompute,
        conversion_goal=query.conversionGoal,
        sampling=query.sampling,
        modifiers=query.modifiers,
        properties=query.properties or [],
        resolve_date_range=lambda: (runner.query_date_range.date_from(), runner.query_date_range.date_to()),
    )


def _events_session_id_expr(runner: "WebStatsTableQueryRunner") -> ast.Expr:
    return runner.events_session_property


def _breakdown_value_expr(runner: "WebStatsTableQueryRunner") -> ast.Expr:
    """Raw pathname for the FRUSTRATION_METRICS breakdown — path cleaning is
    applied at READ time (see `_READ_SQL_TEMPLATE`), not here. Storing raw
    paths keeps the precompute rule-independent: a team can edit cleaning
    rules and the existing precomputed rows remain valid — the next read
    just groups them by the new cleaned values. Mirrors the same pattern in
    `web_stats_paths_lazy_precompute.py`."""
    return ast.Field(chain=["events", "properties", "$pathname"])


# HogQL template for the precompute INSERT — a state-converted version of
# the live `FRUSTRATION_METRICS_INNER_QUERY` + `FrustrationMetricsStrategy`
# outer aggregation. The lazy_computation framework substitutes the listed
# placeholders (including `time_window_min` / `time_window_max`), parses the
# result, and INSERTs into `web_stats_frustration_preaggregated`. The
# framework automatically prepends `team_id`, `job_id` and appends
# `expires_at` to the SELECT.
#
# The inner subquery mirrors the live `FRUSTRATION_METRICS_INNER_QUERY`
# verbatim (per-session counts of rage / dead / exception events), and the
# outer aggregation mirrors the live `FrustrationMetricsStrategy.build_query`
# OUTER (sums collapsed by breakdown) — but bucketed hourly so reads can
# answer arbitrary date ranges via `sumMergeIf`. `sumState(...)` and `sum(...)`
# both aggregate over the same grouped rows, so the HAVING can filter on the
# regular `sum(...)` value while emitting the `sumState(...)` column for
# storage. The outer HAVING is the state-equivalent of the live
# `FrustrationMetricsStrategy._having()` collapse — drop hour-breakdown
# tuples where every metric is zero, which matches what the live outer
# `HAVING or(metric > 0, ...)` drops. Saves storing the all-zero rows that
# the read query would only re-filter via its own `HAVING or(rage > 0, ...)`.
#
# The `event IN (...)` filter restricts the scan to events that can possibly
# contribute to any of the three metrics, plus `$pageview` / `$screen` so the
# session-start anchoring is correct. The forward pad lets sessions that span
# a UTC-day boundary aggregate cleanly — same reasoning as overview/paths.
INSERT_QUERY_TEMPLATE = """
SELECT
    toStartOfHour(start_timestamp) AS time_window_start,
    breakdown_value AS breakdown_value,
    sumState(assumeNotNull(toInt(rage_clicks_count))) AS sum_rage_clicks_state,
    sumState(assumeNotNull(toInt(dead_clicks_count))) AS sum_dead_clicks_state,
    sumState(assumeNotNull(toInt(errors_count))) AS sum_errors_state
FROM (
    SELECT
        {events_session_id} AS session_id,
        {breakdown_value_expr} AS breakdown_value,
        countIf(events.event = '$rageclick') AS rage_clicks_count,
        countIf(events.event = '$dead_click') AS dead_clicks_count,
        countIf(events.event = '$exception') AS errors_count,
        min(session.$start_timestamp) AS start_timestamp
    FROM events
    WHERE and(
        {events_session_id} IS NOT NULL,
        events.event IN ('$pageview', '$screen', '$rageclick', '$dead_click', '$exception'),
        timestamp >= {time_window_min},
        timestamp < ({time_window_max} + toIntervalMinute({pad_minutes})),
        {user_filter},
        {test_account_filter}
    )
    GROUP BY session_id, breakdown_value
    HAVING and(
        breakdown_value IS NOT NULL,
        toStartOfHour(min(session.$start_timestamp)) >= {time_window_min},
        toStartOfHour(min(session.$start_timestamp)) < {time_window_max}
    )
)
GROUP BY time_window_start, breakdown_value
HAVING or(
    sum(rage_clicks_count) > 0,
    sum(dead_clicks_count) > 0,
    sum(errors_count) > 0
)
"""


def ensure_web_stats_frustration_precomputed(
    runner: "WebStatsTableQueryRunner",
    time_range_start: datetime,
    time_range_end: datetime,
) -> LazyComputationResult:
    placeholders: dict[str, ast.Expr] = {
        "events_session_id": _events_session_id_expr(runner),
        "breakdown_value_expr": _breakdown_value_expr(runner),
        "user_filter": host_filter_expr(runner.query.properties or []),
        "test_account_filter": test_account_filter_expr(
            test_account_filters=runner._test_account_filters, team=runner.team
        ),
        "pad_minutes": ast.Constant(value=SESSION_FORWARD_PAD_MINUTES),
    }

    return ensure_precomputed(
        team=runner.team,
        insert_query=INSERT_QUERY_TEMPLATE,
        time_range_start=time_range_start,
        time_range_end=time_range_end,
        ttl_seconds=LAZY_TTL_SECONDS,
        table=LazyComputationTable.WEB_STATS_FRUSTRATION_PREAGGREGATED,
        placeholders=placeholders,
        query_type="web_stats_frustration_lazy_insert",
    )


# Soft budget for the cumulative `ensure_precomputed` time inside a single
# request. The framework's default `wait_timeout_seconds` is 180 s per call; a
# compare-period request makes two back-to-back calls. If the first burns most
# of that budget we skip the second and fall through to the live path to keep
# the overall HTTP request from sitting on a worker past that.
ENSURE_BUDGET_MS = 120 * 1000


# Map runner orderBy → SELECT column name. The strategy's hard-coded default
# is (errors DESC, rage_clicks DESC, dead_clicks DESC) — when the runner has
# no explicit orderBy we sort by errors DESC to match.
_ORDER_BY_TO_COLUMN: dict = {
    WebAnalyticsOrderByFields.ERRORS: "errors",
    WebAnalyticsOrderByFields.RAGE_CLICKS: "rage_clicks",
    WebAnalyticsOrderByFields.DEAD_CLICKS: "dead_clicks",
}


# Read template. The live strategy's `_having()` keeps rows where any of the
# three metrics is non-zero across both periods (matching how the tuple
# comparison `(cur, prev) > (0, 0)` collapses); we mirror that here so the
# pages of zeroes that would otherwise dominate are filtered server-side.
#
# `breakdown_expr` is the (raw or cleaned) breakdown column. Path cleaning is
# applied here in the read rather than baked into the precompute, so rule
# edits don't invalidate stored rows. Cleaning is a chain of nested
# `replaceRegexpAll` calls — see `apply_path_cleaning` — and ClickHouse
# `sumMerge*` is associative across the GROUP BY change, so different cleaned
# values that collapse onto the same key sum correctly.
_READ_SQL_TEMPLATE = """
SELECT
    {breakdown_expr} AS breakdown,
    sumMergeIf(sum_rage_clicks_state, and(time_window_start >= {cur_start}, time_window_start < {cur_end})) AS rage_clicks,
    sumMergeIf(sum_rage_clicks_state, and(time_window_start >= {prev_start}, time_window_start < {prev_end})) AS previous_rage_clicks,
    sumMergeIf(sum_dead_clicks_state, and(time_window_start >= {cur_start}, time_window_start < {cur_end})) AS dead_clicks,
    sumMergeIf(sum_dead_clicks_state, and(time_window_start >= {prev_start}, time_window_start < {prev_end})) AS previous_dead_clicks,
    sumMergeIf(sum_errors_state, and(time_window_start >= {cur_start}, time_window_start < {cur_end})) AS errors,
    sumMergeIf(sum_errors_state, and(time_window_start >= {prev_start}, time_window_start < {prev_end})) AS previous_errors
FROM posthog.web_stats_frustration_preaggregated
WHERE and(team_id = {team_id}, job_id IN {job_ids})
GROUP BY {breakdown_expr}
HAVING or(
    rage_clicks > 0, previous_rage_clicks > 0,
    dead_clicks > 0, previous_dead_clicks > 0,
    errors > 0, previous_errors > 0
)
"""


def _resolve_sort(runner: "WebStatsTableQueryRunner") -> tuple[str, str]:
    """Return `(column, direction)` for the lazy read's ORDER BY.

    Defaults to (errors, DESC) to match the live strategy's primary sort.
    If `runner.query.orderBy` carries a field this module doesn't know how to
    serve, raise rather than silently falling back — the eligibility gate is
    the single source of truth for supported sort fields and the two should
    not drift.
    """
    if runner.query.orderBy:
        field, direction = runner.query.orderBy
        if field not in _ORDER_BY_TO_COLUMN:
            # Defensive: `_check_eligible` already rejects unsupported fields
            # via `SUPPORTED_ORDER_BY_FIELDS`, so reaching here means the gate
            # and `_ORDER_BY_TO_COLUMN` have drifted.
            raise AssertionError(f"unsupported lazy frustration orderBy field={field!r}")
        return _ORDER_BY_TO_COLUMN[field], direction.value if hasattr(direction, "value") else str(direction)
    return "errors", "DESC"


# The live `FrustrationMetricsStrategy._order_by()` is hard-coded to
# `(errors DESC, rage_clicks DESC, dead_clicks DESC)`. We mirror those as
# tiebreakers after the user's primary sort so paginated results are stable
# across the lazy and live paths: rows tied on the primary metric resolve to
# the same order on both engines, which means page N has the same rows
# regardless of which path served it.
_TIEBREAKER_CHAIN = ["errors", "rage_clicks", "dead_clicks"]


def _build_order_by(sort_column: str, sort_direction: str) -> list[ast.OrderExpr]:
    """Sort by the user's pick, then by the live strategy's tiebreaker chain
    (errors DESC, rage_clicks DESC, dead_clicks DESC), then by breakdown for
    a final deterministic tiebreaker."""
    order: list[ast.OrderExpr] = [
        ast.OrderExpr(expr=ast.Field(chain=[sort_column]), order=sort_direction),  # type: ignore[arg-type]
    ]
    for column in _TIEBREAKER_CHAIN:
        if column != sort_column:
            order.append(ast.OrderExpr(expr=ast.Field(chain=[column]), order="DESC"))
    order.append(ast.OrderExpr(expr=ast.Field(chain=["breakdown"]), order="ASC"))
    return order


def execute_read_query(
    *,
    runner: "WebStatsTableQueryRunner",
    job_ids: list[str],
    current_start_utc: datetime,
    current_end_utc: datetime,
    previous_start_utc: Optional[datetime],
    previous_end_utc: Optional[datetime],
    sort_column: str,
    sort_direction: str,
    limit: int,
    offset: int,
) -> list:
    """Read the precomputed FRUSTRATION rows via HogQL.

    Returns the raw `response.results` (list of tuples) so the caller can
    materialize without depending on HogQL's response type. Sort and
    pagination are computed in SQL — the caller materialises the page
    directly without any in-Python re-sort.
    """
    # Sentinel for the no-compare case: an unsatisfiable window so the
    # `sumMergeIf` aggregates return 0 for the "previous" columns without
    # changing the column shape.
    prev_start = previous_start_utc if previous_start_utc is not None else datetime(1970, 1, 1, tzinfo=UTC)
    prev_end = previous_end_utc if previous_end_utc is not None else datetime(1970, 1, 1, tzinfo=UTC)

    placeholders: dict[str, ast.Expr] = {
        "team_id": ast.Constant(value=runner.team.pk),
        "job_ids": ast.Constant(value=[str(jid) for jid in job_ids]),
        "cur_start": ast.Constant(value=current_start_utc),
        "cur_end": ast.Constant(value=current_end_utc),
        "prev_start": ast.Constant(value=prev_start),
        "prev_end": ast.Constant(value=prev_end),
        "breakdown_expr": runner._apply_path_cleaning(ast.Field(chain=["breakdown_value"])),
    }

    parsed = parse_select(_READ_SQL_TEMPLATE, placeholders=placeholders)
    assert isinstance(parsed, ast.SelectQuery), "lazy frustration read template must parse to a SelectQuery"
    parsed.order_by = _build_order_by(sort_column, sort_direction)
    parsed.limit = ast.Constant(value=limit)
    parsed.offset = ast.Constant(value=offset)

    # The precomputed `time_window_start` is UTC; `convertToProjectTimezone`
    # would wrap it in `toTimeZone(..., team_tz)` and break the direct
    # comparison against our UTC bounds.
    modifiers = runner.modifiers.model_copy() if runner.modifiers else HogQLQueryModifiers()
    modifiers.convertToProjectTimezone = False

    tag_queries(product=Product.WEB_ANALYTICS, feature=Feature.QUERY, query_type="web_stats_frustration_lazy_query")
    response = execute_hogql_query(
        query_type="web_stats_frustration_lazy_query",
        query=parsed,
        team=runner.team,
        timings=runner.timings,
        modifiers=modifiers,
        limit_context=runner.limit_context,
    )
    return list(response.results or [])


def execute_lazy_precomputed_read(
    runner: "WebStatsTableQueryRunner",
    *,
    limit: int,
    offset: int,
) -> Optional[list[tuple]]:
    """Orchestrate the lazy precompute + read. Returns the list of result rows,
    or None on any failure (caller falls through to the live path).

    Each row is `(breakdown, rage_clicks, previous_rage_clicks, dead_clicks,
    previous_dead_clicks, errors, previous_errors)`. The caller fetches
    `limit + 1` to detect `hasMore` and pivots the flat columns back into
    the runner's tuple-of-(current, previous) response shape.
    """
    tag_queries(product=Product.WEB_ANALYTICS, feature=Feature.QUERY)
    team_id = runner.team.pk
    overall_started = time.perf_counter()
    try:
        date_from = runner.query_date_range.date_from()
        date_to = runner.query_date_range.date_to()
        assert date_from is not None and date_to is not None

        current_start_utc = date_from.astimezone(UTC)
        current_end_utc = date_to.astimezone(UTC)
        time_range_start = floor_utc_day(current_start_utc)
        time_range_end = ceil_utc_day(current_end_utc)

        if time_range_start >= time_range_end:
            logger.info(
                "web_stats_frustration_lazy_precompute_empty_range",
                team_id=team_id,
                time_range_start=time_range_start.isoformat(),
                time_range_end=time_range_end.isoformat(),
            )
            return None

        logger.info(
            "web_stats_frustration_lazy_precompute_started",
            team_id=team_id,
            time_range_start=time_range_start.isoformat(),
            time_range_end=time_range_end.isoformat(),
            time_range_days=(time_range_end - time_range_start).days,
        )

        ensure_started = time.perf_counter()
        result = ensure_web_stats_frustration_precomputed(
            runner=runner,
            time_range_start=time_range_start,
            time_range_end=time_range_end,
        )
        ensure_duration_ms = int((time.perf_counter() - ensure_started) * 1000)
        logger.info(
            "web_stats_frustration_lazy_precompute_ensure_done",
            team_id=team_id,
            job_count=len(result.job_ids),
            ensure_duration_ms=ensure_duration_ms,
        )

        if not result.job_ids or not result.ready:
            return None

        job_ids: list[str] = [str(jid) for jid in result.job_ids]

        previous_start_utc: Optional[datetime] = None
        previous_end_utc: Optional[datetime] = None
        if runner.query_compare_to_date_range is not None:
            prev_from = runner.query_compare_to_date_range.date_from()
            prev_to = runner.query_compare_to_date_range.date_to()
            if prev_from is not None and prev_to is not None:
                previous_start_utc = prev_from.astimezone(UTC)
                previous_end_utc = prev_to.astimezone(UTC)
                prev_range_start = floor_utc_day(previous_start_utc)
                prev_range_end = ceil_utc_day(previous_end_utc)
                if prev_range_start < prev_range_end:
                    if ensure_duration_ms >= ENSURE_BUDGET_MS:
                        logger.info(
                            "web_stats_frustration_lazy_precompute_compare_budget_exceeded",
                            team_id=team_id,
                            elapsed_ms=ensure_duration_ms,
                            budget_ms=ENSURE_BUDGET_MS,
                        )
                        return None
                    prev_ensure_started = time.perf_counter()
                    prev_result = ensure_web_stats_frustration_precomputed(
                        runner=runner,
                        time_range_start=prev_range_start,
                        time_range_end=prev_range_end,
                    )
                    ensure_duration_ms += int((time.perf_counter() - prev_ensure_started) * 1000)
                    if not prev_result.ready:
                        logger.info(
                            "web_stats_frustration_lazy_precompute_previous_not_ready",
                            team_id=team_id,
                            prev_job_count=len(prev_result.job_ids),
                        )
                        return None
                    job_ids.extend(str(jid) for jid in prev_result.job_ids)

        sort_column, sort_direction = _resolve_sort(runner)
        read_started = time.perf_counter()
        rows = execute_read_query(
            runner=runner,
            job_ids=job_ids,
            current_start_utc=current_start_utc,
            current_end_utc=current_end_utc,
            previous_start_utc=previous_start_utc,
            previous_end_utc=previous_end_utc,
            sort_column=sort_column,
            sort_direction=sort_direction,
            limit=limit,
            offset=offset,
        )
        read_duration_ms = int((time.perf_counter() - read_started) * 1000)
        total_duration_ms = int((time.perf_counter() - overall_started) * 1000)

        rows_returned = len(rows) if rows else 0
        WEB_STATS_FRUSTRATION_LAZY_ROWS.observe(rows_returned)
        if rows_returned == 0:
            WEB_STATS_FRUSTRATION_LAZY_EMPTY.inc()
        logger.info(
            "web_stats_frustration_lazy_precompute_completed",
            team_id=team_id,
            job_count=len(result.job_ids),
            rows_returned=rows_returned,
            ensure_duration_ms=ensure_duration_ms,
            read_duration_ms=read_duration_ms,
            total_duration_ms=total_duration_ms,
        )
        return list(rows) if rows else []
    except Exception as exc:
        WEB_STATS_FRUSTRATION_LAZY_FAILED.labels(error_type=_bucket_error_label(exc)).inc()
        logger.exception(
            "web_stats_frustration_lazy_precompute_failed",
            team_id=team_id,
            error_type=type(exc).__name__,
            total_duration_ms=int((time.perf_counter() - overall_started) * 1000),
        )
        return None
