import json
import datetime as dt

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.clickhouse.client import sync_execute
from posthog.models import Team

from products.metrics.backend.derived import DerivedMetricQueryRunner
from products.metrics.backend.facade.api import list_metric_names, run_metric_query
from products.metrics.backend.facade.contracts import (
    METRICS_DERIVED_SERIES_FEATURE_FLAG,
    MetricFilter,
    MetricGroupBy,
    MetricQueryClause,
    MetricQueryRequest,
    MetricQueryTooManyRowsError,
    MetricSeries,
)
from products.metrics.backend.facade.enums import FilterOp, MetricAggregation, MetricRangeFunction

REQUESTS = "posthog.derived.spans.requests"
ERRORS = "posthog.derived.spans.errors"
DURATION = "posthog.derived.spans.duration"
LOG_RECORDS = "posthog.derived.logs.records"

DATE_FROM = dt.datetime(2026, 6, 2, 8, 0, tzinfo=dt.UTC)
DATE_TO = dt.datetime(2026, 6, 2, 9, 0, tzinfo=dt.UTC)

SERVER, INTERNAL, CLIENT = 2, 1, 3
OK, ERROR = 0, 2

# (service, kind, is_root, duration_ms, status, http.route)
# "web" has server spans, so its root internal span (a cron job) and its client child do not count.
# "worker" has no server spans, so its root spans count as requests and its child does not.
SPANS = [
    ("web", SERVER, True, 10, OK, "/a"),
    ("web", SERVER, True, 20, OK, "/a"),
    ("web", SERVER, True, 30, OK, "/a"),
    ("web", SERVER, True, 40, ERROR, "/a"),
    ("web", CLIENT, False, 500, OK, None),
    ("web", INTERNAL, True, 900, OK, None),
    ("worker", INTERNAL, True, 100, OK, None),
    ("worker", INTERNAL, True, 300, ERROR, None),
    ("worker", INTERNAL, False, 700, ERROR, None),
    ("api", SERVER, True, 5, OK, "/b"),
]

# (service, severity)
LOGS = [("web", "info"), ("web", "info"), ("web", "error"), ("worker", "warn")]


def _flags(*enabled: str):
    return patch("posthoganalytics.feature_enabled", side_effect=lambda flag, *_, **__: flag in enabled)


def _insert_spans(team_id: int) -> None:
    rows: list[str] = []
    for index, (service, kind, is_root, duration_ms, status, route) in enumerate(SPANS):
        start = DATE_FROM + dt.timedelta(minutes=10, seconds=index)
        end = start + dt.timedelta(milliseconds=duration_ms)
        parent = "" if is_root else f"parent{index}"
        attributes = f"{{'http.route__str': '{route}'}}" if route else "{}"
        rows.append(
            f"('019e8756-0000-0000-0000-{index:012d}', {team_id}, 'trace{index}', 'span{index}', '{parent}', "
            f"'op', {kind}, '{start:%Y-%m-%d %H:%M:%S.%f}', '{end:%Y-%m-%d %H:%M:%S.%f}', "
            f"'{start:%Y-%m-%d %H:%M:%S.%f}', {status}, '{service}', {attributes})"
        )
    sync_execute(
        "INSERT INTO trace_spans (uuid, team_id, trace_id, span_id, parent_span_id, name, kind, timestamp, "
        "end_time, observed_timestamp, status_code, service_name, attributes_map_str) VALUES " + ",".join(rows)
    )


def _insert_logs(team_id: int) -> None:
    rows = []
    for index, (service, severity) in enumerate(LOGS):
        timestamp = DATE_FROM + dt.timedelta(minutes=20, seconds=index)
        rows.append(
            {
                "team_id": team_id,
                "timestamp": f"{timestamp:%Y-%m-%d %H:%M:%S.%f}",
                "observed_timestamp": f"{timestamp:%Y-%m-%d %H:%M:%S.%f}",
                "service_name": service,
                "severity_text": severity,
                "body": "line",
            }
        )
    sync_execute("INSERT INTO logs FORMAT JSONEachRow\n" + "\n".join(json.dumps(row) for row in rows))


def _by_label(series: list[MetricSeries], key: str) -> dict[str, float | None]:
    return {s.labels.get(key, ""): s.points[0].value for s in series if s.points}


class TestDerivedMetricsQuery(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        _insert_spans(self.team.id)
        _insert_logs(self.team.id)

    def _run(
        self,
        metric_name: str,
        aggregation: MetricAggregation,
        *,
        quantile: float | None = None,
        group_by: tuple[str, ...] = ("service.name",),
        filters: tuple[MetricFilter, ...] = (),
        range_function: MetricRangeFunction | None = None,
    ) -> list[MetricSeries]:
        clause = MetricQueryClause(
            name="a",
            metric_name=metric_name,
            aggregation=aggregation,
            quantile=quantile,
            group_by=tuple(MetricGroupBy(key=key) for key in group_by),
            filters=filters,
            range_function=range_function,
        )
        request = MetricQueryRequest(clauses=(clause,), date_from=DATE_FROM, date_to=DATE_TO, interval="hour")
        return run_metric_query(team=self.team, request=request)

    @parameterized.expand(
        [
            ("requests", REQUESTS, MetricAggregation.SUM, None, None, {"web": 4, "worker": 2, "api": 1}),
            ("requests_increase", REQUESTS, MetricAggregation.INCREASE, None, None, {"web": 4, "worker": 2, "api": 1}),
            ("errors", ERRORS, MetricAggregation.SUM, None, None, {"web": 1, "worker": 1}),
            (
                "request_rate",
                REQUESTS,
                MetricAggregation.SUM,
                None,
                MetricRangeFunction.RATE,
                {"web": 4 / 3600, "worker": 2 / 3600, "api": 1 / 3600},
            ),
            ("max_duration_ms", DURATION, MetricAggregation.MAX, None, None, {"web": 40, "worker": 300, "api": 5}),
            (
                "p50_duration_ms",
                DURATION,
                MetricAggregation.HISTOGRAM_QUANTILE,
                0.5,
                None,
                {"web": 25, "worker": 200, "api": 5},
            ),
        ]
    )
    def test_span_series_per_service_match_the_fixtures(
        self,
        _name: str,
        metric_name: str,
        aggregation: MetricAggregation,
        quantile: float | None,
        range_function: MetricRangeFunction | None,
        expected: dict[str, float],
    ) -> None:
        with _flags("metrics", METRICS_DERIVED_SERIES_FEATURE_FLAG):
            series = self._run(metric_name, aggregation, quantile=quantile, range_function=range_function)

        assert _by_label(series, "service.name") == expected

    def test_span_attribute_group_by_and_filter(self) -> None:
        with _flags("metrics", METRICS_DERIVED_SERIES_FEATURE_FLAG):
            series = self._run(
                REQUESTS,
                MetricAggregation.SUM,
                group_by=("http.route",),
                filters=(MetricFilter(key="service.name", op=FilterOp.NEQ, value="worker"),),
            )

        assert _by_label(series, "http.route") == {"/a": 4, "/b": 1}

    def test_log_records_per_severity(self) -> None:
        with _flags("metrics", METRICS_DERIVED_SERIES_FEATURE_FLAG):
            series = self._run(
                LOG_RECORDS,
                MetricAggregation.SUM,
                group_by=("severity_text",),
                filters=(MetricFilter(key="service.name", op=FilterOp.EQ, value="web"),),
            )

        assert _by_label(series, "severity_text") == {"info": 2, "error": 1}

    def test_derived_series_stay_hidden_without_the_flag(self) -> None:
        with _flags("metrics"):
            series = self._run(REQUESTS, MetricAggregation.SUM)

        assert all(not s.points for s in series)

    def test_row_cap_raises_instead_of_dropping_series(self) -> None:
        with (
            _flags("metrics", METRICS_DERIVED_SERIES_FEATURE_FLAG),
            patch("products.metrics.backend.derived._ROW_LIMIT", 2),
            self.assertRaises(MetricQueryTooManyRowsError),
        ):
            self._run(REQUESTS, MetricAggregation.SUM)

    @time_machine.travel(DATE_TO, tick=False)
    def test_names_list_derived_metrics_only_for_teams_with_spans_or_logs(self) -> None:
        empty_team = Team.objects.create(organization=self.organization, name="no telemetry")

        with _flags("metrics", METRICS_DERIVED_SERIES_FEATURE_FLAG):
            names = {row["name"] for row in list_metric_names(team=self.team)}
            empty_names = {row["name"] for row in list_metric_names(team=empty_team)}

        assert {REQUESTS, ERRORS, DURATION, LOG_RECORDS} <= names
        assert not any(name.startswith("posthog.derived.") for name in empty_names)

    def test_query_event_marks_derived_queries(self) -> None:
        with (
            _flags("metrics", METRICS_DERIVED_SERIES_FEATURE_FLAG),
            patch("products.metrics.backend.presentation.api.report_user_action") as report,
        ):
            response = self.client.post(
                f"/api/projects/{self.team.id}/metrics/query/",
                {
                    "query": {
                        "metricName": REQUESTS,
                        "aggregation": "sum",
                        "dateFrom": DATE_FROM.isoformat(),
                        "dateTo": DATE_TO.isoformat(),
                        "interval": "hour",
                    }
                },
                format="json",
            )

        assert response.status_code == 200, response.json()
        assert sum(point["value"] for point in response.json()["results"][0]["points"]) == 7
        assert report.call_args.args[2]["is_derived"] is True


class TestDerivedMetricQueryCaps(SimpleTestCase):
    @parameterized.expand(
        [
            ("range_over_seven_days", REQUESTS, MetricAggregation.SUM, None, (), 8),
            ("three_group_by_keys", REQUESTS, MetricAggregation.SUM, None, ("a", "b", "c"), 1),
            ("count_of_a_counter", REQUESTS, MetricAggregation.COUNT, None, (), 1),
            ("sum_of_durations", DURATION, MetricAggregation.SUM, None, (), 1),
            ("raw_series", REQUESTS, MetricAggregation.NONE, None, (), 1),
            ("unknown_derived_name", "posthog.derived.spans.nope", MetricAggregation.SUM, None, (), 1),
        ]
    )
    def test_rejects_queries_outside_the_caps(
        self,
        _name: str,
        metric_name: str,
        aggregation: MetricAggregation,
        quantile: float | None,
        group_by: tuple[str, ...],
        days: int,
    ) -> None:
        clause = MetricQueryClause(
            name="a",
            metric_name=metric_name,
            aggregation=aggregation,
            quantile=quantile,
            group_by=tuple(MetricGroupBy(key=key) for key in group_by),
        )

        with self.assertRaises(ValueError):
            DerivedMetricQueryRunner(
                team=Team(timezone="UTC"),
                clause=clause,
                date_from=DATE_TO - dt.timedelta(days=days),
                date_to=DATE_TO,
                interval=None,
            )
