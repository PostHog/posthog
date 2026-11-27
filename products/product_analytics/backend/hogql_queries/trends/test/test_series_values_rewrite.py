import re
import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from django.test import override_settings

from parameterized import parameterized

from posthog.schema import (
    BreakdownFilter,
    ChartDisplayType,
    CompareFilter,
    DateRange,
    EventPropertyFilter,
    EventsNode,
    HogQLPropertyFilter,
    HogQLQueryModifiers,
    IntervalType,
    PersonPropertyFilter,
    PropertyOperator,
    TrendsFilter,
    TrendsQuery,
)

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import to_printed_hogql

from posthog.clickhouse.client import sync_execute

from products.actions.backend.facade.testing import create_action
from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import (
    LazyComputationResult,
    ServedWindow,
)
from products.analytics_platform.backend.models.preaggregation_job import PreaggregationJob
from products.product_analytics.backend.facade.contracts import (
    PrecomputedSeriesValues,
    SeriesValuesBlocker as Blocker,
    SeriesValuesFeature as Feature,
    SeriesValuesUnavailable,
)
from products.product_analytics.backend.hogql_queries.trends.series_values_rewrite import (
    SeriesValuesRewrite,
    precomputed_series_values,
    rewriting_series_values,
)
from products.product_analytics.backend.hogql_queries.trends.trends_query_runner import TrendsQueryRunner

_NOW = "2024-01-15T12:00:00Z"
_MODULE = "products.product_analytics.backend.hogql_queries.trends.series_values_rewrite"

_PRO = EventPropertyFilter(key="plan", value="pro", operator=PropertyOperator.EXACT)
_COUNT = EventsNode(event="signed_up", math="total")
_OTHER = EventsNode(event="other", math="total")
_UNIQUE_USERS = EventsNode(event="signed_up", math="dau")
_HOURS = {"interval": IntervalType.HOUR, "dateRange": DateRange(date_from="-3d")}


def _query(**overrides: Any) -> TrendsQuery:
    fields: dict[str, Any] = {
        "series": [_COUNT],
        "dateRange": DateRange(date_from="-7d"),
        "interval": IntervalType.DAY,
        **overrides,
    }
    return TrendsQuery(**fields)


@override_settings(IN_UNIT_TESTING=True)
class TestSeriesValuesRewrite(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        PreaggregationJob.objects.filter(team_id=self.team.pk).delete()
        sync_execute("SYSTEM STOP TTL MERGES sharded_series_values_preaggregated")
        self.addCleanup(sync_execute, "SYSTEM START TTL MERGES sharded_series_values_preaggregated")

    def _set_up_team(self, timezone: str = "UTC") -> None:
        self.team.timezone = timezone
        self.team.test_account_filters = [{"key": "plan", "value": "free", "operator": "is_not", "type": "event"}]
        self.team.save()

    def _seed(self) -> None:
        for timestamp, plan in (
            ("2023-11-05T05:30:00Z", "pro"),
            ("2023-11-05T06:30:00Z", "pro"),
            ("2023-11-05T07:30:00Z", "pro"),
            ("2024-01-02T05:00:00Z", "pro"),
            ("2024-01-05T15:00:00Z", "pro"),
            ("2024-01-09T05:00:00Z", "pro"),
            ("2024-01-10T15:00:00Z", "pro"),
            ("2024-01-10T15:40:00Z", "pro"),
            ("2024-01-12T23:30:00Z", "free"),
            ("2024-01-13T23:30:00Z", "pro"),
            ("2024-01-14T03:00:00Z", "pro"),
            ("2024-01-14T07:30:00Z", "pro"),
            ("2024-01-14T07:59:59.500000Z", "pro"),
            ("2024-01-14T08:30:00Z", "pro"),
            ("2024-01-14T23:59:00Z", "free"),
            ("2024-01-15T01:00:00Z", "pro"),
            ("2024-01-15T11:00:00Z", "pro"),
        ):
            _create_event(
                team=self.team, event="signed_up", distinct_id="p1", timestamp=timestamp, properties={"plan": plan}
            )
        for timestamp in (
            "2024-01-09T10:00:00Z",
            "2024-01-13T10:00:00Z",
            "2024-01-14T10:00:00Z",
            "2024-01-15T02:00:00Z",
        ):
            _create_event(team=self.team, event="other", distinct_id="p2", timestamp=timestamp)
        flush_persons_and_events()

    def _printed(self, query: Any) -> str:
        return re.sub(r"'[0-9a-f-]{36}'", "'<job id>'", to_printed_hogql(query, self.team))

    @pytest.mark.usefixtures("unittest_snapshot")
    @time_machine.travel(_NOW, tick=False)
    def test_the_count_query_as_written_served_and_stored_only(self) -> None:
        written = """
            SELECT count() AS total, toStartOfDay(timestamp) AS day_start
            FROM events
            WHERE and(
                timestamp >= toStartOfInterval(assumeNotNull(toDateTime('2024-01-08 00:00:00')), toIntervalDay(1)),
                timestamp <= assumeNotNull(toDateTime('2024-01-15 23:59:59')),
                event = 'signed_up',
                properties.plan = 'pro'
            )
            GROUP BY day_start
        """
        printed = {"as written": self._printed(parse_select(written))}
        for mode in ("serve", "stored_only"):
            context = HogQLContext(team_id=self.team.pk, team=self.team, enable_select_queries=True)
            rewritten = SeriesValuesRewrite(mode=mode).rewrite(parse_select(written), context)
            printed[mode.replace("_", " ")] = self._printed(rewritten)

        assert "\n\n".join(f"-- {name}\n{query}" for name, query in printed.items()) == self.snapshot

    def _live(self, query: TrendsQuery) -> list[Any]:
        return TrendsQueryRunner(team=self.team, query=query).calculate().results

    def _served(self, query: TrendsQuery) -> tuple[list[Any], SeriesValuesRewrite]:
        with rewriting_series_values("serve") as request:
            return TrendsQueryRunner(team=self.team, query=query).calculate().results, request

    @parameterized.expand(
        [
            ("day_utc", {}, "UTC", 1),
            ("day_utc_query_filter", {"properties": [_PRO]}, "UTC", 1),
            (
                "hour_utc_series_filter",
                {**_HOURS, "series": [_COUNT.model_copy(update={"properties": [_PRO]})]},
                "UTC",
                1,
            ),
            ("day_los_angeles", {}, "America/Los_Angeles", 1),
            ("hour_los_angeles", {**_HOURS, "properties": [_PRO]}, "America/Los_Angeles", 1),
            ("day_tokyo", {"properties": [_PRO]}, "Asia/Tokyo", 1),
            ("hour_tokyo", _HOURS, "Asia/Tokyo", 1),
            (
                "hours_across_a_clock_change",
                {"interval": IntervalType.HOUR, "dateRange": DateRange(date_from="2023-11-04", date_to="2023-11-06")},
                "America/New_York",
                1,
            ),
            (
                "day_los_angeles_past_range",
                {"dateRange": DateRange(date_from="2024-01-09", date_to="2024-01-13")},
                "America/Los_Angeles",
                1,
            ),
            (
                "hour_utc_range_that_ends_inside_an_hour",
                {
                    "interval": IntervalType.HOUR,
                    "dateRange": DateRange(date_from="2024-01-10", date_to="2024-01-10T15:20:00"),
                },
                "UTC",
                1,
            ),
            ("all_events", {"series": [EventsNode(event=None, math="total")]}, "UTC", 1),
            ("test_account_filters", {"filterTestAccounts": True}, "UTC", 1),
            ("formula", {"series": [_COUNT, _OTHER], "trendsFilter": TrendsFilter(formula="A/B")}, "UTC", 2),
            ("compare", {"compareFilter": CompareFilter(compare=True)}, "UTC", 2),
            ("smoothing", {"trendsFilter": TrendsFilter(smoothingIntervals=3)}, "UTC", 1),
            ("maximum_of_the_count", {"series": [EventsNode(event="signed_up", math="max")]}, "America/Los_Angeles", 1),
            (
                "cumulative",
                {"trendsFilter": TrendsFilter(display=ChartDisplayType.ACTIONS_LINE_GRAPH_CUMULATIVE)},
                "UTC",
                1,
            ),
        ]
    )
    @time_machine.travel(_NOW, tick=False)
    def test_served_trends_match_live(
        self, _name: str, overrides: dict[str, Any], timezone: str, count_queries: int
    ) -> None:
        self._set_up_team(timezone)
        self._seed()
        query = _query(**overrides)

        live = self._live(query)
        served, request = self._served(query)

        assert json.dumps(served, default=str) == json.dumps(live, default=str)
        assert (len(request.built), request.declined) == (count_queries, [])

    @time_machine.travel(_NOW, tick=False)
    def test_a_declined_series_stays_live_beside_a_served_one(self) -> None:
        self._set_up_team()
        self._seed()
        query = _query(series=[_COUNT, _UNIQUE_USERS])

        live = self._live(query)
        served, request = self._served(query)

        assert json.dumps(served, default=str) == json.dumps(live, default=str)
        assert (len(request.built), request.declined) == (1, [Blocker.OTHER_AGGREGATE])

    @parameterized.expand(
        [
            ("day_utc", {}, "UTC", "2024-01-14", {Feature.EVENT_NAME}),
            (
                "day_los_angeles_filter",
                {"properties": [_PRO]},
                "America/Los_Angeles",
                "2024-01-13",
                {Feature.EVENT_NAME, Feature.EVENT_PROPERTY_FILTERS},
            ),
            (
                "day_tokyo_all_events",
                {"series": [EventsNode(event=None, math="total")]},
                "Asia/Tokyo",
                "2024-01-14",
                set(),
            ),
            ("hour_los_angeles", _HOURS, "America/Los_Angeles", "2024-01-14 15:00:00", {Feature.EVENT_NAME}),
        ]
    )
    @time_machine.travel(_NOW, tick=False)
    def test_stored_values_cover_the_finished_buckets_without_reading_events(
        self, _name: str, overrides: dict[str, Any], timezone: str, last_finished: str, features: set[Feature]
    ) -> None:
        self._set_up_team(timezone)
        self._seed()
        query = _query(**overrides)
        live = self._live(query)[0]

        with self.capture_select_queries() as selects:
            precomputed = precomputed_series_values(TrendsQueryRunner(team=self.team, query=query))

        assert precomputed == PrecomputedSeriesValues(
            values={
                datetime.fromisoformat(day): value
                for day, value in zip(live["days"], live["data"])
                if day <= last_finished
            },
            freshly_built=True,
            features=frozenset(features),
        )
        assert not [select for select in selects if "events" in select]

    @parameterized.expand(
        [
            (Blocker.OTHER_AGGREGATE, {"series": [_UNIQUE_USERS]}, "UTC"),
            (Blocker.MULTIPLE_SERIES, {"series": [_COUNT, _OTHER]}, "UTC"),
            (Blocker.BREAKDOWN, {"breakdownFilter": BreakdownFilter(breakdown="plan", breakdown_type="event")}, "UTC"),
            (Blocker.OTHER_INTERVAL, {"interval": IntervalType.WEEK, "dateRange": DateRange(date_from="-30d")}, "UTC"),
            (
                Blocker.UNSUPPORTED_FILTER,
                {"properties": [PersonPropertyFilter(key="email", value="x", operator=PropertyOperator.EXACT)]},
                "UTC",
            ),
            (
                Blocker.UNSUPPORTED_FILTER,
                {"properties": [EventPropertyFilter(key="plan", value="-7d", operator=PropertyOperator.IS_DATE_AFTER)]},
                "UTC",
            ),
            (
                Blocker.UNSUPPORTED_FILTER,
                {"properties": [HogQLPropertyFilter(key="matchesAction('Signed up')"), _PRO]},
                "UTC",
            ),
            (
                Blocker.UNSUPPORTED_FILTER,
                {"properties": [HogQLPropertyFilter(key="properties.plan = <HogQLQuery query='SELECT 1' />")]},
                "UTC",
            ),
            (
                Blocker.UNSUPPORTED_FILTER,
                {"series": [EventsNode(event="$feature_flag_called", math="total")]},
                "UTC",
            ),
            (Blocker.SAMPLING, {"samplingFactor": 0.1}, "UTC"),
            (Blocker.NO_COUNT_QUERY, {"trendsFilter": TrendsFilter(display=ChartDisplayType.BOLD_NUMBER)}, "UTC"),
            (Blocker.TIMEZONE, {}, "Asia/Kolkata"),
            (
                Blocker.PARTIAL_HOUR,
                {
                    "interval": IntervalType.HOUR,
                    "dateRange": DateRange(date_from="2024-01-10T15:20:00", date_to="2024-01-12", explicitDate=True),
                },
                "UTC",
            ),
            (Blocker.ALL_TIME_RANGE, {"dateRange": DateRange(date_from="all")}, "UTC"),
            (Blocker.NO_FINISHED_BUCKET, {"dateRange": DateRange(date_from="dStart")}, "UTC"),
            (
                Blocker.DATE_RANGE_TOO_LONG,
                {"dateRange": DateRange(date_from="2022-01-01", date_to="2024-01-10")},
                "UTC",
            ),
        ]
    )
    @time_machine.travel(_NOW, tick=False)
    def test_a_query_it_cannot_answer_is_declined_before_anything_runs(
        self, reason: Blocker, overrides: dict[str, Any], timezone: str
    ) -> None:
        self._set_up_team(timezone)
        create_action(team=self.team, name="Signed up", steps_json=[{"event": "signed_up"}])

        with self.capture_select_queries() as selects:
            precomputed = precomputed_series_values(TrendsQueryRunner(team=self.team, query=_query(**overrides)))

        assert precomputed == SeriesValuesUnavailable(reason=reason)
        assert selects == []
        assert not PreaggregationJob.objects.filter(team_id=self.team.pk).exists()

    @time_machine.travel(_NOW, tick=False)
    def test_a_runner_told_to_bucket_in_utc_is_declined(self) -> None:
        self._set_up_team("America/Los_Angeles")
        runner = TrendsQueryRunner(
            team=self.team, query=_query(), modifiers=HogQLQueryModifiers(convertToProjectTimezone=False)
        )

        assert precomputed_series_values(runner) == SeriesValuesUnavailable(reason=Blocker.TIMEZONE)

    @time_machine.travel(_NOW, tick=False)
    def test_no_build_starts_once_the_wait_is_used_up(self) -> None:
        precomputed = precomputed_series_values(
            TrendsQueryRunner(team=self.team, query=_query()), wait_timeout_seconds=0
        )

        assert precomputed == SeriesValuesUnavailable(reason=Blocker.NOT_READY)
        assert not PreaggregationJob.objects.filter(team_id=self.team.pk).exists()

    @time_machine.travel(_NOW, tick=False)
    def test_a_team_with_property_access_rules_is_declined(self) -> None:
        with patch(f"{_MODULE}.team_has_property_access_rules", return_value=True):
            precomputed = precomputed_series_values(TrendsQueryRunner(team=self.team, query=_query()))

        assert precomputed == SeriesValuesUnavailable(reason=Blocker.PROPERTY_ACCESS_RULES)

    @time_machine.travel(_NOW, tick=False)
    def test_a_range_that_the_returned_jobs_leave_uncovered_is_declined(self) -> None:
        result = LazyComputationResult(
            ready=True,
            job_ids=[uuid4()],
            served_windows=(
                ServedWindow(
                    start=datetime(2024, 1, 8, tzinfo=UTC), end=datetime(2024, 1, 10, tzinfo=UTC), computed_at=None
                ),
            ),
        )
        with patch(f"{_MODULE}.ensure_precomputed", return_value=result):
            precomputed = precomputed_series_values(TrendsQueryRunner(team=self.team, query=_query()))

        assert precomputed == SeriesValuesUnavailable(reason=Blocker.NOT_READY)

    @time_machine.travel(_NOW, tick=False)
    def test_rows_land_in_columns_and_a_second_run_reuses_the_jobs(self) -> None:
        self._seed()
        query = _query(properties=[_PRO])

        with patch.object(Database, "create_for", wraps=Database.create_for) as full_database:
            first, _ = self._served(query)
            jobs = PreaggregationJob.objects.filter(team_id=self.team.pk).count()
            full_databases_with_a_build = full_database.call_count
            second, request = self._served(query)
            full_databases_without_a_build = full_database.call_count - full_databases_with_a_build

        assert first == second
        assert jobs > 1
        assert PreaggregationJob.objects.filter(team_id=self.team.pk).count() == jobs
        assert request.built == [False]
        assert full_databases_with_a_build - full_databases_without_a_build == 1
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
            ("2024-01-14 07:00:00.000000", "2024-01-14 08:00:00.000000", "", 2.0),
            ("2024-01-14 08:00:00.000000", "2024-01-14 09:00:00.000000", "", 1.0),
        ]

    @time_machine.travel(_NOW, tick=False)
    def test_a_row_without_a_window_end_is_not_read(self) -> None:
        self._seed()
        query = _query(properties=[_PRO])
        before, _ = self._served(query)
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

        after, _ = self._served(query)

        assert after == before

    @time_machine.travel(_NOW, tick=False)
    def test_stored_values_older_than_the_event_retention_are_not_read(self) -> None:
        self._seed()
        query = _query(interval=IntervalType.HOUR, dateRange=DateRange(date_from="2023-11-04", date_to="2023-11-06"))
        before, _ = self._served(query)

        with patch("posthog.models.team.event_retention.events_retention_months_for_team", return_value=1):
            live = self._live(query)
            served, request = self._served(query)

        assert sum(before[0]["data"]) == 3
        assert json.dumps(served, default=str) == json.dumps(live, default=str)
        assert (sum(served[0]["data"]), request.built) == (0, [False])

    def test_a_day_built_before_late_events_settle_is_rebuilt(self) -> None:
        self._seed()
        query = _query()
        with time_machine.travel("2024-01-15T00:02:00Z", tick=False):
            self._served(query)
        _create_event(team=self.team, event="signed_up", distinct_id="p1", timestamp="2024-01-14T23:59:30Z")
        flush_persons_and_events()

        with time_machine.travel("2024-01-15T01:30:00Z", tick=False):
            live = self._live(query)
            served, _ = self._served(query)

        assert json.dumps(served, default=str) == json.dumps(live, default=str)
