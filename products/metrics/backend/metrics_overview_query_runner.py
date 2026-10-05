"""No FINAL: the distinct counts and `max(last_seen)` give the same result on unmerged duplicate rows."""

import datetime as dt
import contextvars
from concurrent.futures import ThreadPoolExecutor

from opentelemetry import trace
from opentelemetry.trace import Span

from posthog.schema import HogQLQueryModifiers, HogQLQueryResponse

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

_QUERY_SETTINGS = HogQLGlobalSettings(
    max_bytes_to_read=HOGQL_MAX_BYTES_TO_READ_FOR_METRICS_USER_QUERIES,
    read_overflow_mode="break",
)

MAX_SERVICES = 500

DEFAULT_LOOKBACK = dt.timedelta(days=1)


@frozen
class _ServicesRollup:
    services: tuple[MetricsServiceOverview, ...]
    series: int
    last_seen: str | None


def _set_query_timing_attributes(span: Span, response: HogQLQueryResponse) -> None:
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

    def _run_freshness_fallback(self) -> str | None:
        with tracer.start_as_current_span("metrics.overview.freshness") as span:
            span.set_attribute("team_id", self.team.pk)
            query = parse_select(
                """
                    SELECT max(toNullable(last_seen)) AS last_seen_at
                    FROM posthog.metric_series
                    WHERE last_seen >= (SELECT max(time_bucket) FROM posthog.metric_names)
                """
            )
            assert isinstance(query, ast.SelectQuery)

            response = execute_hogql_query(
                query_type="MetricsOverviewFreshnessQuery",
                query=query,
                team=self.team,
                workload=Workload.LOGS,
                settings=_QUERY_SETTINGS,
            )
            _set_query_timing_attributes(span, response)
            if not response.results or response.results[0][0] is None:
                return None
            return response.results[0][0].isoformat()

    def _run_metric_names_count(self) -> int:
        with tracer.start_as_current_span("metrics.overview.metric_names") as span:
            span.set_attribute("team_id", self.team.pk)
            query = parse_select(
                """
                    SELECT uniqExact(metric_name) AS metric_names
                    FROM posthog.metric_names
                    WHERE time_bucket >= toStartOfHour(now() - {lookback})
                """,
                placeholders={"lookback": self._lookback_interval()},
            )
            assert isinstance(query, ast.SelectQuery)

            response = execute_hogql_query(
                query_type="MetricsOverviewMetricNamesQuery",
                query=query,
                team=self.team,
                workload=Workload.LOGS,
                settings=_QUERY_SETTINGS,
            )
            _set_query_timing_attributes(span, response)
            if not response.results:
                return 0
            return int(response.results[0][0])

    def _run_services(self) -> _ServicesRollup:
        with tracer.start_as_current_span("metrics.overview.services") as span:
            span.set_attribute("team_id", self.team.pk)
            # The services_by_hour projection answers this query only while it filters on time_bucket, uses uniq,
            # and aggregates the bare last_seen column. The time zone conversion stays outside max() for that reason.
            # Each series has one service, so the sum of the service counts counts each series once.
            query = parse_select(
                """
                    SELECT
                        service_name,
                        uniqExact(metric_name) AS metric_names,
                        uniq(series_fingerprint) AS series,
                        toTimeZone(max(last_seen), 'UTC') AS last_seen_at,
                        sum(uniq(series_fingerprint)) OVER () AS total_series,
                        toTimeZone(max(max(last_seen)) OVER (), 'UTC') AS total_last_seen_at
                    FROM posthog.metric_series
                    WHERE time_bucket >= toStartOfHour(toTimeZone(now() - {lookback}, 'UTC'))
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
                workload=Workload.LOGS,
                settings=_QUERY_SETTINGS,
                modifiers=HogQLQueryModifiers(convertToProjectTimezone=False),
            )
            _set_query_timing_attributes(span, response)
            span.set_attribute("services.count", len(response.results))
            if not response.results:
                return _ServicesRollup(services=(), series=0, last_seen=None)
            return _ServicesRollup(
                services=tuple(
                    MetricsServiceOverview(
                        service_name=row[0],
                        metric_names=int(row[1]),
                        series=int(row[2]),
                        last_seen=row[3].isoformat(),
                    )
                    for row in response.results
                ),
                series=int(response.results[0][4]),
                last_seen=response.results[0][5].isoformat(),
            )

    def run(self) -> MetricsOverview:
        with tracer.start_as_current_span("metrics.overview.run") as span:
            span.set_attribute("team_id", self.team.pk)
            span.set_attribute("lookback_seconds", int(self.lookback.total_seconds()))

            if TEST:
                rollup = self._run_services()
                metric_names = self._run_metric_names_count()
            else:
                with ThreadPoolExecutor(max_workers=2, thread_name_prefix="metrics_overview") as executor:
                    services_future = executor.submit(contextvars.copy_context().run, self._run_services)
                    metric_names_future = executor.submit(contextvars.copy_context().run, self._run_metric_names_count)
                    rollup = services_future.result()
                    metric_names = metric_names_future.result()

            last_seen = rollup.last_seen if rollup.services else self._run_freshness_fallback()

            return MetricsOverview(
                last_seen=last_seen,
                metric_names=metric_names,
                series=rollup.series,
                lookback_seconds=int(self.lookback.total_seconds()),
                services=rollup.services,
            )
