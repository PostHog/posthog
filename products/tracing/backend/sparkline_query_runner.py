from zoneinfo import ZoneInfo

from posthog.schema import (
    CachedTraceSpansQueryResponse,
    TraceSpansQuery,
    TraceSpansQueryResponse,
    TraceSpansSparklineBreakdownBy,
)

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner

from products.tracing.backend.constants import TRACE_SPANS_HEATMAP_SETTINGS, TRACE_SPANS_SPARKLINE_SETTINGS
from products.tracing.backend.logic import TraceSpansQueryRunnerMixin


class TraceSpansSparklineQueryRunner(TraceSpansQueryRunnerMixin, AnalyticsQueryRunner[TraceSpansQueryResponse]):
    """Aggregates trace spans over time for the tracing chart (volume or latency heatmap)."""

    query: TraceSpansQuery
    cached_response: CachedTraceSpansQueryResponse

    @property
    def _breakdown(self) -> TraceSpansSparklineBreakdownBy:
        return self.query.sparklineBreakdownBy or TraceSpansSparklineBreakdownBy.SERVICE

    @property
    def _is_heatmap(self) -> bool:
        return self._breakdown in (
            TraceSpansSparklineBreakdownBy.LATENCY_LOG2,
            TraceSpansSparklineBreakdownBy.SERVICE_AND_LATENCY_LOG2,
        )

    @property
    def settings(self) -> HogQLGlobalSettings:  # type: ignore[override]
        return TRACE_SPANS_HEATMAP_SETTINGS if self._is_heatmap else TRACE_SPANS_SPARKLINE_SETTINGS

    def _calculate(self) -> TraceSpansQueryResponse:
        response = execute_hogql_query(
            query_type="TraceSpansSparklineQuery",
            query=self.to_query(),
            modifiers=self.modifiers,
            team=self.team,
            workload=Workload.LOGS,
            timings=self.timings,
            limit_context=self.limit_context,
            settings=self.settings,
        )

        results: list[dict] = []
        include_q = bool(self.query.heatmapIncludeQuantiles) and self._is_heatmap

        for row in response.results:
            time_iso = row[0].replace(tzinfo=ZoneInfo("UTC")).isoformat()
            if self._breakdown == TraceSpansSparklineBreakdownBy.SERVICE:
                service = row[1] if row[1] not in (None, "") else "(no value)"
                results.append({"time": time_iso, "service": service, "count": row[2]})
            else:
                duration_log2_bucket = int(row[1]) if row[1] is not None else None
                service = row[2] if len(row) > 2 and row[2] not in (None, "") else ""
                count = row[3] if len(row) > 3 else row[2]
                item: dict = {
                    "time": time_iso,
                    "duration_log2_bucket": duration_log2_bucket,
                    "service": service,
                    "count": count,
                }
                if include_q and len(row) > 4 and row[4] is not None:
                    qvals = row[4]
                    if isinstance(qvals, (list, tuple)) and len(qvals) >= 3:
                        item["p50_nano"] = int(qvals[0])
                        item["p95_nano"] = int(qvals[1])
                        item["p99_nano"] = int(qvals[2])
                results.append(item)

        return TraceSpansQueryResponse(results=results)

    def to_query(self) -> ast.SelectQuery:
        if self._breakdown == TraceSpansSparklineBreakdownBy.SERVICE:
            return self._service_volume_query()
        return self._latency_heatmap_query()

    def _service_volume_query(self) -> ast.SelectQuery:
        query = parse_select(
            """
                SELECT
                    am.time_bucket AS time,
                    {breakdown_field},
                    ifNull(ac.event_count, 0) AS count
                FROM (
                    SELECT
                        dateAdd({date_from_start_of_interval}, {number_interval_period}) AS time_bucket
                    FROM numbers(
                        floor(
                            dateDiff({interval},
                                        {date_from_start_of_interval},
                                        {date_to_start_of_interval}) / {interval_count} + 1
                                    )
                        )
                    WHERE
                        time_bucket >= {date_from_start_of_interval} and
                        time_bucket <= greatest(
                            {date_from_start_of_interval},
                            toStartOfInterval({date_to} - toIntervalSecond(1), {one_interval_period})
                        )
                ) AS am
                LEFT JOIN (
                    SELECT
                        toStartOfInterval({time_field}, {one_interval_period}) AS time,
                        {breakdown_field},
                        count() AS event_count
                    FROM posthog.trace_spans
                    WHERE {where} AND time >= {date_from_start_of_interval} AND time <= {date_to}
                    GROUP BY {breakdown_field}, time
                ) AS ac ON am.time_bucket = ac.time
                ORDER BY time asc, count desc
                LIMIT 10 BY time LIMIT 10000
        """,
            placeholders={
                **self.query_date_range.to_placeholders(),
                "time_field": ast.Call(name="toStartOfMinute", args=[ast.Field(chain=["timestamp"])])
                if self.query_date_range.interval_name != "second"
                else ast.Field(chain=["timestamp"]),
                "where": self.where(),
                "breakdown_field": ast.Field(chain=["service_name"]),
            },
        )
        assert isinstance(query, ast.SelectQuery)
        return query

    def _latency_heatmap_query(self) -> ast.SelectQuery:
        include_q = bool(self.query.heatmapIncludeQuantiles)
        by_service = self._breakdown == TraceSpansSparklineBreakdownBy.SERVICE_AND_LATENCY_LOG2

        q_agg = ", quantiles(0.5, 0.95, 0.99)(duration_nano) AS q" if include_q else ""
        q_outer = ", ac.q AS q" if include_q else ""

        if by_service:
            inner_select = f"""
                        toStartOfInterval({{time_field}}, {{one_interval_period}}) AS time,
                        floor(log2(greatest(duration_nano, 1))) AS duration_log2_bucket,
                        service_name,
                        count() AS event_count
                        {q_agg}
            """
            group_by = "time, duration_log2_bucket, service_name"
            outer_select = f"""
                    am.time_bucket AS time,
                    ac.duration_log2_bucket AS duration_log2_bucket,
                    ac.service_name AS service_name,
                    ifNull(ac.event_count, 0) AS count
                    {q_outer}
            """
        else:
            inner_select = f"""
                        toStartOfInterval({{time_field}}, {{one_interval_period}}) AS time,
                        floor(log2(greatest(duration_nano, 1))) AS duration_log2_bucket,
                        count() AS event_count
                        {q_agg}
            """
            group_by = "time, duration_log2_bucket"
            outer_select = f"""
                    am.time_bucket AS time,
                    ac.duration_log2_bucket AS duration_log2_bucket,
                    '' AS service_name,
                    ifNull(ac.event_count, 0) AS count
                    {q_outer}
            """

        sql = f"""
                SELECT
                    {outer_select.strip()}
                FROM (
                    SELECT
                        dateAdd({{date_from_start_of_interval}}, {{number_interval_period}}) AS time_bucket
                    FROM numbers(
                        floor(
                            dateDiff({{interval}},
                                        {{date_from_start_of_interval}},
                                        {{date_to_start_of_interval}}) / {{interval_count}} + 1
                                    )
                        )
                    WHERE
                        time_bucket >= {{date_from_start_of_interval}} and
                        time_bucket <= greatest(
                            {{date_from_start_of_interval}},
                            toStartOfInterval({{date_to}} - toIntervalSecond(1), {{one_interval_period}})
                        )
                ) AS am
                LEFT JOIN (
                    SELECT
                        {inner_select.strip()}
                    FROM posthog.trace_spans
                    WHERE {{where}} AND time >= {{date_from_start_of_interval}} AND time <= {{date_to}}
                    GROUP BY {group_by}
                ) AS ac ON am.time_bucket = ac.time
                ORDER BY time asc, count desc
                LIMIT 100000
        """

        query = parse_select(
            sql,
            placeholders={
                **self.query_date_range.to_placeholders(),
                "time_field": ast.Call(name="toStartOfMinute", args=[ast.Field(chain=["timestamp"])])
                if self.query_date_range.interval_name != "second"
                else ast.Field(chain=["timestamp"]),
                "where": self.where(),
            },
        )
        assert isinstance(query, ast.SelectQuery)
        return query
