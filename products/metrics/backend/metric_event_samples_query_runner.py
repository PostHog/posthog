"""Raw metric emissions for a metric, from the metric_samples/metric_series split.

Unlike `MetricQueryRunner` (which aggregates `metrics1` into a time series), this
returns individual emissions — value, attributes, and the trace linkage — newest
first. It backs the Samples view and the metric->trace pivot.

Joins `posthog.metric_samples` (the tiny hot rows) to `posthog.metric_series`
(the deduped label set) on `series_fingerprint`. Samples are filtered + limited
first, then enriched with their series' labels; the series side is grouped so a
ReplacingMergeTree duplicate never multiplies a sample. metric_name comes from
the sample row itself, so an emission whose series row hasn't landed yet still
renders with its name (series-side fields fall back to empty).
"""

import datetime as dt
from typing import Any

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.models import Team


class MetricEventSamplesQueryRunner:
    def __init__(
        self,
        team: Team,
        *,
        metric_name: str,
        date_from: dt.datetime,
        date_to: dt.datetime,
        trace_id: str | None = None,
        limit: int = 100,
    ) -> None:
        if not metric_name:
            raise ValueError("metric_name is required")
        if date_to <= date_from:
            raise ValueError("date_to must be after date_from")
        if limit <= 0 or limit > 1000:
            raise ValueError("limit must be in [1, 1000]")

        self.team = team
        self.metric_name = metric_name
        self.date_from = date_from
        self.date_to = date_to
        self.trace_id = (trace_id or "").strip()
        self.limit = limit

    def run(self) -> list[dict[str, Any]]:
        # The trace filter is an always-present predicate that is a no-op when no
        # trace is given, so the optional clause never has to be spliced into the
        # query string (which would collide with the HogQL placeholder braces) —
        # an empty {trace_id} matches every row. Samples are filtered + limited in
        # the inner query, then left-joined to the deduped series for labels.
        query = parse_select(
            """
                SELECT
                    s.timestamp,
                    s.metric_name,
                    ser.metric_type,
                    s.value,
                    s.count,
                    ser.unit,
                    ser.aggregation_temporality,
                    ser.is_monotonic,
                    ser.service_name,
                    s.trace_id,
                    s.span_id,
                    ser.attributes,
                    ser.resource_attributes
                FROM (
                    SELECT team_id, metric_name, series_fingerprint, timestamp, value, count, trace_id, span_id
                    FROM posthog.metric_samples
                    WHERE metric_name = {metric_name}
                      AND timestamp >= {date_from}
                      AND timestamp < {date_to}
                      AND ({trace_id} = '' OR trace_id = {trace_id})
                    ORDER BY timestamp DESC
                    LIMIT {limit}
                ) AS s
                LEFT JOIN (
                    SELECT
                        team_id,
                        metric_name,
                        series_fingerprint,
                        any(metric_type) AS metric_type,
                        any(unit) AS unit,
                        any(aggregation_temporality) AS aggregation_temporality,
                        any(is_monotonic) AS is_monotonic,
                        any(service_name) AS service_name,
                        any(attributes) AS attributes,
                        any(resource_attributes) AS resource_attributes
                    FROM posthog.metric_series
                    WHERE metric_name = {metric_name}
                    GROUP BY team_id, metric_name, series_fingerprint
                ) AS ser
                    ON s.team_id = ser.team_id
                    AND s.metric_name = ser.metric_name
                    AND s.series_fingerprint = ser.series_fingerprint
                ORDER BY s.timestamp DESC
            """,
            placeholders={
                "metric_name": ast.Constant(value=self.metric_name),
                "date_from": ast.Constant(value=self.date_from),
                "date_to": ast.Constant(value=self.date_to),
                "trace_id": ast.Constant(value=self.trace_id),
                "limit": ast.Constant(value=self.limit),
            },
        )
        assert isinstance(query, ast.SelectQuery)

        response = execute_hogql_query(
            query_type="MetricEventSamplesQuery",
            query=query,
            team=self.team,
            workload=Workload.LOGS,  # metrics share the logs ClickHouse workload pool for now
        )

        return [
            {
                "timestamp": row[0].isoformat() if hasattr(row[0], "isoformat") else str(row[0]),
                "metric_name": row[1],
                "metric_type": row[2],
                "value": row[3],
                "count": int(row[4]),
                "unit": row[5],
                "aggregation_temporality": row[6],
                "is_monotonic": bool(row[7]),
                "service_name": row[8],
                "trace_id": row[9],
                "span_id": row[10],
                "attributes": dict(row[11]) if row[11] else {},
                "resource_attributes": dict(row[12]) if row[12] else {},
            }
            for row in response.results
        ]
