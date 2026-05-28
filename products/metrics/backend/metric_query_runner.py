"""Single-metric time-series query runner.

Returns a list of `(time_bucket, value)` points for one metric over a date
range, with a choice of aggregation. Modelled after the logs
`SparklineQueryRunner` shape but flattened — we don't yet need the full
`AnalyticsQueryRunner[LogsQueryResponse]` infrastructure since this product
isn't going through HogQL `DataNode` caching, schema-gen or the data-viz
pipeline yet.
"""

import datetime as dt
from typing import Any

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.models import Team

# Allowed aggregation -> HogQL expression. Restricted set for v1 — extendable
# as the viewer UI gains more controls.
_AGGREGATIONS: dict[str, str] = {
    "sum": "sum(value)",
    "avg": "avg(value)",
    "count": "count()",
    "p95": "quantile(0.95)(value)",
}

# Target ~60 buckets across the requested range — feels right for a chart.
_TARGET_BUCKET_COUNT = 60

# Order from finest to coarsest. Picked so the first one that yields
# <= _TARGET_BUCKET_COUNT buckets wins.
_INTERVAL_LADDER: list[tuple[str, dt.timedelta]] = [
    ("second", dt.timedelta(seconds=1)),
    ("minute", dt.timedelta(minutes=1)),
    ("minute_5", dt.timedelta(minutes=5)),
    ("minute_15", dt.timedelta(minutes=15)),
    ("hour", dt.timedelta(hours=1)),
    ("hour_6", dt.timedelta(hours=6)),
    ("day", dt.timedelta(days=1)),
    ("week", dt.timedelta(weeks=1)),
]

_INTERVAL_TO_CH_EXPR: dict[str, str] = {
    "second": "toIntervalSecond(1)",
    "minute": "toIntervalMinute(1)",
    "minute_5": "toIntervalMinute(5)",
    "minute_15": "toIntervalMinute(15)",
    "hour": "toIntervalHour(1)",
    "hour_6": "toIntervalHour(6)",
    "day": "toIntervalDay(1)",
    "week": "toIntervalWeek(1)",
}


def _pick_interval(date_from: dt.datetime, date_to: dt.datetime) -> str:
    """Pick the finest interval that keeps bucket count at or below the target."""
    span = date_to - date_from
    for name, step in _INTERVAL_LADDER:
        if span / step <= _TARGET_BUCKET_COUNT:
            return name
    return _INTERVAL_LADDER[-1][0]


class MetricQueryRunner:
    def __init__(
        self,
        team: Team,
        metric_name: str,
        aggregation: str,
        date_from: dt.datetime,
        date_to: dt.datetime,
    ) -> None:
        if aggregation not in _AGGREGATIONS:
            raise ValueError(f"Unsupported aggregation: {aggregation!r}")
        if date_to <= date_from:
            raise ValueError("date_to must be after date_from")

        self.team = team
        self.metric_name = metric_name
        self.aggregation = aggregation
        self.date_from = date_from
        self.date_to = date_to
        self.interval = _pick_interval(date_from, date_to)

    def run(self) -> list[dict[str, Any]]:
        # `metrics` is only registered under the `posthog.` HogQL namespace
        # (see posthog/hogql/database/database.py).
        query = parse_select(
            f"""
                SELECT
                    toStartOfInterval(timestamp, {_INTERVAL_TO_CH_EXPR[self.interval]}) AS time,
                    {_AGGREGATIONS[self.aggregation]} AS value
                FROM posthog.metrics
                WHERE metric_name = {{metric_name}}
                  AND timestamp >= {{date_from}}
                  AND timestamp < {{date_to}}
                GROUP BY time
                ORDER BY time ASC
                LIMIT 10000
            """,
            placeholders={
                "metric_name": ast.Constant(value=self.metric_name),
                "date_from": ast.Constant(value=self.date_from),
                "date_to": ast.Constant(value=self.date_to),
            },
        )
        assert isinstance(query, ast.SelectQuery)

        response = execute_hogql_query(
            query_type="MetricQuery",
            query=query,
            team=self.team,
            workload=Workload.LOGS,  # metrics share the logs ClickHouse workload pool for now
        )

        return [
            {"time": row[0].isoformat() if isinstance(row[0], dt.datetime) else row[0], "value": row[1]}
            for row in response.results
        ]
