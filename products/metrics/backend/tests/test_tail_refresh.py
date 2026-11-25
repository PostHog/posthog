import datetime as dt
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from zoneinfo import ZoneInfo

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.schema import (
    DateRange,
    MetricsHistogramQuery,
    MetricsHistogramQueryResponse,
    MetricsQuery,
    MetricsQueryClause,
    MetricsQueryGroupBy,
    MetricsQueryPoint,
    MetricsQuerySeries,
)

from posthog.api.snuffle_proxy import SNUFFLE_API_FEATURE_FLAG
from posthog.hogql_queries.query_runner import ExecutionMode

from products.metrics.backend.hogql_queries.metrics_histogram_query_runner import MetricsHistogramQueryRunner
from products.metrics.backend.hogql_queries.metrics_query_runner import MetricsQueryRunner
from products.metrics.backend.hogql_queries.tail_refresh import (
    FullRunReason,
    ShadowDiff,
    TailPlan,
    TailState,
    compare_grid,
    compare_series,
    merge_series,
    plan_tail,
)
from products.metrics.backend.tests._seeder import seed_metric, truncate_metrics_tables

UTC = ZoneInfo("UTC")
NOW = dt.datetime(2026, 9, 19, 12, 0, 30, tzinfo=dt.UTC)


def _state(**overrides: Any) -> TailState:
    values: dict[str, Any] = {
        "date_from": NOW - dt.timedelta(hours=1),
        "date_to": NOW,
        "interval": "minute",
        "full_at": NOW,
    }
    values.update(overrides)
    return TailState(**values)


def _series(labels: dict[str, str], values: dict[str, float | None], clause: str = "a") -> MetricsQuerySeries:
    return MetricsQuerySeries(
        labels=labels,
        clause=clause,
        metricName="m",
        points=[MetricsQueryPoint(time=time, value=value) for time, value in values.items()],
    )


class TestPlanTail(SimpleTestCase):
    @parameterized.expand(
        [
            ("no_cached_result", None, NOW + dt.timedelta(minutes=1), "minute", FullRunReason.NO_CACHED_RESULT),
            ("interval_changed", _state(), NOW + dt.timedelta(minutes=1), "minute_5", FullRunReason.INTERVAL_CHANGED),
            (
                "full_run_older_than_15_minutes",
                _state(full_at=NOW - dt.timedelta(minutes=14)),
                NOW + dt.timedelta(minutes=2),
                "minute",
                FullRunReason.PERIODIC_FULL_RUN,
            ),
            (
                "day_buckets",
                _state(interval="day"),
                NOW + dt.timedelta(minutes=1),
                "day",
                FullRunReason.COARSE_INTERVAL,
            ),
            (
                "window_moved_past_the_tail",
                _state(full_at=NOW + dt.timedelta(minutes=55)),
                NOW + dt.timedelta(minutes=55),
                "minute",
                FullRunReason.WINDOW_MOVED,
            ),
        ]
    )
    def test_full_run(
        self, _name: str, previous: TailState | None, now: dt.datetime, interval: str, reason: FullRunReason
    ) -> None:
        assert (
            plan_tail(
                previous,
                date_from=now - dt.timedelta(hours=1),
                date_to=now,
                interval=interval,
                now=now,
                tzinfo=UTC,
            )
            == reason
        )

    def test_window_that_starts_earlier_runs_in_full(self) -> None:
        now = NOW + dt.timedelta(minutes=1)
        assert (
            plan_tail(
                _state(),
                date_from=NOW - dt.timedelta(hours=2),
                date_to=now,
                interval="minute",
                now=now,
                tzinfo=UTC,
            )
            == FullRunReason.WINDOW_MOVED
        )

    @parameterized.expand(
        [
            # cut = floor(12:00:30 - 5m) = 11:55; lead-in = ceil((5m lookback + 2 * 1m) / 1m) steps = 7m.
            ("minute", "minute", UTC, "2026-09-19T11:55:00+00:00", "2026-09-19T11:48:00+00:00"),
            # 30-minute buckets: lookback is one step, so the lead-in is 3 steps.
            ("half_hour", "minute_30", UTC, "2026-09-19T11:30:00+00:00", "2026-09-19T10:00:00+00:00"),
            # The cut lands on the team's local 6-hour grid (12:00 IST), not on a UTC multiple of 6 hours.
            (
                "six_hours_half_hour_offset",
                "hour_6",
                ZoneInfo("Asia/Kolkata"),
                "2026-09-19T06:30:00+00:00",
                "2026-09-18T12:30:00+00:00",
            ),
        ]
    )
    def test_tail_plan(self, _name: str, interval: str, tzinfo: ZoneInfo, cut: str, fetch_from: str) -> None:
        now = NOW + dt.timedelta(minutes=1)
        previous = _state(date_from=NOW - dt.timedelta(days=7), interval=interval)

        plan = plan_tail(
            previous, date_from=now - dt.timedelta(days=7), date_to=now, interval=interval, now=now, tzinfo=tzinfo
        )

        assert plan == TailPlan(cut=dt.datetime.fromisoformat(cut), fetch_from=dt.datetime.fromisoformat(fetch_from))


class TestMergeSeries(SimpleTestCase):
    START = dt.datetime(2026, 9, 19, 11, 0, tzinfo=dt.UTC)
    CUT = dt.datetime(2026, 9, 19, 11, 2, tzinfo=dt.UTC)

    def _merge(
        self, cached: list[MetricsQuerySeries], tail: list[MetricsQuerySeries], formula: bool = False
    ) -> list[MetricsQuerySeries] | None:
        return merge_series(cached, tail, start=self.START, cut=self.CUT, clause_order=["a"], formula=formula)

    @parameterized.expand(
        [
            (
                "formula_label_set_only_in_tail",
                [_series({"pod": "a"}, {"2026-09-19T11:01:00+00:00": 1.0}, clause="formula")],
                [
                    _series({"pod": "a"}, {"2026-09-19T11:02:00+00:00": 1.0}, clause="formula"),
                    _series({"pod": "b"}, {"2026-09-19T11:02:00+00:00": 1.0}, clause="formula"),
                ],
                True,
            ),
            (
                "empty_result",
                [_series({}, {})],
                [_series({}, {"2026-09-19T11:02:00+00:00": 1.0})],
                False,
            ),
            (
                "clause_at_the_series_cap",
                [_series({"pod": str(i)}, {"2026-09-19T11:01:00+00:00": 1.0}) for i in range(100)],
                [_series({"pod": "0"}, {"2026-09-19T11:02:00+00:00": 1.0})],
                False,
            ),
            (
                "kept_points_all_zero_and_series_gone_from_tail",
                [
                    _series({"pod": "a"}, {"2026-09-19T11:01:00+00:00": 1.0}),
                    _series({"pod": "b"}, {"2026-09-19T11:01:00+00:00": 0.0}),
                ],
                [_series({"pod": "a"}, {"2026-09-19T11:02:00+00:00": 1.0})],
                False,
            ),
            (
                "unit_changed",
                [_series({"pod": "a"}, {"2026-09-19T11:01:00+00:00": 1.0}).model_copy(update={"unit": "s"})],
                [_series({"pod": "a"}, {"2026-09-19T11:02:00+00:00": 1.0}).model_copy(update={"unit": "ms"})],
                False,
            ),
            (
                "merged_clause_reaches_the_series_cap",
                [_series({"pod": f"old{i}"}, {"2026-09-19T11:01:00+00:00": 1.0}) for i in range(60)],
                [_series({"pod": f"new{i}"}, {"2026-09-19T11:02:00+00:00": 1.0}) for i in range(60)],
                False,
            ),
        ]
    )
    def test_refuses_merges_a_full_run_could_answer_differently(
        self, _name: str, cached: list[MetricsQuerySeries], tail: list[MetricsQuerySeries], formula: bool
    ) -> None:
        assert self._merge(cached, tail, formula=formula) is None


def _grid(counts: list[list[int]]) -> MetricsHistogramQueryResponse:
    return MetricsHistogramQueryResponse(
        results=None,
        times=["2026-09-19T11:00:00+00:00", "2026-09-19T11:01:00+00:00"],
        bounds=[0.5],
        counts=counts,
    )


class TestShadowDiff(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "identical",
                [_series({"pod": "a"}, {"2026-09-19T11:01:00+00:00": 2.0, "2026-09-19T11:02:00+00:00": 0.0})],
                [_series({"pod": "a"}, {"2026-09-19T11:01:00+00:00": 2.0, "2026-09-19T11:02:00+00:00": 0.0})],
                ShadowDiff(mismatch_points=0, max_rel_diff=0.0),
            ),
            (
                "one_value_differs",
                [_series({"pod": "a"}, {"2026-09-19T11:01:00+00:00": 8.0, "2026-09-19T11:02:00+00:00": 3.0})],
                [_series({"pod": "a"}, {"2026-09-19T11:01:00+00:00": 10.0, "2026-09-19T11:02:00+00:00": 3.0})],
                ShadowDiff(mismatch_points=1, max_rel_diff=0.2),
            ),
            (
                "full_run_picks_another_series",
                [_series({"pod": "a"}, {"2026-09-19T11:01:00+00:00": 1.0, "2026-09-19T11:02:00+00:00": 1.0})],
                [_series({"pod": "b"}, {"2026-09-19T11:01:00+00:00": 1.0, "2026-09-19T11:02:00+00:00": 1.0})],
                ShadowDiff(mismatch_points=4, max_rel_diff=1.0),
            ),
            (
                "gap_against_a_value",
                [_series({"pod": "a"}, {"2026-09-19T11:01:00+00:00": None})],
                [_series({"pod": "a"}, {"2026-09-19T11:01:00+00:00": 5.0})],
                ShadowDiff(mismatch_points=1, max_rel_diff=1.0),
            ),
        ]
    )
    def test_compare_series(
        self, _name: str, merged: list[MetricsQuerySeries], full: list[MetricsQuerySeries], expected: ShadowDiff
    ) -> None:
        assert compare_series(merged, full) == expected

    @parameterized.expand(
        [
            ("identical", [[1, 2], [3, 4]], [[1, 2], [3, 4]], ShadowDiff(mismatch_points=0, max_rel_diff=0.0)),
            ("late_sample", [[1, 2], [3, 3]], [[1, 2], [3, 4]], ShadowDiff(mismatch_points=1, max_rel_diff=0.25)),
        ]
    )
    def test_compare_grid(
        self, _name: str, merged: list[list[int]], full: list[list[int]], expected: ShadowDiff
    ) -> None:
        assert compare_grid(_grid(merged), _grid(full)) == expected


@contextmanager
def _dashboard_v2(enabled: bool) -> Iterator[MagicMock]:
    flags = {"metrics", SNUFFLE_API_FEATURE_FLAG, *(["dashboard-v2", "dashboard-v2-users"] if enabled else [])}
    with (
        patch("posthoganalytics.feature_enabled", side_effect=lambda flag, *args, **kwargs: flag in flags),
        patch("posthog.hogql_queries.query_runner.report_user_or_team_action") as report,
    ):
        yield report


def _refresh_modes(report: MagicMock) -> list[str | None]:
    return [call.args[1].get("tail_refresh") for call in report.call_args_list if call.args[0] == "query executed"]


@override_settings(METRICS_TAIL_REFRESH_VERIFY_RATE=0.0)
class TestMetricsTailRefresh(ClickhouseTestMixin, APIBaseTest):
    T0 = dt.datetime(2026, 9, 19, 12, 0, 20, tzinfo=dt.UTC)

    def setUp(self) -> None:
        super().setUp()
        truncate_metrics_tables()

    def _seed_gauges(self, start: dt.datetime, end: dt.datetime) -> None:
        minutes = int((end - start).total_seconds() // 60)
        samples = [start + dt.timedelta(minutes=i) for i in range(minutes)]
        seed_metric(
            team_id=self.team.pk,
            metric_name="queue_depth",
            points=[(t, 10.0 + i % 7) for i, t in enumerate(samples)],
            labels={"pod": "steady"},
        )

    def _seed_counter(self, start: dt.datetime, end: dt.datetime, pod: str, reset_at: dt.datetime | None) -> None:
        points: list[tuple[dt.datetime, float]] = []
        value = 1000.0
        t = start
        while t < end:
            value = 3.0 if reset_at is not None and reset_at <= t < reset_at + dt.timedelta(seconds=30) else value + 7
            points.append((t, value))
            t += dt.timedelta(seconds=30)
        seed_metric(
            team_id=self.team.pk,
            metric_name="requests_total",
            metric_type="sum",
            is_monotonic=True,
            points=points,
            labels={"pod": pod},
        )

    def _gauge_query(self, date_from: str) -> MetricsQuery:
        return MetricsQuery(
            clauses=[
                MetricsQueryClause(
                    name="a", metricName="queue_depth", aggregation="avg", groupBy=[MetricsQueryGroupBy(key="pod")]
                )
            ],
            dateRange=DateRange(date_from=date_from),
        )

    def _rate_query(self, date_from: str) -> MetricsQuery:
        return MetricsQuery(
            clauses=[
                MetricsQueryClause(
                    name="a",
                    metricName="requests_total",
                    aggregation="sum",
                    rangeFunction="rate",
                    groupBy=[MetricsQueryGroupBy(key="pod")],
                )
            ],
            dateRange=DateRange(date_from=date_from),
        )

    def _refresh_response(self, query: MetricsQuery) -> Any:
        return MetricsQueryRunner(query=query.model_copy(deep=True), team=self.team, user=self.user).run(
            execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS, dashboard_id=1
        )

    def _refresh(self, query: MetricsQuery) -> list[dict[str, Any]]:
        return [series.model_dump() for series in self._refresh_response(query).results]

    def _full(self, query: MetricsQuery) -> list[dict[str, Any]]:
        response = MetricsQueryRunner(query=query.model_copy(deep=True), team=self.team).calculate()
        return [series.model_dump() for series in response.results]

    @parameterized.expand([("1h", "-1h"), ("24h", "-24h"), ("7d", "-7d")])
    def test_tail_refresh_of_gauges_equals_a_full_run(self, _name: str, date_from: str) -> None:
        window_start = self.T0 - dt.timedelta(days=8)
        self._seed_gauges(window_start, self.T0)
        # Stops before the cut, so the tail does not return it.
        seed_metric(
            team_id=self.team.pk,
            metric_name="queue_depth",
            points=[(self.T0 - dt.timedelta(minutes=30 - i), 2.0) for i in range(5)],
            labels={"pod": "stopped"},
        )
        query = self._gauge_query(date_from)

        with _dashboard_v2(True) as report, time_machine.travel(self.T0, tick=False) as traveller:
            self._refresh(query)
            traveller.shift(dt.timedelta(minutes=3))
            self._seed_gauges(self.T0, self.T0 + dt.timedelta(minutes=3))
            # Starts after the cut, so only the tail returns it.
            seed_metric(
                team_id=self.team.pk,
                metric_name="queue_depth",
                points=[(self.T0 + dt.timedelta(minutes=1), 9.0)],
                labels={"pod": "new"},
            )
            spliced = self._refresh_response(query)
            merged = [series.model_dump() for series in spliced.results]
            full = self._full(query)

        assert _refresh_modes(report) == ["full", "spliced"]
        assert merged == full
        # Dashboard frames read their dates and interval from the range the response resolved.
        assert spliced.resolved_date_range is not None

    @parameterized.expand([("1h", "-1h"), ("24h", "-24h")])
    def test_tail_refresh_of_counter_rate_equals_a_full_run(self, _name: str, date_from: str) -> None:
        self._seed_counter(self.T0 - dt.timedelta(days=2), self.T0, "api", reset_at=None)
        # Resets right at the cut of the next refresh.
        self._seed_counter(
            self.T0 - dt.timedelta(days=2), self.T0, "worker", reset_at=self.T0 - dt.timedelta(minutes=5)
        )
        query = self._rate_query(date_from)

        with _dashboard_v2(True) as report, time_machine.travel(self.T0, tick=False) as traveller:
            self._refresh(query)
            traveller.shift(dt.timedelta(minutes=2))
            self._seed_counter(self.T0, self.T0 + dt.timedelta(minutes=2), "api", reset_at=None)
            merged = self._refresh(query)
            full = self._full(query)

        assert _refresh_modes(report) == ["full", "spliced"]
        assert merged == full

    @parameterized.expand(
        [
            ("flag_off", False, dt.timedelta(minutes=2), [None, None], None),
            ("entry_older_than_15_minutes", True, dt.timedelta(minutes=16), ["full", "full"], None),
            ("formula_over_a_grouped_clause", True, dt.timedelta(minutes=2), [None, None], "a * 2"),
        ]
    )
    def test_full_run(
        self, _name: str, flag_on: bool, shift: dt.timedelta, modes: list[str | None], formula: str | None
    ) -> None:
        self._seed_gauges(self.T0 - dt.timedelta(hours=2), self.T0)
        query = self._gauge_query("-1h").model_copy(update={"formula": formula})

        with _dashboard_v2(flag_on) as report, time_machine.travel(self.T0, tick=False) as traveller:
            self._refresh(query)
            traveller.shift(shift)
            self._seed_gauges(self.T0, self.T0 + shift)
            refreshed = self._refresh(query)
            full = self._full(query)

        assert _refresh_modes(report) == modes
        assert refreshed == full

    def test_new_interval_or_variable_value_runs_in_full(self) -> None:
        self._seed_gauges(self.T0 - dt.timedelta(hours=2), self.T0)
        query = self._gauge_query("-1h")

        with _dashboard_v2(True) as report, time_machine.travel(self.T0, tick=False) as traveller:
            self._refresh(query)
            traveller.shift(dt.timedelta(minutes=1))
            self._refresh(query.model_copy(update={"interval": "minute_5"}))

        assert _refresh_modes(report) == ["full", "full"]

    @override_settings(METRICS_TAIL_REFRESH_VERIFY_RATE=1.0)
    def test_shadow_checked_tail_refresh_reports_no_mismatch(self) -> None:
        self._seed_gauges(self.T0 - dt.timedelta(hours=2), self.T0)
        query = self._gauge_query("-1h")

        with _dashboard_v2(True) as report, time_machine.travel(self.T0, tick=False) as traveller:
            self._refresh(query)
            traveller.shift(dt.timedelta(minutes=2))
            self._seed_gauges(self.T0, self.T0 + dt.timedelta(minutes=2))
            self._refresh(query)

        shadow_keys = ("tail_refresh", "tail_shadow_checked", "tail_shadow_mismatch_points", "tail_shadow_max_rel_diff")
        shadow = [
            {key: call.args[1][key] for key in shadow_keys if key in call.args[1]}
            for call in report.call_args_list
            if call.args[0] == "query executed"
        ]
        assert shadow == [
            {"tail_refresh": "full", "tail_shadow_checked": False},
            {
                "tail_refresh": "spliced",
                "tail_shadow_checked": True,
                "tail_shadow_mismatch_points": 0,
                "tail_shadow_max_rel_diff": 0.0,
            },
        ]

    def test_tail_refresh_of_histogram_heatmap_equals_a_full_run(self) -> None:
        def seed(start: dt.datetime, end: dt.datetime) -> None:
            t = start
            i = 0
            while t < end:
                seed_metric(
                    team_id=self.team.pk,
                    metric_name="latency",
                    metric_type="histogram",
                    aggregation_temporality="delta",
                    histogram_bounds=[0.1, 0.5, 1.0],
                    histogram_counts=[i % 3, 1, i % 5, 2],
                    points=[(t, 0.0)],
                )
                t += dt.timedelta(minutes=1)
                i += 1

        seed(self.T0 - dt.timedelta(hours=2), self.T0)
        query = MetricsHistogramQuery(metricName="latency", dateRange=DateRange(date_from="-1h"))

        def refresh() -> dict[str, Any]:
            response = MetricsHistogramQueryRunner(
                query=query.model_copy(deep=True), team=self.team, user=self.user
            ).run(execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS, dashboard_id=1)
            return {"times": response.times, "bounds": response.bounds, "counts": response.counts}  # type: ignore[union-attr]

        with _dashboard_v2(True) as report, time_machine.travel(self.T0, tick=False) as traveller:
            refresh()
            traveller.shift(dt.timedelta(minutes=3))
            seed(self.T0, self.T0 + dt.timedelta(minutes=3))
            merged = refresh()
            full = MetricsHistogramQueryRunner(query=query.model_copy(deep=True), team=self.team).calculate()

        assert _refresh_modes(report) == ["full", "spliced"]
        assert merged == {"times": full.times, "bounds": full.bounds, "counts": full.counts}
