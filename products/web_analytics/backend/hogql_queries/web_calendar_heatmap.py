import time
from datetime import UTC, datetime
from typing import Optional

import structlog
from prometheus_client import Counter

from posthog.schema import (
    EventsHeatMapColumnAggregationResult,
    EventsHeatMapDataResult,
    EventsHeatMapRowAggregationResult,
    EventsHeatMapStructuredResult,
    EventsNode,
    TrendsQuery,
    TrendsQueryResponse,
)

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.preaggregation.web_overview_preaggregated_sql import (
    DISTRIBUTED_WEB_OVERVIEW_PREAGGREGATED_TABLE,
)
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.hogql_queries.insights.trends.calendar_heatmap_trends_query_runner import CalendarHeatmapTrendsQueryRunner
from posthog.models import EventDefinition

from products.web_analytics.backend.hogql_queries.web_analytics_lazy_precompute import (
    WEB_ANALYTICS_LAZY_PRECOMPUTE_FALLBACK,
    WEB_ANALYTICS_LAZY_PRECOMPUTE_SUCCESS,
    can_use_lazy_precompute as _can_use_lazy_precompute_shared,
    ceil_utc_day,
    floor_utc_day,
)
from products.web_analytics.backend.hogql_queries.web_lazy_precompute_common import (
    handle_stale_served,
    is_precompute_enabled_for_team,
)
from products.web_analytics.backend.hogql_queries.web_overview import WebOverviewQueryRunner
from products.web_analytics.backend.hogql_queries.web_overview_lazy_precompute import (
    _READ_SETTINGS,
    ensure_web_overview_precomputed,
)
from products.web_analytics.backend.hogql_queries.web_trends_lazy_precompute import (
    build_inner_overview_query,
    is_trends_precompute_enabled_for_team,
)

logger = structlog.get_logger(__name__)

_FAMILY = "web_calendar_heatmap"

WEB_CALENDAR_HEATMAP_LAZY_FAILED = Counter(
    "web_calendar_heatmap_lazy_precompute_failed_total",
    "Web calendar heatmap lazy precompute path failures, by error class",
    ["error_type"],
)

# grouping() markers disambiguate the aggregation levels: hour 0 / dow 1 are
# real values, so the cell rows can't be told apart from the rollup rows by
# their defaults alone.
_HEATMAP_READ_SQL_TEMPLATE = """
SELECT
    grouping(dow) AS g_dow,
    grouping(hour) AS g_hour,
    toDayOfWeek(toTimeZone(time_window_start, %(tz)s)) AS dow,
    toHour(toTimeZone(time_window_start, %(tz)s)) AS hour,
    uniqMerge(uniq_users_state) AS value
FROM {table}
WHERE team_id = %(team_id)s AND job_id IN %(job_ids)s
  AND time_window_start >= %(range_start)s AND time_window_start < %(range_end)s
GROUP BY GROUPING SETS ((dow, hour), (dow), (hour), ())
"""


def heatmap_precompute_servable(query: TrendsQuery) -> bool:
    """Only the Active Hours unique-visitors tab is servable: it buckets by
    session start (matching the buckets' attribution) and counts unique
    persons (matching `uniq_users_state`). The total-events tab buckets by raw
    event timestamp, which the session-start-keyed buckets can't reproduce."""
    if len(query.series) != 1:
        return False
    series = query.series[0]
    if not isinstance(series, EventsNode):
        return False
    if series.event not in ("$pageview", "$screen"):
        return False
    if series.math != "dau":
        return False
    if series.fixedProperties:
        return False
    if query.conversionGoal is not None:
        return False
    if query.aggregation_group_type_index is not None:
        return False
    if query.samplingFactor is not None:
        return False
    chf = getattr(query, "calendarHeatmapFilter", None)
    if chf is None or not chf.bucketBySessionStart:
        return False
    if query.properties is not None and not isinstance(query.properties, list):
        return False
    return True


def _hour_aligned_bounds(start_utc: datetime, end_utc: datetime) -> bool:
    """The read filters whole hourly buckets, so a bound inside an hour would
    silently include or drop up to an hour of sessions vs the live path's exact
    timestamp filter. The end bound may also be an inclusive hour-end
    (…:59:59.xxxxxx), which covers its final bucket exactly."""
    if start_utc.minute or start_utc.second or start_utc.microsecond:
        return False
    if end_utc.minute == 59 and end_utc.second == 59:
        return True
    return end_utc.minute == 0 and end_utc.second == 0 and end_utc.microsecond == 0


def _assemble_structured_result(rows: list[tuple[int, int, int, int, int]]) -> EventsHeatMapStructuredResult:
    data: list[EventsHeatMapDataResult] = []
    row_aggs: list[EventsHeatMapRowAggregationResult] = []
    col_aggs: list[EventsHeatMapColumnAggregationResult] = []
    total = 0
    for g_dow, g_hour, dow, hour, value in rows:
        value = int(value)
        if g_dow == 0 and g_hour == 0:
            data.append(EventsHeatMapDataResult(row=int(dow), column=int(hour), value=value))
        elif g_dow == 0 and g_hour == 1:
            row_aggs.append(EventsHeatMapRowAggregationResult(row=int(dow), value=value))
        elif g_dow == 1 and g_hour == 0:
            col_aggs.append(EventsHeatMapColumnAggregationResult(column=int(hour), value=value))
        else:
            total = value
    return EventsHeatMapStructuredResult(
        data=data, rowAggregations=row_aggs, columnAggregations=col_aggs, allAggregations=total
    )


def execute_lazy_precomputed_heatmap(
    runner: "WebCalendarHeatmapTrendsQueryRunner",
) -> Optional[EventsHeatMapStructuredResult]:
    """Serve the Active Hours heatmap from the shared web_overview preagg
    buckets. Returns None on any ineligibility/miss (caller falls back)."""
    tag_queries(product=Product.WEB_ANALYTICS, feature=Feature.QUERY)
    team = runner.team
    overall_started = time.perf_counter()
    try:
        if not heatmap_precompute_servable(runner.query):
            return None
        if not is_trends_precompute_enabled_for_team(team):
            return None

        # The buckets store person-id uniq states, which cannot represent
        # distinct-id aggregation, so keep these teams on the live path.
        if team.aggregate_users_by_distinct_id:
            WEB_ANALYTICS_LAZY_PRECOMPUTE_FALLBACK.labels(family=_FAMILY, reason="distinct_id_aggregation").inc()
            return None

        series = runner.query.series[0]
        assert isinstance(series, EventsNode)  # guaranteed by heatmap_precompute_servable
        props = list(runner.query.properties or [])
        if series.properties:
            props.extend(series.properties)

        # The buckets aggregate $pageview and $screen into one uniq state with
        # no event dimension, while the live path filters exactly to
        # series.event. Serving is only faithful when the team tracks just the
        # requested event, so fall back if the other one has ever been seen.
        other_event = "$screen" if series.event == "$pageview" else "$pageview"
        if EventDefinition.objects.filter(team=team, name=other_event).exists():
            WEB_ANALYTICS_LAZY_PRECOMPUTE_FALLBACK.labels(family=_FAMILY, reason="mixed_event_types").inc()
            return None

        inner_query = build_inner_overview_query(runner.query, props)
        inner_runner = WebOverviewQueryRunner(query=inner_query, team=team, modifiers=runner.modifiers)

        if not _can_use_lazy_precompute_shared(inner_runner, log_prefix=_FAMILY):
            return None

        date_from = runner.query_date_range.date_from()
        date_to = runner.query_date_range.date_to()
        assert date_from is not None and date_to is not None
        start_utc = date_from.astimezone(UTC)
        end_utc = date_to.astimezone(UTC)

        # Covers explicit sub-hour date bounds and timezones with fractional
        # UTC offsets, both of which put a bound inside a bucket.
        if not _hour_aligned_bounds(start_utc, end_utc):
            WEB_ANALYTICS_LAZY_PRECOMPUTE_FALLBACK.labels(family=_FAMILY, reason="sub_hour_range").inc()
            return None

        time_range_start = floor_utc_day(start_utc)
        time_range_end = ceil_utc_day(end_utc)
        if time_range_start >= time_range_end:
            WEB_ANALYTICS_LAZY_PRECOMPUTE_FALLBACK.labels(family=_FAMILY, reason="empty_range").inc()
            return None

        result = ensure_web_overview_precomputed(
            runner=inner_runner,
            time_range_start=time_range_start,
            time_range_end=time_range_end,
        )
        if result.stale:
            # Family web_overview on purpose: the shared buckets are refreshed
            # by one debounced overview re-run.
            handle_stale_served(runner=inner_runner, family="web_overview")
        if not result.job_ids:
            WEB_ANALYTICS_LAZY_PRECOMPUTE_FALLBACK.labels(family=_FAMILY, reason="no_job_ids").inc()
            return None
        if not result.ready:
            WEB_ANALYTICS_LAZY_PRECOMPUTE_FALLBACK.labels(family=_FAMILY, reason="current_not_ready").inc()
            return None

        sql = _HEATMAP_READ_SQL_TEMPLATE.format(table=DISTRIBUTED_WEB_OVERVIEW_PREAGGREGATED_TABLE())
        tag_queries(product=Product.WEB_ANALYTICS, feature=Feature.QUERY, query_type="web_calendar_heatmap_lazy_query")
        rows = sync_execute(
            sql,
            {
                "team_id": team.pk,
                "job_ids": tuple(str(jid) for jid in result.job_ids),
                "tz": team.timezone,
                "range_start": start_utc,
                "range_end": end_utc,
            },
            settings=_READ_SETTINGS,
            team_id=team.pk,
        )

        structured = _assemble_structured_result(rows)
        WEB_ANALYTICS_LAZY_PRECOMPUTE_SUCCESS.labels(family=_FAMILY).inc()
        logger.info(
            "web_calendar_heatmap_lazy_precompute_completed",
            team_id=team.pk,
            job_count=len(result.job_ids),
            cells=len(structured.data),
            total_duration_ms=int((time.perf_counter() - overall_started) * 1000),
        )
        return structured
    except Exception as exc:
        WEB_CALENDAR_HEATMAP_LAZY_FAILED.labels(error_type=type(exc).__name__).inc()
        logger.exception(
            "web_calendar_heatmap_lazy_precompute_failed",
            team_id=team.pk,
            error_type=type(exc).__name__,
            total_duration_ms=int((time.perf_counter() - overall_started) * 1000),
        )
        return None


class WebCalendarHeatmapTrendsQueryRunner(CalendarHeatmapTrendsQueryRunner):
    """Active Hours runner for web-analytics-tagged calendar heatmap queries.
    Serves the unique-visitors tab from the shared web_overview precompute
    buckets and falls back to the live calendar heatmap path otherwise."""

    def get_cache_payload(self) -> dict:
        payload = super().get_cache_payload()
        # Rollout state in the cache key = immediate kill switch: disabling a
        # flag must not keep serving cached precompute-derived results until
        # they stale out (same mechanism as WebTrendsQueryRunner).
        payload["web_trends_precompute"] = is_trends_precompute_enabled_for_team(
            self.team
        ) and is_precompute_enabled_for_team(self.team)
        return payload

    def _calculate(self) -> TrendsQueryResponse:
        structured = execute_lazy_precomputed_heatmap(self)
        if structured is None:
            return super()._calculate()
        return self._wrap_calendar_results(structured, timings=self.timings.to_list(), hogql=None)
