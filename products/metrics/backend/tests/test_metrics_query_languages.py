import json
import math
import datetime as dt
from pathlib import Path
from typing import Any

import pytest
import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import MagicMock, patch

from django.test import override_settings

import requests
from parameterized import parameterized

from posthog.schema import DateRange, HogQLQuery, MetricsQuery, MetricsQueryClause

from posthog.hogql.errors import ExposedHogQLError

from posthog.hogql_queries.hogql_query_runner import HogQLQueryRunner

from products.access_control.backend.facade.user_access_control import UserAccessControlError
from products.metrics.backend.hogql_queries.metrics_query_runner import MetricsQueryRunner
from products.metrics.backend.tests._seeder import seed_metric

FIXTURES: dict[str, dict[str, Any]] = json.loads(
    (Path(__file__).parents[2] / "frontend/queryLanguages/__fixtures__/builder_sql.json").read_text()
)
NOW = dt.datetime(2026, 9, 19, 12, 0, tzinfo=dt.UTC)
DATE_RANGE = DateRange(date_from="2026-09-19T11:00:00Z", date_to="2026-09-19T12:00:00Z")
HISTOGRAM_BOUNDS = [10.0, 50.0, 100.0]
SERIES_LABELS = [
    ("api", {"http.route": "/api/users", "http.request.method": "GET", "http.response.status_code": "200"}),
    ("api", {"http.route": "/health", "http.request.method": "OPTIONS", "http.response.status_code": "500"}),
    ("worker", {"http.route": "/api/jobs", "http.request.method": "GET", "http.response.status_code": "503"}),
]


def _metric_kinds() -> dict[str, str]:
    kinds: dict[str, str] = {}
    for fixture in FIXTURES.values():
        for clause in fixture["builder"]["clauses"]:
            aggregation = clause["aggregation"]
            kinds[clause["metricName"]] = (
                "histogram"
                if aggregation == "histogram_quantile"
                else "counter"
                if aggregation in ("rate", "increase")
                else "gauge"
            )
    return kinds


def _comparable(series: list[Any], *, use_clause: bool) -> dict[tuple, dict[str, float]]:
    # A SQL union fills the labels another series groups by with ''; the builder has no such label.
    out: dict[tuple, dict[str, float]] = {}
    for item in series:
        labels = tuple(sorted((key, value) for key, value in item.labels.items() if value != ""))
        key = (item.clause if use_clause else None, labels)
        out[key] = {point.time: point.value for point in item.points if point.value is not None}
    return out


@time_machine.travel(NOW, tick=False)
class TestMetricsSqlMode(ClickhouseTestMixin, APIBaseTest):
    def _seed(self) -> None:
        start = NOW - dt.timedelta(minutes=70)
        for metric_name, kind in _metric_kinds().items():
            for index, (service, labels) in enumerate(SERIES_LABELS):
                minutes = range(0, 70, 1)
                if kind == "gauge":
                    points = [(start + dt.timedelta(minutes=m), float((index + 1) * 10 + m % 7)) for m in minutes]
                    seed_metric(
                        team_id=self.team.pk,
                        metric_name=metric_name,
                        points=points,
                        labels={**labels, "queue": 'it\'s a "quoted" \\ value'},
                        service_name=service,
                    )
                elif kind == "counter":
                    points = [(start + dt.timedelta(minutes=m), float((index + 1) * m * 3)) for m in minutes]
                    seed_metric(
                        team_id=self.team.pk,
                        metric_name=metric_name,
                        points=points,
                        labels=labels,
                        service_name=service,
                        metric_type="sum",
                        is_monotonic=True,
                    )
                else:
                    for m in minutes:
                        seed_metric(
                            team_id=self.team.pk,
                            metric_name=metric_name,
                            points=[(start + dt.timedelta(minutes=m), 0.0)],
                            labels=labels,
                            service_name=service,
                            metric_type="histogram",
                            histogram_bounds=HISTOGRAM_BOUNDS,
                            histogram_counts=[m * (index + 1), m * 3, m, 0],
                        )

    def _run(self, **fields: Any) -> list[Any]:
        query = MetricsQuery(dateRange=DATE_RANGE, interval="minute_5", **fields)
        return MetricsQueryRunner(query=query, team=self.team).calculate().results

    def test_generated_sql_matches_the_builder_engine(self) -> None:
        self._seed()
        for name, fixture in FIXTURES.items():
            with self.subTest(fixture=name):
                builder = fixture["builder"]
                expected = self._run(
                    clauses=[MetricsQueryClause(**clause) for clause in builder["clauses"]],
                    formula=builder.get("formula"),
                )
                actual = self._run(clauses=[], language="sql", sql=fixture["sql"])

                use_clause = len(builder["clauses"]) > 1 and not builder.get("formula")
                expected_points = _comparable(expected, use_clause=use_clause)
                actual_points = _comparable(actual, use_clause=use_clause)
                assert set(actual_points) == {key for key, values in expected_points.items() if values}, name
                for key, values in actual_points.items():
                    # The builder fills empty buckets with 0, so compare the buckets SQL returned.
                    for time, value in values.items():
                        assert math.isclose(value, expected_points[key].get(time, 0.0), rel_tol=1e-6, abs_tol=1e-9), (
                            name,
                            key,
                            time,
                        )

    @parameterized.expand(
        [
            ("no_value_column", "SELECT timestamp AS time FROM posthog.metrics", 'a "time" and a "value" column'),
            ("other_table", "SELECT timestamp AS time, 1 AS value FROM events", "can only read the metrics tables"),
            (
                "other_table_in_subquery",
                "SELECT now() AS time, count() AS value FROM posthog.metrics WHERE metric_name IN (SELECT event FROM events)",
                "can only read the metrics tables",
            ),
        ]
    )
    def test_rejects_sql_outside_the_contract(self, _name: str, sql: str, message: str) -> None:
        with pytest.raises(ExposedHogQLError, match=message):
            self._run(clauses=[], language="sql", sql=sql)

    def test_date_placeholders_follow_the_date_range(self) -> None:
        seed_metric(
            team_id=self.team.pk,
            metric_name="queue_depth",
            points=[(NOW - dt.timedelta(minutes=30), 4.0), (NOW - dt.timedelta(hours=3), 9.0)],
        )
        sql = (
            "SELECT toStartOfInterval(timestamp, {interval}) AS time, max(value) AS value FROM posthog.metrics "
            "WHERE metric_name = 'queue_depth' AND timestamp >= {date_from} AND timestamp < {date_to} GROUP BY time"
        )

        [series] = self._run(clauses=[], language="sql", sql=sql)

        assert [point.value for point in series.points] == [4.0]

    def test_caches_like_a_metrics_insight_not_a_sql_insight(self) -> None:
        sql = "SELECT now() AS time, 1 AS value FROM posthog.metrics"
        sql_runner = MetricsQueryRunner(query=MetricsQuery(clauses=[], language="sql", sql=sql), team=self.team)
        builder_runner = MetricsQueryRunner(
            query=MetricsQuery(clauses=[MetricsQueryClause(name="a", metricName="queue_depth", aggregation="sum")]),
            team=self.team,
        )
        other_sql_runner = MetricsQueryRunner(
            query=MetricsQuery(clauses=[], language="sql", sql=sql + " LIMIT 5"), team=self.team
        )

        sql_insight_runner = HogQLQueryRunner(query=HogQLQuery(query=sql), team=self.team)

        sql_age = sql_runner.cache_target_age(NOW)
        sql_insight_age = sql_insight_runner.cache_target_age(NOW)
        assert sql_age is not None and sql_insight_age is not None
        assert sql_age == builder_runner.cache_target_age(NOW)
        assert sql_age < sql_insight_age
        assert sql_runner.get_cache_key() != other_sql_runner.get_cache_key()
        assert sql_runner.get_cache_payload()["query_runner"] == "MetricsQueryRunner"


def _snuffle_response(status_code: int, payload: dict[str, Any]) -> MagicMock:
    response = MagicMock(spec=requests.Response)
    response.status_code = status_code
    response.json.return_value = payload
    response.headers = {}
    return response


@override_settings(SNUFFLE_APM_URL="http://snuffle.test:9091", SNUFFLE_APM_USER="reader", SNUFFLE_APM_PASSWORD="secret")
@time_machine.travel(NOW, tick=False)
class TestMetricsPromQLMode(APIBaseTest):
    def _runner(self, promql: str = "sum by (job) (rate(http_requests_total))") -> MetricsQueryRunner:
        query = MetricsQuery(clauses=[], language="promql", promql=promql, dateRange=DATE_RANGE)
        return MetricsQueryRunner(query=query, team=self.team)

    def test_runs_a_range_query_and_maps_the_matrix(self) -> None:
        start = int(dt.datetime(2026, 9, 19, 11, 0, tzinfo=dt.UTC).timestamp())
        payload = {
            "status": "success",
            "data": {
                "resultType": "matrix",
                "result": [
                    {"metric": {"job": "api", "clause": "a"}, "values": [[start, "1.5"], [start + 60, "NaN"]]},
                    {"metric": {"__name__": "up", "job": "worker"}, "values": [[start + 60, "4"]]},
                ],
            },
        }
        with patch(
            "posthog.api.snuffle_proxy.internal_requests.request", return_value=_snuffle_response(200, payload)
        ) as request:
            results = self._runner().calculate().results

        method, url = request.call_args.args
        sent = request.call_args.kwargs
        assert (method, url) == ("POST", "http://snuffle.test:9091/api/v1/query_range")
        assert sent["data"]["query"] == "sum by (job) (rate(http_requests_total))"
        assert sent["data"]["step"] == "60"
        assert sent["headers"]["X-Team-ID"] == str(self.team.pk)
        by_job = {series.labels["job"]: series for series in results}
        assert [point.value for point in by_job["worker"].points] == [None, 4.0]
        assert [point.value for point in by_job["api"].points] == [1.5, None]
        assert by_job["api"].clause == "a"
        assert by_job["worker"].metricName == "up"

    @parameterized.expand(
        [
            (
                "bad_query",
                _snuffle_response(400, {"status": "error", "errorType": "bad_data", "error": "parse error at char 5"}),
                "parse error at char 5",
            ),
            ("upstream_failure", _snuffle_response(503, {}), "backend failed"),
        ]
    )
    def test_upstream_errors_are_shown_to_the_user(self, _name: str, response: MagicMock, message: str) -> None:
        with patch("posthog.api.snuffle_proxy.internal_requests.request", return_value=response):
            with pytest.raises(ExposedHogQLError, match=message):
                self._runner().calculate()

    def test_explains_when_snuffle_is_not_configured(self) -> None:
        with override_settings(SNUFFLE_APM_URL=""):
            with pytest.raises(ExposedHogQLError, match="not available"):
                self._runner().calculate()

    def test_timeout_is_shown_to_the_user(self) -> None:
        with patch("posthog.api.snuffle_proxy.internal_requests.request", side_effect=requests.Timeout()):
            with pytest.raises(ExposedHogQLError, match="timed out"):
                self._runner().calculate()

    def test_needs_the_snuffle_flag(self) -> None:
        def flag_enabled(flag: str, *args: Any, **kwargs: Any) -> bool:
            return flag != "logs-metrics-snuffle-api"

        with patch("posthoganalytics.feature_enabled", side_effect=flag_enabled):
            with pytest.raises(UserAccessControlError):
                self._runner().validate_query_runner_access(self.user)
