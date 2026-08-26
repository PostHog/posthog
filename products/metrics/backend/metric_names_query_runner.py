"""Distinct metric names for a team's picker UI.

Queries `posthog.metric_series` (one row per unique metric + label-set) rather
than the raw `posthog.metrics` datapoint table. The picker only needs the set
of names, and `metric_series` holds one row per series instead of one per data
point, so the scan is proportional to series count rather than emission volume.
`metric_name` is the second column of the series table's ORDER BY and
`last_seen` records recency directly, so both the grouping and the ordering
follow the table's own layout.

Surfaces `metric_type` alongside the name so the viewer can hint at the
type-appropriate default aggregation (gauge -> avg, counter/sum -> sum, etc.)
without a second round-trip.
"""

import datetime as dt
from typing import Any

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.models import Team


class MetricNamesQueryRunner:
    def __init__(
        self,
        team: Team,
        *,
        search: str = "",
        limit: int = 100,
        lookback: dt.timedelta = dt.timedelta(days=7),
    ) -> None:
        if limit <= 0 or limit > 1000:
            raise ValueError("limit must be in [1, 1000]")
        if lookback <= dt.timedelta(0):
            raise ValueError("lookback must be positive")

        self.team = team
        self.search = search.strip()
        self.limit = limit
        self.lookback = lookback

    def run(self) -> list[dict[str, Any]]:
        # any() on metric_type collapses to the single canonical type per name
        # (a metric name shouldn't change type — if it does, we get whichever
        # answer ClickHouse picks, which is fine for a picker).
        query = parse_select(
            """
                SELECT
                    metric_name AS name,
                    any(metric_type) AS metric_type
                FROM posthog.metric_series
                WHERE last_seen > now() - {lookback}
                  AND metric_name ILIKE {search_pattern}
                GROUP BY metric_name
                ORDER BY
                    lower(metric_name) = lower({exact}) DESC,
                    max(last_seen) DESC
                LIMIT {limit}
            """,
            placeholders={
                "lookback": ast.Call(
                    name="toIntervalSecond", args=[ast.Constant(value=int(self.lookback.total_seconds()))]
                ),
                "search_pattern": ast.Constant(value=f"%{self.search}%"),
                "exact": ast.Constant(value=self.search),
                "limit": ast.Constant(value=self.limit),
            },
        )
        assert isinstance(query, ast.SelectQuery)

        response = execute_hogql_query(
            query_type="MetricNamesQuery",
            query=query,
            team=self.team,
            workload=Workload.LOGS,  # metrics share the logs ClickHouse workload pool for now
        )

        return [{"name": row[0], "metric_type": row[1]} for row in response.results]
