"""Build metrics overview data from `metric_series`.

`max(last_seen)` and `uniqExact` handle duplicate rows without FINAL.
Counts use a window so the index skips old parts. Freshness reads the last
data point. All three queries run concurrently.
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
from posthog.dataclasses import frozen
from posthog.models import Team
from posthog.settings import TEST

from products.metrics.backend.facade.contracts import MetricsOverview, MetricsServiceOverview

tracer = trace.get_tracer(__name__)

# The overview accepts partial results. Stop at the read limit.
_QUERY_SETTINGS = HogQLGlobalSettings(
    max_bytes_to_read=HOGQL_MAX_BYTES_TO_READ_FOR_METRICS_USER_QUERIES,
    read_overflow_mode="break",
)

# Show only the largest services.
MAX_SERVICES = 500

DEFAULT_LOOKBACK = dt.timedelta(days=1)


@frozen
class _OverviewCounts:
    metric_names: int
    series: int


def _set_query_timing_attributes(span: Span, response: HogQLQueryResponse) -> None:
    """Set separate timing attributes for the query and ClickHouse read."""
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
            # Report the last data point, even after ingestion stops.
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

    def _run_counts(self) -> _OverviewCounts:
        with tracer.start_as_current_span("metrics.overview.counts") as span:
            span.set_attribute("team_id", self.team.pk)
            # Put the time window in WHERE so the index skips old parts.
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
                return _OverviewCounts(metric_names=0, series=0)
            metric_names, series = response.results[0]
            return _OverviewCounts(metric_names=int(metric_names), series=int(series))

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
                counts = self._run_counts()
                services = self._run_services()
            else:
                with ThreadPoolExecutor(max_workers=3, thread_name_prefix="metrics_overview") as executor:
                    freshness_future = executor.submit(contextvars.copy_context().run, self._run_freshness)
                    counts_future = executor.submit(contextvars.copy_context().run, self._run_counts)
                    services_future = executor.submit(contextvars.copy_context().run, self._run_services)
                    last_seen = freshness_future.result()
                    counts = counts_future.result()
                    services = services_future.result()

            return MetricsOverview(
                last_seen=last_seen,
                metric_names=counts.metric_names,
                series=counts.series,
                lookback_seconds=int(self.lookback.total_seconds()),
                services=services,
            )
