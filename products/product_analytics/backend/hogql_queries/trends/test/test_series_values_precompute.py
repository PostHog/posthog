import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from django.test import override_settings

from parameterized import parameterized

from posthog.schema import (
    ActionsNode,
    BreakdownFilter,
    ChartDisplayType,
    CohortPropertyFilter,
    CompareFilter,
    DataWarehouseNode,
    DateRange,
    EventPropertyFilter,
    EventsNode,
    HogQLQueryModifiers,
    IntervalType,
    PersonPropertyFilter,
    PersonsOnEventsMode,
    PropertyOperator,
    TrendsFilter,
    TrendsQuery,
)

from posthog.clickhouse.client import sync_execute

from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import (
    LazyComputationResult,
    ServedWindow,
)
from products.analytics_platform.backend.models.preaggregation_job import PreaggregationJob
from products.product_analytics.backend.facade.contracts import (
    PrecomputedSeriesValues,
    SeriesValuesBlocker,
    SeriesValuesFeature,
    SeriesValuesUnavailable,
)
from products.product_analytics.backend.hogql_queries.trends.series_values_precompute import (
    execute_precomputed_trends,
    precomputed_series_values,
)
from products.product_analytics.backend.hogql_queries.trends.trends_query_runner import TrendsQueryRunner

_NOW = "2024-01-15T12:00:00Z"

_PRO = EventPropertyFilter(key="plan", value="pro", operator=PropertyOperator.EXACT)

_TEST_ACCOUNT_FILTERS: dict[str, dict[str, Any]] = {
    "test_account_event": {"key": "plan", "value": "pro", "operator": "exact", "type": "event"},
    "test_account_person": {"key": "tier", "value": "pro", "operator": "exact", "type": "person"},
}


def _query(**overrides: Any) -> TrendsQuery:
    fields: dict[str, Any] = {
        "series": [EventsNode(event="signed_up", math="total")],
        "dateRange": DateRange(date_from="-7d"),
        "interval": IntervalType.DAY,
        "trendsFilter": TrendsFilter(display=ChartDisplayType.ACTIONS_LINE_GRAPH),
        **overrides,
    }
    return TrendsQuery(**fields)


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

    def _set_test_account_filters(self, filters: list[dict[str, Any]], persons_mode: PersonsOnEventsMode) -> None:
        self.team.test_account_filters = filters
        self.team.modifiers = {"personsOnEventsMode": persons_mode.value}
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
                team=self.team,
                event="signed_up",
                distinct_id="p1",
                timestamp=timestamp,
                properties={"plan": plan},
                person_properties={"tier": plan},
            )
        _create_event(team=self.team, event="other", distinct_id="p1", timestamp="2024-01-14T10:00:00Z")
        flush_persons_and_events()

    @parameterized.expand(
        [
            ("day_utc_query_filter", IntervalType.DAY, "UTC", "-7d", None, "query"),
            ("hour_utc_series_filter", IntervalType.HOUR, "UTC", "-3d", None, "series"),
            ("day_los_angeles_series_filter", IntervalType.DAY, "America/Los_Angeles", "-7d", None, "series"),
            ("hour_los_angeles_query_filter", IntervalType.HOUR, "America/Los_Angeles", "-3d", None, "query"),
            ("day_tokyo_series_filter", IntervalType.DAY, "Asia/Tokyo", "-7d", None, "series"),
            (
                "day_los_angeles_past_range",
                IntervalType.DAY,
                "America/Los_Angeles",
                "2024-01-09",
                "2024-01-13",
                "query",
            ),
            ("hour_utc_past_relative_range", IntervalType.HOUR, "UTC", "-3d", "-1d", "series"),
            ("day_utc_event_test_account_filter", IntervalType.DAY, "UTC", "-7d", None, "test_account_event"),
            (
                "hour_los_angeles_person_test_account_filter",
                IntervalType.HOUR,
                "America/Los_Angeles",
                "-3d",
                None,
                "test_account_person",
            ),
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
        if filter_level in _TEST_ACCOUNT_FILTERS:
            self._set_test_account_filters(
                [_TEST_ACCOUNT_FILTERS[filter_level]], PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS
            )
        series = EventsNode(event="signed_up", math="total", properties=[_PRO] if filter_level == "series" else None)
        query = _query(
            series=[series],
            dateRange=DateRange(date_from=date_from, date_to=date_to),
            interval=interval,
            properties=[_PRO] if filter_level == "query" else None,
            filterTestAccounts=filter_level in _TEST_ACCOUNT_FILTERS,
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
            SELECT toString(time_window_start), toString(time_window_end), series_key, value
            FROM series_values_preaggregated
            WHERE team_id = %(team_id)s
            ORDER BY time_window_start
            """,
            {"team_id": self.team.pk},
        )
        assert rows == [
            ("2024-01-09 05:00:00.000000", "2024-01-09 06:00:00.000000", "", 1.0),
            ("2024-01-10 15:00:00.000000", "2024-01-10 16:00:00.000000", "", 2.0),
            ("2024-01-13 23:00:00.000000", "2024-01-14 00:00:00.000000", "", 1.0),
            ("2024-01-14 03:00:00.000000", "2024-01-14 04:00:00.000000", "", 1.0),
            ("2024-01-14 07:00:00.000000", "2024-01-14 08:00:00.000000", "", 1.0),
            ("2024-01-14 08:00:00.000000", "2024-01-14 09:00:00.000000", "", 1.0),
        ]

    @time_machine.travel(_NOW, tick=False)
    def test_a_row_without_a_window_end_is_not_read(self) -> None:
        self._seed()
        query = _query(properties=[_PRO])
        before = execute_precomputed_trends(TrendsQueryRunner(team=self.team, query=query), run_inserts=True)
        job = PreaggregationJob.objects.get(
            team_id=self.team.pk,
            time_range_start__lte="2024-01-14T00:00:00Z",
            time_range_end__gt="2024-01-14T00:00:00Z",
        )
        sync_execute(
            """
            INSERT INTO sharded_series_values_preaggregated (team_id, job_id, time_window_start, series_key, value)
            VALUES (%(team_id)s, %(job_id)s, '2024-01-14 10:00:00', '', 5)
            """,
            {"team_id": self.team.pk, "job_id": str(job.id)},
        )

        after = execute_precomputed_trends(TrendsQueryRunner(team=self.team, query=query), run_inserts=True)

        assert before is not None and after == before

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

    @time_machine.travel(_NOW, tick=False)
    def test_a_range_that_the_returned_jobs_leave_uncovered_is_not_served(self) -> None:
        result = LazyComputationResult(
            ready=True,
            job_ids=[uuid4()],
            served_windows=(
                ServedWindow(
                    start=datetime(2024, 1, 8, tzinfo=UTC), end=datetime(2024, 1, 10, tzinfo=UTC), computed_at=None
                ),
            ),
        )
        with patch(
            "products.product_analytics.backend.hogql_queries.trends.series_values_precompute.ensure_precomputed",
            return_value=result,
        ):
            precomputed = precomputed_series_values(TrendsQueryRunner(team=self.team, query=_query()), run_inserts=True)

        assert precomputed == SeriesValuesUnavailable(reason=SeriesValuesBlocker.NOT_READY)

    @time_machine.travel(_NOW, tick=False)
    def test_cold_cache_without_inserts_returns_none(self) -> None:
        self._seed()

        result = execute_precomputed_trends(TrendsQueryRunner(team=self.team, query=_query()), run_inserts=False)

        assert result is None
        assert not PreaggregationJob.objects.filter(team_id=self.team.pk).exists()

    @parameterized.expand(
        [
            (SeriesValuesFeature.ACTION_SERIES, {"series": [ActionsNode(id=1)]}, None),
            (
                SeriesValuesFeature.DATA_WAREHOUSE_SERIES,
                {
                    "series": [
                        DataWarehouseNode(
                            id="t", table_name="t", id_field="id", distinct_id_field="id", timestamp_field="ts"
                        )
                    ]
                },
                None,
            ),
            (SeriesValuesFeature.OTHER_MATH, {"series": [EventsNode(event="signed_up", math="dau")]}, None),
            (
                SeriesValuesFeature.BREAKDOWN,
                {"breakdownFilter": BreakdownFilter(breakdown="plan", breakdown_type="event")},
                None,
            ),
            (SeriesValuesFeature.COMPARE, {"compareFilter": CompareFilter(compare=True)}, None),
            (SeriesValuesFeature.FORMULA, {"trendsFilter": TrendsFilter(formula="A * 2")}, None),
            (
                SeriesValuesFeature.OTHER_DISPLAY,
                {"trendsFilter": TrendsFilter(display=ChartDisplayType.ACTIONS_LINE_GRAPH_CUMULATIVE)},
                None,
            ),
            (SeriesValuesFeature.SMOOTHING, {"trendsFilter": TrendsFilter(smoothingIntervals=7)}, None),
            (SeriesValuesFeature.ALL_TIME_RANGE, {"dateRange": DateRange(date_from="all")}, None),
            (SeriesValuesFeature.SAMPLING, {"samplingFactor": 0.1}, None),
            (
                SeriesValuesFeature.QUERY_MODIFIERS,
                {"modifiers": HogQLQueryModifiers(convertToProjectTimezone=False)},
                None,
            ),
            (SeriesValuesFeature.OTHER_INTERVAL, {"interval": IntervalType.WEEK}, None),
            (SeriesValuesFeature.OTHER_PROPERTY_TYPE, {"properties": [CohortPropertyFilter(key="id", value=1)]}, None),
            (SeriesValuesBlocker.TIMEZONE, {}, "Asia/Kolkata"),
            (
                SeriesValuesBlocker.DST_TRANSITION,
                {"interval": IntervalType.HOUR, "dateRange": DateRange(date_from="2023-11-04", date_to="2023-11-06")},
                "America/New_York",
            ),
            (
                SeriesValuesBlocker.DST_TRANSITION,
                {"interval": IntervalType.HOUR, "dateRange": DateRange(date_from="2023-10-01", date_to="2024-04-01")},
                "America/New_York",
            ),
            (SeriesValuesBlocker.NO_FINISHED_BUCKET, {"dateRange": DateRange(date_from="dStart")}, None),
            (SeriesValuesBlocker.PARTIAL_BUCKET, {"dateRange": DateRange(date_from="-24h")}, None),
            (
                SeriesValuesBlocker.PARTIAL_BUCKET,
                {
                    "interval": IntervalType.HOUR,
                    "dateRange": DateRange(date_from="2024-01-10", date_to="2024-01-10T15:20:00"),
                },
                None,
            ),
            (
                SeriesValuesBlocker.DATE_RANGE_TOO_LONG,
                {"dateRange": DateRange(date_from="2022-01-01", date_to="2024-01-10")},
                None,
            ),
        ]
    )
    @time_machine.travel(_NOW, tick=False)
    def test_refuses_unsupported_shapes(
        self, reason: SeriesValuesFeature | SeriesValuesBlocker, overrides: dict[str, Any], timezone: str | None
    ) -> None:
        if timezone is not None:
            self._set_timezone(timezone)

        precomputed = precomputed_series_values(
            TrendsQueryRunner(team=self.team, query=_query(**overrides)), run_inserts=True
        )

        assert precomputed == SeriesValuesUnavailable(reason=reason)
        assert not PreaggregationJob.objects.filter(team_id=self.team.pk).exists()

    @parameterized.expand([("second_series", 1), ("third_series", 2)])
    @time_machine.travel(_NOW, tick=False)
    def test_a_series_of_a_multi_series_query_matches_live(self, _name: str, series_index: int) -> None:
        self._seed()
        query = _query(
            series=[
                EventsNode(event="signed_up", math="dau"),
                EventsNode(event="signed_up", math="total", properties=[_PRO]),
                EventsNode(event="other", math="total"),
            ]
        )
        [live_series] = [
            row
            for row in TrendsQueryRunner(team=self.team, query=query).calculate().results
            if row["order"] == series_index
        ]

        precomputed = precomputed_series_values(
            TrendsQueryRunner(team=self.team, query=query), series_index=series_index, run_inserts=True
        )

        assert isinstance(precomputed, PrecomputedSeriesValues)
        live_by_day = {
            datetime.fromisoformat(day): value for day, value in zip(live_series["days"], live_series["data"])
        }
        assert precomputed.values == {day: live_by_day[day] for day in precomputed.values}
        assert sum(precomputed.values.values()) > 0
        assert SeriesValuesFeature.MULTIPLE_SERIES in precomputed.features

    @time_machine.travel(_NOW, tick=False)
    def test_refuses_a_series_the_query_does_not_have(self) -> None:
        precomputed = precomputed_series_values(
            TrendsQueryRunner(team=self.team, query=_query()), series_index=1, run_inserts=True
        )

        assert precomputed == SeriesValuesUnavailable(reason=SeriesValuesBlocker.SERIES_NOT_FOUND)

    @time_machine.travel(_NOW, tick=False)
    def test_insight_path_leaves_multi_series_queries_to_the_live_runner(self) -> None:
        query = _query(series=[EventsNode(event="signed_up"), EventsNode(event="other")])

        result = execute_precomputed_trends(TrendsQueryRunner(team=self.team, query=query), run_inserts=True)

        assert result is None
        assert not PreaggregationJob.objects.filter(team_id=self.team.pk).exists()

    @parameterized.expand(
        [
            (
                "cohort_test_account_filter",
                PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS,
                [{"key": "id", "value": 1, "type": "cohort"}],
                None,
                SeriesValuesFeature.OTHER_TEST_ACCOUNT_FILTER_TYPE,
            ),
            (
                "person_test_account_filter_with_joined_persons",
                PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED,
                [_TEST_ACCOUNT_FILTERS["test_account_person"]],
                None,
                SeriesValuesFeature.OTHER_TEST_ACCOUNT_FILTER_TYPE,
            ),
            (
                "virtual_person_test_account_filter",
                PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS,
                [{"key": "$virt_revenue", "value": 100, "operator": "gt", "type": "person"}],
                None,
                SeriesValuesFeature.OTHER_TEST_ACCOUNT_FILTER_TYPE,
            ),
            (
                "person_query_filter_with_joined_persons",
                PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED,
                [],
                [PersonPropertyFilter(key="tier", value="pro", operator=PropertyOperator.EXACT)],
                SeriesValuesFeature.OTHER_PROPERTY_TYPE,
            ),
        ]
    )
    @time_machine.travel(_NOW, tick=False)
    def test_refuses_filters_whose_value_can_change_after_ingestion(
        self,
        _name: str,
        persons_mode: PersonsOnEventsMode,
        test_account_filters: list[dict[str, Any]],
        properties: list[PersonPropertyFilter] | None,
        reason: SeriesValuesFeature,
    ) -> None:
        self._set_test_account_filters(test_account_filters, persons_mode)
        query = _query(filterTestAccounts=True, properties=properties)

        precomputed = precomputed_series_values(TrendsQueryRunner(team=self.team, query=query), run_inserts=True)

        assert precomputed == SeriesValuesUnavailable(reason=reason)
        assert not PreaggregationJob.objects.filter(team_id=self.team.pk).exists()

    @time_machine.travel(_NOW, tick=False)
    def test_reports_test_account_and_person_filters_as_features(self) -> None:
        self._set_test_account_filters(
            [_TEST_ACCOUNT_FILTERS["test_account_person"]], PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS
        )
        query = _query(filterTestAccounts=True)

        precomputed = precomputed_series_values(TrendsQueryRunner(team=self.team, query=query), run_inserts=True)

        assert isinstance(precomputed, PrecomputedSeriesValues)
        assert precomputed.features == {
            SeriesValuesFeature.TEST_ACCOUNT_FILTERS,
            SeriesValuesFeature.PERSON_PROPERTY_FILTERS,
        }

    @parameterized.expand(
        [
            ("no_filter", None, frozenset()),
            ("event_property_filter", [_PRO], frozenset({SeriesValuesFeature.EVENT_PROPERTY_FILTERS})),
        ]
    )
    @time_machine.travel(_NOW, tick=False)
    def test_reports_the_features_a_query_uses(
        self, _name: str, properties: list[EventPropertyFilter] | None, features: frozenset[SeriesValuesFeature]
    ) -> None:
        query = _query(properties=properties)

        precomputed = precomputed_series_values(TrendsQueryRunner(team=self.team, query=query), run_inserts=True)

        assert isinstance(precomputed, PrecomputedSeriesValues)
        assert precomputed.features == features

    @time_machine.travel(_NOW, tick=False)
    def test_refuses_teams_with_property_access_rules(self) -> None:
        with patch(
            "products.product_analytics.backend.hogql_queries.trends.series_values_precompute.team_has_property_access_rules",
            return_value=True,
        ):
            precomputed = precomputed_series_values(TrendsQueryRunner(team=self.team, query=_query()), run_inserts=True)

        assert precomputed == SeriesValuesUnavailable(reason=SeriesValuesBlocker.PROPERTY_ACCESS_RULES)
