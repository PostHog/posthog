"""Ingestion rollup for the metrics overview page.

Reads `metric_series` only — one row per (metric, label-set) with a
materialized `last_seen`, sorted by `(team_id, metric_name,
series_fingerprint)` — so the landing page never scans the raw datapoint
table. Two queries: an unwindowed pass for freshness plus window-scoped
inventory counts, and a windowed GROUP BY service.

No FINAL, same argument as `MetricNamesQueryRunner`: ReplacingMergeTree
duplicates share the fingerprint, `max(last_seen)` picks the row FINAL would
keep, and `uniqExact(series_fingerprint)` counts duplicates once. The
freshness pass filters inside the aggregates rather than in WHERE because
`last_seen` must be the max over ALL retained series: when ingestion stops,
the window counts go to zero but the status strip still needs to say how
long ago the last datapoint arrived.
"""

import datetime as dt

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.database.schema.metrics import HOGQL_MAX_BYTES_TO_READ_FOR_METRICS_USER_QUERIES
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.dataclasses import frozen
from posthog.models import Team

from products.metrics.backend.facade.contracts import MetricsOverview, MetricsServiceOverview

# The overview tolerates partial results, so reads break at the budget instead
# of erroring the way the chart queries do. Mirrors MetricNamesQueryRunner.
_QUERY_SETTINGS = HogQLGlobalSettings(
    max_bytes_to_read=HOGQL_MAX_BYTES_TO_READ_FOR_METRICS_USER_QUERIES,
    read_overflow_mode="break",
)

# More services than this stops being an overview; the largest win.
MAX_SERVICES = 500

DEFAULT_LOOKBACK = dt.timedelta(days=1)


@frozen
class _OverviewTotals:
    """Project-wide freshness and inventory counts, before the per-service split.

    `metric_names` and `series` are both counts of the window, so they are named
    rather than positional — swapping them would misreport the project silently.
    """

    last_seen: str | None
    metric_names: int
    series: int


class MetricsOverviewQueryRunner:
    def __init__(self, team: Team, *, lookback: dt.timedelta = DEFAULT_LOOKBACK) -> None:
        if lookback <= dt.timedelta(0):
            raise ValueError("lookback must be positive")

        self.team = team
        self.lookback = lookback

    def _lookback_interval(self) -> ast.Call:
        return ast.Call(name="toIntervalSecond", args=[ast.Constant(value=int(self.lookback.total_seconds()))])

    def _run_totals(self) -> _OverviewTotals:
        # `last_seen_at`, not `last_seen`: HogQL registers select aliases before
        # resolving the aggregate filters and would shadow the table column.
        query = parse_select(
            """
                SELECT
                    max(toNullable(last_seen)) AS last_seen_at,
                    uniqExactIf(metric_name, last_seen > now() - {lookback}) AS metric_names,
                    uniqExactIf(series_fingerprint, last_seen > now() - {lookback}) AS active_series
                FROM posthog.metric_series
            """,
            placeholders={"lookback": self._lookback_interval()},
        )
        assert isinstance(query, ast.SelectQuery)

        response = execute_hogql_query(
            query_type="MetricsOverviewTotalsQuery",
            query=query,
            team=self.team,
            workload=Workload.LOGS,  # metrics share the logs ClickHouse workload pool for now
            settings=_QUERY_SETTINGS,
        )
        if not response.results:
            return _OverviewTotals(last_seen=None, metric_names=0, series=0)
        last_seen, metric_names, series = response.results[0]
        return _OverviewTotals(
            last_seen=last_seen.isoformat() if last_seen is not None else None,
            metric_names=int(metric_names),
            series=int(series),
        )

    def _run_services(self) -> tuple[MetricsServiceOverview, ...]:
        query = parse_select(
            """
                SELECT
                    service_name,
                    uniqExact(metric_name) AS metric_names,
                    uniqExact(series_fingerprint) AS series,
                    max(last_seen) AS last_seen_at
                FROM posthog.metric_series
                WHERE last_seen > now() - {lookback}
                GROUP BY service_name
                ORDER BY series DESC, service_name ASC
                LIMIT {limit}
            """,
            placeholders={"lookback": self._lookback_interval(), "limit": ast.Constant(value=MAX_SERVICES)},
        )
        assert isinstance(query, ast.SelectQuery)

        response = execute_hogql_query(
            query_type="MetricsOverviewServicesQuery",
            query=query,
            team=self.team,
            workload=Workload.LOGS,  # metrics share the logs ClickHouse workload pool for now
            settings=_QUERY_SETTINGS,
        )
        return tuple(
            MetricsServiceOverview(
                service_name=row[0],
                metric_names=int(row[1]),
                series=int(row[2]),
                last_seen=row[3].isoformat(),
            )
            for row in response.results
        )

    def run(self) -> MetricsOverview:
        totals = self._run_totals()
        return MetricsOverview(
            last_seen=totals.last_seen,
            metric_names=totals.metric_names,
            series=totals.series,
            lookback_seconds=int(self.lookback.total_seconds()),
            services=self._run_services() if totals.last_seen is not None else (),
        )
