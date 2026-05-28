import time
from datetime import (
    UTC,
    datetime,
    time as dt_time,
)
from typing import TYPE_CHECKING, Optional

import structlog
from prometheus_client import Counter

from posthog.schema import (
    HogQLQueryModifiers,
    WebVitalsMetric,
    WebVitalsMetricBand,
    WebVitalsPathBreakdownQueryResponse,
    WebVitalsPathBreakdownResult,
    WebVitalsPathBreakdownResultItem,
    WebVitalsPercentile,
)

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tag_queries

from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import (
    LazyComputationResult,
    LazyComputationTable,
    ensure_precomputed,
)
from products.web_analytics.backend.hogql_queries.web_analytics_lazy_precompute import (
    LAZY_TTL_SECONDS,
    WEB_ANALYTICS_LAZY_PRECOMPUTE_FALLBACK,
    WEB_ANALYTICS_LAZY_PRECOMPUTE_SUCCESS,
    LazyPrecomputeIneligible,
    LazyPrecomputeRunner,
    can_use_lazy_precompute as _can_use_lazy_precompute_shared,
    ceil_utc_day,
    floor_utc_day,
    test_account_filter_expr,
    user_filter_expr,
)

_FAMILY = "web_vitals_paths"

if TYPE_CHECKING:
    from products.web_analytics.backend.hogql_queries.web_vitals_path_breakdown import WebVitalsPathBreakdownQueryRunner

logger = structlog.get_logger(__name__)


WEB_VITALS_LAZY_FAILED = Counter(
    "web_vitals_paths_lazy_precompute_failed_total",
    "Web vitals paths lazy precompute path failures, by error class",
    ["error_type"],
)


class NonDayAlignedRange(LazyPrecomputeIneligible):
    pass


# `date_to` from the query date range arrives as either midnight (exclusive next
# day) or end-of-day (inclusive last day) — both are day-aligned and the bucket
# math still works. Anything else (10:00, 12:00, …) is a sub-day filter we can't
# serve from day buckets.
_DAY_ALIGNED_END_TIMES: frozenset[dt_time] = frozenset(
    [
        dt_time(0, 0, 0, 0),
        dt_time(23, 59, 59, 999999),
    ]
)


def _check_vitals_eligible(runner: LazyPrecomputeRunner) -> None:
    """Reject sub-day date ranges. The runner buckets into team-tz days via
    `toStartOfDay(timestamp, team_tz)`, so the read filter
    (`time_window_start >= cur_start AND ... < cur_end`) compares against
    bucket keys at team-local midnight. A sub-day range like 10:00–12:00 would
    miss the surrounding day bucket and silently return empty results, while
    the raw query computes the same range correctly from event timestamps.
    """
    date_from = runner.query_date_range.date_from()  # type: ignore[attr-defined]
    date_to = runner.query_date_range.date_to()  # type: ignore[attr-defined]
    if date_from is None or date_to is None:
        return  # Caught by check_common_eligible's MissingDateRange.
    if date_from.time() != dt_time(0, 0):
        raise NonDayAlignedRange()
    if date_to.time() not in _DAY_ALIGNED_END_TIMES:
        raise NonDayAlignedRange()


# 1-based ClickHouse `arrayElement` index into the quantiles tuple stored in
# the metric's `quantiles_state` column (`quantiles(0.75, 0.90, 0.99)`).
_PCT_INDEX: dict[WebVitalsPercentile, int] = {
    WebVitalsPercentile.P75: 1,
    WebVitalsPercentile.P90: 2,
    WebVitalsPercentile.P99: 3,
}

_METRIC_STATE_COLUMN: dict[WebVitalsMetric, str] = {
    WebVitalsMetric.INP: "inp_quantiles_state",
    WebVitalsMetric.LCP: "lcp_quantiles_state",
    WebVitalsMetric.CLS: "cls_quantiles_state",
    WebVitalsMetric.FCP: "fcp_quantiles_state",
}


def can_use_lazy_precompute(runner: "WebVitalsPathBreakdownQueryRunner") -> bool:
    """Return True iff the lazy precompute path is eligible for this web vitals
    path-breakdown query — the shared web analytics gate plus a day-alignment
    check on the requested range.

    Bucket key is computed in the team's timezone, so half-hour-offset timezones
    (IST/Newfoundland/Nepal/Iran) are also supported — the integer-timezone gate
    is opted out.
    """
    return _can_use_lazy_precompute_shared(
        runner,
        log_prefix=_FAMILY,
        extra_check=_check_vitals_eligible,
        require_integer_timezone=False,
    )


# HogQL template for the precompute INSERT. The lazy_computation framework
# substitutes the listed placeholders (including `time_window_min` /
# `time_window_max`), parses the result, and INSERTs into
# `web_vitals_paths_preaggregated`. The framework automatically prepends
# `team_id`, `job_id` and appends `expires_at` to the SELECT.
#
# Bucketing strategy: per-(team-tz-day, path), not per-hour. The path-breakdown
# tile only consumes day-aligned date ranges from the dashboard filter, so a
# daily bucket is sufficient and ~24× smaller than hourly. The bucket key is
# `toStartOfDay(timestamp, team_tz)` — start of the team-local day, with the
# underlying Unix timestamp being the UTC instant of that local midnight. This
# aligns cleanly for every timezone (including half-hour offsets like IST),
# which is why this runner opts out of the shared `is_integer_timezone` gate.
#
# Note that a UTC daily INSERT job typically writes into TWO team-tz day
# buckets — events in the first hours of UTC day N belong to team-tz day N-1
# for non-UTC teams. Reads merge both rows via the ReplacingMergeTree key
# `(team_id, job_id, time_window_start, path)`.
#
# The raw vitals query has no session join, so no session-boundary pad on the
# event scan is needed — each event maps to one (team-tz day, path) bucket.
# One state column per metric: ARRAY JOIN would fan one event into four rows
# but the new analyzer rejects bare `events.properties` references inside the
# ARRAY JOIN source array, so we collapse per-event into per-row.
INSERT_QUERY_TEMPLATE = """
SELECT
    toStartOfDay(event_timestamp, {team_tz}) AS time_window_start,
    path AS path,
    quantilesStateIf(0.75, 0.90, 0.99)(assumeNotNull(inp_value), isNotNull(inp_value)) AS inp_quantiles_state,
    quantilesStateIf(0.75, 0.90, 0.99)(assumeNotNull(lcp_value), isNotNull(lcp_value)) AS lcp_quantiles_state,
    quantilesStateIf(0.75, 0.90, 0.99)(assumeNotNull(cls_value), isNotNull(cls_value)) AS cls_quantiles_state,
    quantilesStateIf(0.75, 0.90, 0.99)(assumeNotNull(fcp_value), isNotNull(fcp_value)) AS fcp_quantiles_state
FROM (
    SELECT
        events.timestamp AS event_timestamp,
        {breakdown_by} AS path,
        toFloat(events.properties.`$web_vitals_INP_value`) AS inp_value,
        toFloat(events.properties.`$web_vitals_LCP_value`) AS lcp_value,
        toFloat(events.properties.`$web_vitals_CLS_value`) AS cls_value,
        toFloat(events.properties.`$web_vitals_FCP_value`) AS fcp_value
    FROM events
    WHERE and(
        equals(events.event, '$web_vitals'),
        isNotNull({breakdown_by}),
        events.timestamp >= {time_window_min},
        events.timestamp < {time_window_max},
        {user_filter},
        {test_account_filter}
    )
)
GROUP BY time_window_start, path
"""


def _breakdown_expr(runner: "WebVitalsPathBreakdownQueryRunner") -> ast.Expr:
    """The path expression — `_apply_path_cleaning` returns either the raw
    `events.properties.$pathname` field or the cleaned variant when
    `query.doPathCleaning` is True. The substituted AST is what
    `ensure_precomputed` hashes into the cache key, so the cleaning-on and
    cleaning-off variants each get a distinct precomputed job."""
    return runner._apply_path_cleaning(ast.Field(chain=["events", "properties", "$pathname"]))


def ensure_web_vitals_paths_precomputed(
    runner: "WebVitalsPathBreakdownQueryRunner",
    time_range_start: datetime,
    time_range_end: datetime,
) -> LazyComputationResult:
    placeholders: dict[str, ast.Expr] = {
        "breakdown_by": _breakdown_expr(runner),
        "user_filter": user_filter_expr(runner),
        "test_account_filter": test_account_filter_expr(runner),
        # Team timezone goes into the cache key — a team that changes its
        # timezone naturally invalidates existing jobs.
        "team_tz": ast.Constant(value=runner.team.timezone),
    }

    return ensure_precomputed(
        team=runner.team,
        insert_query=INSERT_QUERY_TEMPLATE,
        time_range_start=time_range_start,
        time_range_end=time_range_end,
        ttl_seconds=LAZY_TTL_SECONDS,
        table=LazyComputationTable.WEB_VITALS_PATHS_PREAGGREGATED,
        placeholders=placeholders,
        query_type="web_vitals_paths_lazy_insert",
    )


# HogQL read template — substituted via `parse_select(..., placeholders=...)` so
# arguments flow through the printer with proper escaping. The
# `arrayElement(quantilesMergeIf(...), pct_index)` picks one percentile out
# of the three stored in the reservoir. `HAVING value >= 0` mirrors the raw
# query: an all-NULL or empty reservoir comes back as NULL/<0 here, and the
# raw path drops those rows the same way.
#
# `LIMIT 20 BY band` matches the raw query: at most 20 rows per band sorted by
# ascending value. The runner-side response builder then re-partitions the rows
# into the `good`/`needs_improvements`/`poor` arrays.
#
# The metric-specific state column is substituted as a `Field` placeholder, so
# only one of `inp_quantiles_state` / `lcp_quantiles_state` / ... is read.
_READ_SQL_TEMPLATE = """
SELECT
    multiIf(
        value <= {good_threshold}, 'good',
        value <= {needs_improvements_threshold}, 'needs_improvements',
        'poor'
    ) AS band,
    path,
    value
FROM (
    SELECT
        path,
        arrayElement(
            quantilesMergeIf(0.75, 0.90, 0.99)(
                {state_column},
                and(time_window_start >= {cur_start}, time_window_start < {cur_end})
            ),
            {pct_index}
        ) AS value
    FROM posthog.web_vitals_paths_preaggregated
    WHERE and(team_id = {team_id}, job_id IN {job_ids})
    GROUP BY path
    HAVING value >= 0
)
ORDER BY value ASC, path ASC
LIMIT 20 BY band
"""


def execute_read_query(
    *,
    runner: "WebVitalsPathBreakdownQueryRunner",
    job_ids: list[str],
    current_start_utc: datetime,
    current_end_utc: datetime,
) -> list[tuple[str, str, float]]:
    """Read the precomputed rows via HogQL. Returns the raw `(band, path, value)`
    triples in the same shape the raw runner's `_calculate` consumes.

    `convertToProjectTimezone=False` is forced so the printer does not wrap
    `time_window_start` (stored UTC) in `toTimeZone(..., team_tz)` and break the
    direct comparison against our UTC `cur_start` / `cur_end` constants.
    """
    pct_index = _PCT_INDEX[runner.query.percentile]
    good_threshold = float(runner.query.thresholds[0])
    needs_improvements_threshold = float(runner.query.thresholds[1])
    state_column = _METRIC_STATE_COLUMN[runner.query.metric]

    placeholders: dict[str, ast.Expr] = {
        "team_id": ast.Constant(value=runner.team.pk),
        "job_ids": ast.Constant(value=[str(jid) for jid in job_ids]),
        "state_column": ast.Field(chain=[state_column]),
        "cur_start": ast.Constant(value=current_start_utc),
        "cur_end": ast.Constant(value=current_end_utc),
        "pct_index": ast.Constant(value=pct_index),
        "good_threshold": ast.Constant(value=good_threshold),
        "needs_improvements_threshold": ast.Constant(value=needs_improvements_threshold),
    }

    parsed = parse_select(_READ_SQL_TEMPLATE, placeholders=placeholders)

    modifiers = runner.modifiers.model_copy() if runner.modifiers else HogQLQueryModifiers()
    modifiers.convertToProjectTimezone = False

    tag_queries(product=Product.WEB_ANALYTICS, feature=Feature.QUERY, query_type="web_vitals_paths_lazy_query")
    response = execute_hogql_query(
        query_type="web_vitals_paths_lazy_query",
        query=parsed,
        team=runner.team,
        timings=runner.timings,
        modifiers=modifiers,
        limit_context=runner.limit_context,
    )
    assert response.results is not None
    return [(row[0], row[1], row[2]) for row in response.results]


def _build_response(
    runner: "WebVitalsPathBreakdownQueryRunner",
    rows: list[tuple[str, str, float]],
) -> WebVitalsPathBreakdownQueryResponse:
    def _band_rows(band: WebVitalsMetricBand) -> list[WebVitalsPathBreakdownResultItem]:
        return [WebVitalsPathBreakdownResultItem(path=row[1], value=row[2]) for row in rows if row[0] == band.value]

    return WebVitalsPathBreakdownQueryResponse(
        results=[
            WebVitalsPathBreakdownResult(
                good=_band_rows(WebVitalsMetricBand.GOOD),
                needs_improvements=_band_rows(WebVitalsMetricBand.NEEDS_IMPROVEMENTS),
                poor=_band_rows(WebVitalsMetricBand.POOR),
            )
        ],
        timings=runner.timings.to_list() if runner.timings else None,
        modifiers=runner.modifiers,
        usedLazyPrecompute=True,
    )


def execute_lazy_precomputed_read(
    runner: "WebVitalsPathBreakdownQueryRunner",
) -> Optional[WebVitalsPathBreakdownQueryResponse]:
    """Orchestrate the lazy precompute + read. Returns the response, or None on
    any failure (caller falls through to the raw path)."""
    # Tag the whole lazy path (INSERT + read) with product/feature so the INSERT
    # `sync_execute` inside `ensure_web_vitals_paths_precomputed` doesn't trip
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
        # daily-window jobs fully cover the team-tz request.
        time_range_start = floor_utc_day(current_start_utc)
        time_range_end = ceil_utc_day(current_end_utc)

        if time_range_start >= time_range_end:
            WEB_ANALYTICS_LAZY_PRECOMPUTE_FALLBACK.labels(family=_FAMILY, reason="empty_range").inc()
            logger.info(
                "web_vitals_paths_lazy_precompute_empty_range",
                team_id=team_id,
                time_range_start=time_range_start.isoformat(),
                time_range_end=time_range_end.isoformat(),
            )
            return None

        logger.info(
            "web_vitals_paths_lazy_precompute_started",
            team_id=team_id,
            metric=runner.query.metric.value,
            percentile=runner.query.percentile.value,
            time_range_start=time_range_start.isoformat(),
            time_range_end=time_range_end.isoformat(),
            time_range_days=(time_range_end - time_range_start).days,
        )

        result = ensure_web_vitals_paths_precomputed(
            runner=runner,
            time_range_start=time_range_start,
            time_range_end=time_range_end,
        )

        if not result.job_ids:
            WEB_ANALYTICS_LAZY_PRECOMPUTE_FALLBACK.labels(family=_FAMILY, reason="no_job_ids").inc()
            logger.info(
                "web_vitals_paths_lazy_precompute_no_job_ids",
                team_id=team_id,
                metric=runner.query.metric.value,
            )
            return None

        if not result.ready:
            WEB_ANALYTICS_LAZY_PRECOMPUTE_FALLBACK.labels(family=_FAMILY, reason="current_not_ready").inc()
            logger.info(
                "web_vitals_paths_lazy_precompute_current_not_ready",
                team_id=team_id,
                job_count=len(result.job_ids),
            )
            return None

        job_ids: list[str] = [str(jid) for jid in result.job_ids]

        rows = execute_read_query(
            runner=runner,
            job_ids=job_ids,
            current_start_utc=current_start_utc,
            current_end_utc=current_end_utc,
        )

        response = _build_response(runner, rows)
        WEB_ANALYTICS_LAZY_PRECOMPUTE_SUCCESS.labels(family=_FAMILY).inc()
        logger.info(
            "web_vitals_paths_lazy_precompute_completed",
            team_id=team_id,
            metric=runner.query.metric.value,
            percentile=runner.query.percentile.value,
            job_count=len(result.job_ids),
            rows_returned=len(rows),
            total_duration_ms=int((time.perf_counter() - overall_started) * 1000),
        )
        return response
    except Exception as exc:
        WEB_VITALS_LAZY_FAILED.labels(error_type=type(exc).__name__).inc()
        logger.exception(
            "web_vitals_paths_lazy_precompute_failed",
            team_id=team_id,
            error_type=type(exc).__name__,
            total_duration_ms=int((time.perf_counter() - overall_started) * 1000),
        )
        return None
