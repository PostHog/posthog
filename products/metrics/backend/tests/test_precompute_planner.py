import math
import datetime as dt

from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from django.test import override_settings

from parameterized import parameterized
from structlog.testing import capture_logs

from posthog.schema import MetricsQuery, MetricsQueryClause

from posthog.hogql_queries.query_runner import ExecutionMode

from products.metrics.backend.facade.api import run_metric_query, run_precomputed_metric_query
from products.metrics.backend.facade.contracts import (
    MetricFilter,
    MetricGroupBy,
    MetricQueryClause,
    MetricQueryRequest,
    MetricSeries,
)
from products.metrics.backend.facade.enums import (
    FilterOp,
    MetricAggregation,
    MetricQueryProvenanceMode,
    MetricRangeFunction,
    MetricType,
)
from products.metrics.backend.hogql_queries.metrics_query_runner import MetricsQueryRunner
from products.metrics.backend.models import MetricPrecomputedMetric
from products.metrics.backend.precompute.definitions import get_or_create_precomputed_metric, leaf_for_clause
from products.metrics.backend.precompute.fill import fill_precomputed_metrics
from products.metrics.backend.tests._seeder import batched_seeding, seed_metric, truncate_metrics_tables

NOW = dt.datetime(2026, 11, 12, 12, 7, tzinfo=dt.UTC)
SEED_FROM = NOW - dt.timedelta(days=4)
BOUNDS = [0.05, 0.1, 0.25, 0.5, 1.0, 2.5]

COUNTER = "http_requests_total"
HISTOGRAM = "http_request_duration_seconds"


def _counter_clause(aggregation: MetricAggregation, **fields) -> MetricQueryClause:
    return MetricQueryClause(name="a", metric_name=COUNTER, aggregation=aggregation, **fields)


def _histogram_clause(
    aggregation: MetricAggregation = MetricAggregation.HISTOGRAM_QUANTILE, **fields
) -> MetricQueryClause:
    return MetricQueryClause(
        name="a",
        metric_name=HISTOGRAM,
        aggregation=aggregation,
        metric_type=MetricType.HISTOGRAM,
        **fields,
    )


BY_SERVICE = (MetricGroupBy(key="service_name"),)
SERVER_ERRORS = (MetricFilter(key="status", op=FilterOp.REGEX, value="^5"),)


# The clause queries otherwise run on threads that can't see the test transaction.
@override_settings(IN_UNIT_TESTING=True)
class TestPrecomputedMetricQuery(ClickhouseTestMixin, APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self):
        super().setUp()
        truncate_metrics_tables()
        with batched_seeding():
            self._seed()

    def _seed(self) -> None:
        minutes = int((NOW - SEED_FROM).total_seconds() // 60)
        for service_index, service in enumerate(("checkout", "search")):
            for status in ("200", "503"):
                total, points = 0.0, []
                for minute in range(0, minutes, 5):
                    # Uneven increments and one counter reset, so per-hour and per-day sums must agree exactly.
                    total = 0.0 if minute == 2400 else total + 1 + (minute * 7 + service_index * 3 + len(status)) % 11
                    points.append((SEED_FROM + dt.timedelta(minutes=minute, seconds=13), total))
                seed_metric(
                    team_id=self.team.pk,
                    metric_name=COUNTER,
                    metric_type="sum",
                    is_monotonic=True,
                    service_name=service,
                    labels={"status": status},
                    points=points,
                )
            for minute in range(0, minutes, 10):
                counts = [(minute // 10 + service_index + bucket) % 4 for bucket in range(len(BOUNDS) + 1)]
                seed_metric(
                    team_id=self.team.pk,
                    metric_name=HISTOGRAM,
                    metric_type="histogram",
                    aggregation_temporality="delta",
                    service_name=service,
                    histogram_bounds=BOUNDS,
                    histogram_counts=counts,
                    count=sum(counts),
                    points=[(SEED_FROM + dt.timedelta(minutes=minute, seconds=29), 0.0)],
                )

    def _set_timezone(self, timezone: str) -> None:
        self.team.timezone = timezone
        self.team.save()

    def _precompute(self, clause: MetricQueryClause) -> None:
        leaf = leaf_for_clause(clause)
        assert not isinstance(leaf, str), leaf
        assert get_or_create_precomputed_metric(self.team.pk, leaf) is not None
        fill_precomputed_metrics(self.team.pk, now=NOW)

    def _request(self, clause: MetricQueryClause, interval: str | None, days: float = 2) -> MetricQueryRequest:
        return MetricQueryRequest(
            clauses=(clause,), date_from=NOW - dt.timedelta(days=days), date_to=NOW, interval=interval
        )

    def _assert_same_series(self, precomputed: list[MetricSeries], raw: list[MetricSeries]) -> None:
        def by_labels(series: list[MetricSeries]) -> dict:
            return {tuple(sorted(s.labels.items())): s for s in series}

        precomputed_by_labels, raw_by_labels = by_labels(precomputed), by_labels(raw)
        assert precomputed_by_labels.keys() == raw_by_labels.keys()
        for key, raw_series in raw_by_labels.items():
            got = precomputed_by_labels[key]
            assert [p.time for p in got.points] == [p.time for p in raw_series.points]
            assert any(p.value for p in raw_series.points)
            for got_point, raw_point in zip(got.points, raw_series.points):
                assert (got_point.value is None) == (raw_point.value is None), got_point.time
                if raw_point.value is not None:
                    assert math.isclose(got_point.value, raw_point.value, rel_tol=1e-9, abs_tol=1e-9), (
                        got_point.time,
                        got_point.value,
                        raw_point.value,
                    )
            assert got.unit == raw_series.unit

    @parameterized.expand(
        [
            (
                "increase_by_service_hourly",
                "UTC",
                _counter_clause(MetricAggregation.INCREASE, group_by=BY_SERVICE),
                "hour",
            ),
            (
                "rate_of_server_errors_6h_new_york",
                "America/New_York",
                _counter_clause(MetricAggregation.RATE, filters=SERVER_ERRORS),
                "hour_6",
            ),
            (
                "sum_of_increase_daily_new_york",
                "America/New_York",
                _counter_clause(
                    MetricAggregation.SUM, range_function=MetricRangeFunction.INCREASE, group_by=BY_SERVICE
                ),
                "day",
            ),
            (
                "histogram_request_rate_auto_interval",
                "UTC",
                _histogram_clause(aggregation=MetricAggregation.COUNT_RATE),
                None,
            ),
            ("histogram_p95_by_service_6h", "UTC", _histogram_clause(quantile=0.95, group_by=BY_SERVICE), "hour_6"),
            ("histogram_p50_daily_tokyo", "Asia/Tokyo", _histogram_clause(quantile=0.5), "day"),
        ]
    )
    def test_matches_raw_over_a_range_spanning_stored_and_raw_buckets(
        self, _name: str, timezone: str, clause: MetricQueryClause, interval: str | None
    ):
        self._set_timezone(timezone)
        self._precompute(clause)
        request = self._request(clause, interval)

        result = run_precomputed_metric_query(team=self.team, request=request)

        assert result.provenance.mode == MetricQueryProvenanceMode.MIXED, result.provenance
        assert result.provenance.precomputed_until is not None and result.provenance.precomputed_until < NOW
        self._assert_same_series(result.series, run_metric_query(team=self.team, request=request))

    def test_a_sampled_tile_also_runs_raw_and_logs_how_far_apart_they_are(self):
        clause = _counter_clause(MetricAggregation.INCREASE, group_by=BY_SERVICE)
        self._precompute(clause)

        with (
            patch("products.metrics.backend.facade.api.PRECOMPUTE_SHADOW_CHECK_RATE", 1.0),
            capture_logs() as logs,
        ):
            run_precomputed_metric_query(team=self.team, request=self._request(clause, "hour"))

        (check,) = [log for log in logs if log["event"] == "metrics_precompute_shadow_check"]
        assert check["max_relative_difference"] == 0.0
        assert check["mode"] == "mixed"

    @parameterized.expand(
        [
            ("gauge_sum", _counter_clause(MetricAggregation.SUM, group_by=BY_SERVICE)),
            ("max_of_rate", _counter_clause(MetricAggregation.MAX, range_function=MetricRangeFunction.RATE)),
        ]
    )
    def test_unsupported_shapes_run_raw_unchanged(self, _name: str, clause: MetricQueryClause):
        request = self._request(clause, "hour")

        result = run_precomputed_metric_query(team=self.team, request=request)

        assert result.provenance.mode == MetricQueryProvenanceMode.RAW
        assert result.provenance.reasons
        assert result.series == run_metric_query(team=self.team, request=request)
        assert not MetricPrecomputedMetric.objects.for_team(self.team.pk).exists()

    def test_first_long_range_tile_creates_its_metric_and_runs_raw_meanwhile(self):
        clause = _counter_clause(MetricAggregation.INCREASE, group_by=BY_SERVICE)
        request = self._request(clause, "hour")

        result = run_precomputed_metric_query(team=self.team, request=request)

        assert result.provenance.mode == MetricQueryProvenanceMode.RAW
        assert result.series == run_metric_query(team=self.team, request=request)
        created = MetricPrecomputedMetric.objects.for_team(self.team.pk).get()
        assert created.labels == [{"key": "service_name", "scope": "auto"}]

    def test_short_range_tile_does_not_create_a_metric(self):
        clause = _counter_clause(MetricAggregation.INCREASE)

        run_precomputed_metric_query(team=self.team, request=self._request(clause, "minute_5", days=0.25))

        assert not MetricPrecomputedMetric.objects.for_team(self.team.pk).exists()

    def test_range_older_than_the_raw_tail_is_answered_only_from_storage(self):
        clause = _counter_clause(MetricAggregation.INCREASE, group_by=BY_SERVICE)
        self._precompute(clause)
        request = MetricQueryRequest(
            clauses=(clause,),
            date_from=NOW - dt.timedelta(days=3),
            date_to=NOW.replace(minute=0) - dt.timedelta(days=1),
            interval="hour",
        )

        result = run_precomputed_metric_query(team=self.team, request=request)

        assert result.provenance.mode == MetricQueryProvenanceMode.PRECOMPUTED
        self._assert_same_series(result.series, run_metric_query(team=self.team, request=request))

    def test_a_formula_over_a_precomputed_and_a_raw_clause_is_mixed_and_matches_raw(self):
        errors = MetricQueryClause(
            name="errors", metric_name=COUNTER, aggregation=MetricAggregation.INCREASE, filters=SERVER_ERRORS
        )
        self._precompute(errors)
        everything = MetricQueryClause(name="total", metric_name=COUNTER, aggregation=MetricAggregation.SUM)
        request = MetricQueryRequest(
            clauses=(errors, everything),
            date_from=NOW - dt.timedelta(days=2),
            date_to=NOW,
            interval="hour_6",
            formula="errors / total",
        )

        result = run_precomputed_metric_query(team=self.team, request=request)

        assert result.provenance.mode == MetricQueryProvenanceMode.MIXED
        self._assert_same_series(result.series, run_metric_query(team=self.team, request=request))


@override_settings(IN_UNIT_TESTING=True)
class TestMetricsQueryRunnerPrecompute(ClickhouseTestMixin, APIBaseTest):
    def _run(self, *, flag_on: bool, dashboard_id: int | None):
        runner = MetricsQueryRunner(
            query=MetricsQuery(
                clauses=[MetricsQueryClause(name="a", metricName=COUNTER, aggregation="increase")],
                dateRange={"date_from": "-7d"},
            ),
            team=self.team,
        )
        with patch(
            "products.metrics.backend.hogql_queries.metrics_query_runner.posthog_feature_flag_enabled",
            side_effect=lambda flag, *args, **kwargs: flag != "dashboard-v2" or flag_on,
        ):
            return runner.run(execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS, dashboard_id=dashboard_id)

    @parameterized.expand([("flag_off", False, 1), ("not_a_dashboard_tile", True, None)])
    def test_runs_exactly_as_before_without_dashboard_v2_on_a_tile(self, _name: str, flag_on: bool, dashboard_id):
        response = self._run(flag_on=flag_on, dashboard_id=dashboard_id)

        assert response.provenance is None
        assert not MetricPrecomputedMetric.objects.for_team(self.team.pk).exists()

    def test_a_dashboard_v2_tile_reports_where_its_buckets_came_from(self):
        response = self._run(flag_on=True, dashboard_id=1)

        assert response.provenance is not None and response.provenance.mode == "raw"
        assert MetricPrecomputedMetric.objects.for_team(self.team.pk).exists()
