import json
from datetime import datetime
from typing import Any

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from django.test import override_settings

from parameterized import parameterized
from prometheus_client import REGISTRY

from posthog.schema import (
    ActionsNode,
    BreakdownFilter,
    ChartDisplayType,
    CompareFilter,
    DataWarehouseNode,
    DateRange,
    EventPropertyFilter,
    EventsNode,
    IntervalType,
    PersonPropertyFilter,
    PropertyOperator,
    TrendsFilter,
    TrendsQuery,
)

from posthog.clickhouse.client import sync_execute

from products.analytics_platform.backend.models.preaggregation_job import PreaggregationJob
from products.product_analytics.backend.facade.contracts import ClosedSeriesValues
from products.product_analytics.backend.hogql_queries.trends.series_values_precompute import (
    SOURCE_COUNT_SERIES_KEY,
    closed_series_values,
    execute_precomputed_trends,
)
from products.product_analytics.backend.hogql_queries.trends.trends_query_runner import TrendsQueryRunner

_NOW = "2024-01-15T12:00:00Z"

_PRO = EventPropertyFilter(key="plan", value="pro", operator=PropertyOperator.EXACT)


def _query(**overrides: Any) -> TrendsQuery:
    fields: dict[str, Any] = {
        "series": [EventsNode(event="signed_up", math="total")],
        "dateRange": DateRange(date_from="-7d"),
        "interval": IntervalType.DAY,
        "trendsFilter": TrendsFilter(display=ChartDisplayType.ACTIONS_LINE_GRAPH),
        **overrides,
    }
    return TrendsQuery(**fields)


def _fallbacks(reason: str) -> float:
    return REGISTRY.get_sample_value("series_values_precompute_fallback_total", {"reason": reason}) or 0.0


@override_settings(IN_UNIT_TESTING=True)
class TestSeriesValuesPrecompute(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        PreaggregationJob.objects.filter(team_id=self.team.pk).delete()
        sync_execute("SYSTEM STOP TTL MERGES sharded_series_values_preaggregated")
        self.addCleanup(sync_execute, "SYSTEM START TTL MERGES sharded_series_values_preaggregated")

    def _set_timezone(self, timezone: str) -> None:
        self.team.timezone = timezone
        self.team.save()

    def _seed(self) -> None:
        for timestamp, plan in (
            ("2024-01-09T05:00:00Z", "pro"),
            ("2024-01-10T15:00:00Z", "pro"),
            ("2024-01-10T15:40:00Z", "pro"),
            ("2024-01-12T23:30:00Z", "free"),
            ("2024-01-13T23:30:00Z", "pro"),
            ("2024-01-14T03:00:00Z", "pro"),
            ("2024-01-14T07:30:00Z", "pro"),
            ("2024-01-14T08:30:00Z", "pro"),
            ("2024-01-14T23:59:00Z", "free"),
            ("2024-01-15T01:00:00Z", "pro"),
            ("2024-01-15T11:00:00Z", "pro"),
        ):
            _create_event(
                team=self.team, event="signed_up", distinct_id="p1", timestamp=timestamp, properties={"plan": plan}
            )
        _create_event(team=self.team, event="other", distinct_id="p1", timestamp="2024-01-14T10:00:00Z")
        flush_persons_and_events()

    @parameterized.expand(
        [
            ("day_utc_query_filter", IntervalType.DAY, "UTC", "-7d", None, "query"),
            ("hour_utc_series_filter", IntervalType.HOUR, "UTC", "-3d", None, "series"),
            ("day_los_angeles_series_filter", IntervalType.DAY, "America/Los_Angeles", "-7d", None, "series"),
            ("hour_los_angeles_query_filter", IntervalType.HOUR, "America/Los_Angeles", "-3d", None, "query"),
            (
                "day_los_angeles_past_range",
                IntervalType.DAY,
                "America/Los_Angeles",
                "2024-01-09",
                "2024-01-13",
                "query",
            ),
            ("hour_utc_past_relative_range", IntervalType.HOUR, "UTC", "-3d", "-1d", "series"),
        ]
    )
    @time_machine.travel(_NOW, tick=False)
    def test_matches_live_trends(
        self,
        _name: str,
        interval: IntervalType,
        timezone: str,
        date_from: str,
        date_to: str | None,
        filter_level: str,
    ) -> None:
        self._set_timezone(timezone)
        self._seed()
        series = EventsNode(event="signed_up", math="total", properties=[_PRO] if filter_level == "series" else None)
        query = _query(
            series=[series],
            dateRange=DateRange(date_from=date_from, date_to=date_to),
            interval=interval,
            properties=[_PRO] if filter_level == "query" else None,
        )

        live = TrendsQueryRunner(team=self.team, query=query).calculate().results
        precomputed = execute_precomputed_trends(TrendsQueryRunner(team=self.team, query=query), run_inserts=True)

        assert json.dumps(precomputed) == json.dumps(live)
        assert PreaggregationJob.objects.filter(team_id=self.team.pk, status=PreaggregationJob.Status.READY).exists()

    @time_machine.travel(_NOW, tick=False)
    def test_rows_land_in_columns_and_second_call_reuses_jobs(self) -> None:
        self._seed()
        query = _query(properties=[_PRO])

        first = execute_precomputed_trends(TrendsQueryRunner(team=self.team, query=query), run_inserts=True)
        jobs = PreaggregationJob.objects.filter(team_id=self.team.pk).count()
        second = execute_precomputed_trends(TrendsQueryRunner(team=self.team, query=query), run_inserts=True)

        assert first is not None and first == second
        assert jobs > 0
        assert PreaggregationJob.objects.filter(team_id=self.team.pk).count() == jobs
        rows = sync_execute(
            """
            SELECT toString(time_window_start), series_key, value
            FROM series_values_preaggregated
            WHERE team_id = %(team_id)s
            ORDER BY time_window_start, series_key
            """,
            {"team_id": self.team.pk},
        )
        assert rows == [
            ("2024-01-09 05:00:00.000000", "", 1.0),
            ("2024-01-09 05:00:00.000000", SOURCE_COUNT_SERIES_KEY, 1.0),
            ("2024-01-10 15:00:00.000000", "", 2.0),
            ("2024-01-10 15:00:00.000000", SOURCE_COUNT_SERIES_KEY, 2.0),
            ("2024-01-12 23:00:00.000000", "", 0.0),
            ("2024-01-12 23:00:00.000000", SOURCE_COUNT_SERIES_KEY, 1.0),
            ("2024-01-13 23:00:00.000000", "", 1.0),
            ("2024-01-13 23:00:00.000000", SOURCE_COUNT_SERIES_KEY, 1.0),
            ("2024-01-14 03:00:00.000000", "", 1.0),
            ("2024-01-14 03:00:00.000000", SOURCE_COUNT_SERIES_KEY, 1.0),
            ("2024-01-14 07:00:00.000000", "", 1.0),
            ("2024-01-14 07:00:00.000000", SOURCE_COUNT_SERIES_KEY, 1.0),
            ("2024-01-14 08:00:00.000000", "", 1.0),
            ("2024-01-14 08:00:00.000000", SOURCE_COUNT_SERIES_KEY, 1.0),
            ("2024-01-14 23:00:00.000000", "", 0.0),
            ("2024-01-14 23:00:00.000000", SOURCE_COUNT_SERIES_KEY, 1.0),
        ]

    def test_day_built_before_late_events_settle_is_rebuilt(self) -> None:
        self._seed()
        query = _query()
        with time_machine.travel("2024-01-15T00:02:00Z", tick=False):
            execute_precomputed_trends(TrendsQueryRunner(team=self.team, query=query), run_inserts=True)
        _create_event(team=self.team, event="signed_up", distinct_id="p1", timestamp="2024-01-14T23:59:30Z")
        flush_persons_and_events()

        with time_machine.travel("2024-01-15T01:30:00Z", tick=False):
            live = TrendsQueryRunner(team=self.team, query=query).calculate().results
            precomputed = execute_precomputed_trends(TrendsQueryRunner(team=self.team, query=query), run_inserts=True)

        assert json.dumps(precomputed) == json.dumps(live)

    def _ready_jobs(self) -> dict[str, str]:
        return {
            f"{job.time_range_start:%m-%d}..{job.time_range_end:%m-%d}": str(job.id)
            for job in PreaggregationJob.objects.filter(team_id=self.team.pk, status=PreaggregationJob.Status.READY)
        }

    def _closed(self, *, verify: bool) -> ClosedSeriesValues:
        closed = closed_series_values(
            TrendsQueryRunner(team=self.team, query=_query(properties=[_PRO])), run_inserts=True, verify=verify
        )
        assert isinstance(closed, ClosedSeriesValues)
        return closed

    @parameterized.expand(
        [
            ("late_event_rebuilds_its_window", "UTC", "pro", ["01-08..01-11"], 1, 2),
            ("late_unmatched_event_rebuilds_its_window", "UTC", "free", ["01-08..01-11"], 1, 1),
            ("no_late_event_rebuilds_nothing", "UTC", None, [], 0, 1),
            ("no_late_event_off_utc_rebuilds_nothing", "America/Los_Angeles", None, [], 0, 0),
        ]
    )
    @time_machine.travel(_NOW, tick=False)
    def test_verified_read_rebuilds_only_changed_days(
        self,
        _name: str,
        timezone: str,
        late_plan: str | None,
        rebuilt_windows: list[str],
        stale_days: int,
        jan_9_value: int,
    ) -> None:
        self._set_timezone(timezone)
        self._seed()
        self._closed(verify=False)
        jobs_before = self._ready_jobs()
        if late_plan is not None:
            _create_event(
                team=self.team,
                event="signed_up",
                distinct_id="p1",
                timestamp="2024-01-09T10:00:00Z",
                properties={"plan": late_plan},
            )
            flush_persons_and_events()

        closed = self._closed(verify=True)

        jobs_after = self._ready_jobs()
        assert closed.verification is not None and closed.verification.stale_days == stale_days
        assert closed.values[datetime(2024, 1, 9)] == jan_9_value
        assert jobs_after.keys() == jobs_before.keys()
        assert sorted(window for window in jobs_before if jobs_after[window] != jobs_before[window]) == rebuilt_windows

    @time_machine.travel(_NOW, tick=False)
    def test_verification_runs_once_per_interval(self) -> None:
        self._seed()
        assert self._closed(verify=True).verification is not None
        _create_event(
            team=self.team,
            event="signed_up",
            distinct_id="p1",
            timestamp="2024-01-09T10:00:00Z",
            properties={"plan": "pro"},
        )
        flush_persons_and_events()

        closed = self._closed(verify=True)

        assert closed.verification is None
        assert closed.values[datetime(2024, 1, 9)] == 1

    @time_machine.travel(_NOW, tick=False)
    def test_cold_cache_without_inserts_returns_none(self) -> None:
        self._seed()

        result = execute_precomputed_trends(TrendsQueryRunner(team=self.team, query=_query()), run_inserts=False)

        assert result is None
        assert not PreaggregationJob.objects.filter(team_id=self.team.pk).exists()

    @parameterized.expand(
        [
            ("series_count", {"series": [EventsNode(event="a"), EventsNode(event="b")]}, None),
            ("actions_node", {"series": [ActionsNode(id=1)]}, None),
            (
                "data_warehouse_node",
                {
                    "series": [
                        DataWarehouseNode(
                            id="t", table_name="t", id_field="id", distinct_id_field="id", timestamp_field="ts"
                        )
                    ]
                },
                None,
            ),
            ("math", {"series": [EventsNode(event="signed_up", math="dau")]}, None),
            ("breakdown", {"breakdownFilter": BreakdownFilter(breakdown="plan", breakdown_type="event")}, None),
            ("compare", {"compareFilter": CompareFilter(compare=True)}, None),
            ("formula", {"trendsFilter": TrendsFilter(formula="A * 2")}, None),
            ("display", {"trendsFilter": TrendsFilter(display=ChartDisplayType.ACTIONS_LINE_GRAPH_CUMULATIVE)}, None),
            ("smoothing", {"trendsFilter": TrendsFilter(smoothingIntervals=7)}, None),
            ("sampling", {"samplingFactor": 0.1}, None),
            ("interval", {"interval": IntervalType.WEEK}, None),
            ("test_account_filters", {"filterTestAccounts": True}, None),
            ("property_type", {"properties": [PersonPropertyFilter(key="email", value="x", operator="exact")]}, None),
            ("timezone", {}, "Asia/Kolkata"),
            (
                "dst_transition",
                {"interval": IntervalType.HOUR, "dateRange": DateRange(date_from="2023-11-04", date_to="2023-11-06")},
                "America/New_York",
            ),
            (
                "dst_transition",
                {"interval": IntervalType.HOUR, "dateRange": DateRange(date_from="2023-10-01", date_to="2024-04-01")},
                "America/New_York",
            ),
            ("nothing_closed", {"dateRange": DateRange(date_from="dStart")}, None),
            ("unaligned_range", {"dateRange": DateRange(date_from="-24h")}, None),
            (
                "unaligned_range",
                {
                    "interval": IntervalType.HOUR,
                    "dateRange": DateRange(date_from="2024-01-10", date_to="2024-01-10T15:20:00"),
                },
                None,
            ),
            ("date_range_too_long", {"dateRange": DateRange(date_from="2022-01-01", date_to="2024-01-10")}, None),
        ]
    )
    @time_machine.travel(_NOW, tick=False)
    def test_refuses_unsupported_shapes(self, reason: str, overrides: dict[str, Any], timezone: str | None) -> None:
        if timezone is not None:
            self._set_timezone(timezone)
        before = _fallbacks(reason)

        result = execute_precomputed_trends(
            TrendsQueryRunner(team=self.team, query=_query(**overrides)), run_inserts=True
        )

        assert result is None
        assert _fallbacks(reason) == before + 1
        assert not PreaggregationJob.objects.filter(team_id=self.team.pk).exists()

    @time_machine.travel(_NOW, tick=False)
    def test_refuses_teams_with_property_access_rules(self) -> None:
        before = _fallbacks("property_access_rules")

        with patch(
            "products.product_analytics.backend.hogql_queries.trends.series_values_precompute.team_has_property_access_rules",
            return_value=True,
        ):
            result = execute_precomputed_trends(TrendsQueryRunner(team=self.team, query=_query()), run_inserts=True)

        assert result is None
        assert _fallbacks("property_access_rules") == before + 1
