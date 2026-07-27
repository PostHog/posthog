"""Distinct metric names for a team's picker UI.

Queries `posthog.metrics` directly rather than `metric_attributes`: `metric_name`
is a top-level column on the source table with a `set(100)` skip index
(`idx_metric_name_set`) purpose-built for this lookup. Materialising it into
the attributes table would require a new MV with negligible upside given the
cardinality (10s — low 100s of distinct names per team).

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
        # ILIKE on metric_name uses the bloom filter side of the skip index;
        # any() on metric_type collapses to the single canonical type per
        # name (a metric name shouldn't change type — if it does, we get the
        # most-recent answer ClickHouse picks, which is fine for a picker).
        query = parse_select(
            """
                SELECT
                    metric_name AS name,
                    any(metric_type) AS metric_type,
                    max(timestamp) AS last_seen
                FROM posthog.metrics
                WHERE timestamp > now() - {lookback}
                  AND metric_name ILIKE {search_pattern}
                GROUP BY metric_name
                ORDER BY
                    lower(metric_name) = lower({exact}) DESC,
                    last_seen DESC
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
