"""Ingestion rollup for the metrics overview page.

Reads `metric_series` only — one row per (metric, label-set) with a
materialized `last_seen`, sorted by `(team_id, metric_name,
series_fingerprint)` — so the landing page never scans the raw datapoint
table. Two queries: an unwindowed pass for freshness plus window-scoped
inventory counts, and a windowed GROUP BY service.

No FINAL, same argument as `MetricNamesQueryRunner`: ReplacingMergeTree
duplicates share the fingerprint, `max(last_seen)` picks the row FINAL would
keep, and `uniqExact(series_fingerprint)` counts duplicates once.

Freshness and the window counts are two queries, not one. The counts filter
`last_seen` in WHERE so the `idx_last_seen_minmax` skip index on
`metric_series2` reads only the recent parts; folding them into a single
unwindowed pass (filtering inside the aggregates) would defeat the index and
scan every series row. Freshness stays unwindowed on its own — when ingestion
stops the window counts go to zero but the status strip still needs the last
datapoint's age — but it reads only the `last_seen` column, not the fingerprint.
The two run concurrently with the per-service pass.
"""

import datetime as dt
import contextvars
from concurrent.futures import ThreadPoolExecutor

from opentelemetry import trace
from opentelemetry.trace import Span

from posthog.schema import HogQLQueryResponse

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.database.schema.metrics import HOGQL_MAX_BYTES_TO_READ_FOR_METRICS_USER_QUERIES
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.models import Team
from posthog.settings import TEST

from products.metrics.backend.facade.contracts import MetricsOverview, MetricsServiceOverview

tracer = trace.get_tracer(__name__)

# The overview tolerates partial results, so reads break at the budget instead
# of erroring the way the chart queries do. Mirrors MetricNamesQueryRunner.
_QUERY_SETTINGS = HogQLGlobalSettings(
    max_bytes_to_read=HOGQL_MAX_BYTES_TO_READ_FOR_METRICS_USER_QUERIES,
    read_overflow_mode="break",
)

# More services than this stops being an overview; the largest win.
MAX_SERVICES = 500

DEFAULT_LOOKBACK = dt.timedelta(days=1)


def _set_query_timing_attributes(span: Span, response: HogQLQueryResponse) -> None:
    """Split the HogQL root timing from the ClickHouse read.

    `.` is the whole lifecycle (parse, resolve, print, execute), so a slow overview
    trace needs `./clickhouse_execute` to tell a slow read from slow query building.
    """
    timings = {timing.k: timing.t for timing in response.timings or ()}
    if (query_seconds := timings.get(".")) is not None:
        span.set_attribute("query.seconds", query_seconds)
    if (clickhouse_seconds := timings.get("./clickhouse_execute")) is not None:
        span.set_attribute("clickhouse.seconds", clickhouse_seconds)


class MetricsOverviewQueryRunner:
    def __init__(self, team: Team, *, lookback: dt.timedelta = DEFAULT_LOOKBACK) -> None:
        if lookback <= dt.timedelta(0):
            raise ValueError("lookback must be positive")

        self.team = team
        self.lookback = lookback

    def _lookback_interval(self) -> ast.Call:
        return ast.Call(name="toIntervalSecond", args=[ast.Constant(value=int(self.lookback.total_seconds()))])

    def _run_freshness(self) -> str | None:
        with tracer.start_as_current_span("metrics.overview.freshness") as span:
            span.set_attribute("team_id", self.team.pk)
            # Unwindowed on purpose: the status strip reports the last datapoint's
            # age even after ingestion stops. Reads only `last_seen`, so the whole
            # scan is one narrow column.
            query = parse_select("SELECT max(toNullable(last_seen)) AS last_seen_at FROM posthog.metric_series")
            assert isinstance(query, ast.SelectQuery)

            response = execute_hogql_query(
                query_type="MetricsOverviewFreshnessQuery",
                query=query,
                team=self.team,
                workload=Workload.LOGS,  # metrics share the logs ClickHouse workload pool for now
                settings=_QUERY_SETTINGS,
            )
            _set_query_timing_attributes(span, response)
            if not response.results or response.results[0][0] is None:
                return None
            return response.results[0][0].isoformat()

    def _run_counts(self) -> tuple[int, int]:
        with tracer.start_as_current_span("metrics.overview.counts") as span:
            span.set_attribute("team_id", self.team.pk)
            # Window in WHERE, not inside the aggregates, so `idx_last_seen_minmax`
            # prunes the old parts instead of the read touching every series row.
            query = parse_select(
                """
                    SELECT
                        uniqExact(metric_name) AS metric_names,
                        uniqExact(series_fingerprint) AS active_series
                    FROM posthog.metric_series
                    WHERE last_seen > now() - {lookback}
                """,
                placeholders={"lookback": self._lookback_interval()},
            )
            assert isinstance(query, ast.SelectQuery)

            response = execute_hogql_query(
                query_type="MetricsOverviewCountsQuery",
                query=query,
                team=self.team,
                workload=Workload.LOGS,  # metrics share the logs ClickHouse workload pool for now
                settings=_QUERY_SETTINGS,
            )
            _set_query_timing_attributes(span, response)
            if not response.results:
                return 0, 0
            metric_names, series = response.results[0]
            return int(metric_names), int(series)

    def _run_services(self) -> tuple[MetricsServiceOverview, ...]:
        with tracer.start_as_current_span("metrics.overview.services") as span:
            span.set_attribute("team_id", self.team.pk)
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
            _set_query_timing_attributes(span, response)
            span.set_attribute("services.count", len(response.results))
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
        with tracer.start_as_current_span("metrics.overview.run") as span:
            span.set_attribute("team_id", self.team.pk)
            span.set_attribute("lookback_seconds", int(self.lookback.total_seconds()))

            if TEST:
                last_seen = self._run_freshness()
                metric_names, series = self._run_counts()
                services = self._run_services()
            else:
                with ThreadPoolExecutor(max_workers=3, thread_name_prefix="metrics_overview") as executor:
                    freshness_future = executor.submit(contextvars.copy_context().run, self._run_freshness)
                    counts_future = executor.submit(contextvars.copy_context().run, self._run_counts)
                    services_future = executor.submit(contextvars.copy_context().run, self._run_services)
                    last_seen = freshness_future.result()
                    metric_names, series = counts_future.result()
                    services = services_future.result()

            return MetricsOverview(
                last_seen=last_seen,
                metric_names=metric_names,
                series=series,
                lookback_seconds=int(self.lookback.total_seconds()),
                services=services,
            )
