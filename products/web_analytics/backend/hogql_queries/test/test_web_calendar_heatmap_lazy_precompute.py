from collections.abc import Iterator
from contextlib import ExitStack, contextmanager

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person
from unittest.mock import patch

from django.test import override_settings

from parameterized import parameterized

from posthog.schema import (
    CalendarHeatmapFilter,
    ChartDisplayType,
    DateRange,
    EventsHeatMapStructuredResult,
    EventsNode,
    TrendsFilter,
    TrendsQuery,
)

from posthog.clickhouse.client import sync_execute
from posthog.hogql_queries.insights.trends.calendar_heatmap_trends_query_runner import CalendarHeatmapTrendsQueryRunner
from posthog.hogql_queries.query_runner import get_query_runner
from posthog.models import EventDefinition
from posthog.models.utils import uuid7

from products.analytics_platform.backend.models.preaggregation_job import PreaggregationJob
from products.web_analytics.backend.hogql_queries.web_calendar_heatmap import WebCalendarHeatmapTrendsQueryRunner


@override_settings(IN_UNIT_TESTING=True)
class TestWebCalendarHeatmapLazyPrecompute(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        PreaggregationJob.objects.filter(team_id=self.team.pk).delete()
        sync_execute("SYSTEM STOP TTL MERGES sharded_web_overview_preaggregated")

    @contextmanager
    def _enable(self) -> Iterator[None]:
        with patch(
            "products.web_analytics.backend.hogql_queries.web_lazy_precompute_common.posthoganalytics.feature_enabled",
            return_value=True,
        ):
            yield

    def _seed(self) -> None:
        # Two sessions on different weekdays/hours plus a second visitor sharing
        # one cell — exercises cell dedupe, row/column rollups, and the total.
        # 2024-01-02 is a Tuesday (dow 2), 2024-01-03 a Wednesday (dow 3).
        _create_person(team_id=self.team.pk, distinct_ids=["p1"], properties={})
        _create_person(team_id=self.team.pk, distinct_ids=["p2"], properties={})
        s1 = str(uuid7("2024-01-02"))
        s2 = str(uuid7("2024-01-03"))
        s3 = str(uuid7("2024-01-02"))
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2024-01-02T10:00:00Z",
            properties={"$session_id": s1, "$host": "example.com"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p1",
            timestamp="2024-01-03T15:00:00Z",
            properties={"$session_id": s2, "$host": "example.com"},
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id="p2",
            timestamp="2024-01-02T10:30:00Z",
            properties={"$session_id": s3, "$host": "example.com"},
        )

    def _build_query(self, unique_tab: bool = True) -> TrendsQuery:
        return TrendsQuery(
            dateRange=DateRange(date_from="2024-01-01", date_to="2024-01-07"),
            series=[EventsNode(event="$pageview", math="dau" if unique_tab else "total")],
            trendsFilter=TrendsFilter(display=ChartDisplayType.CALENDAR_HEATMAP),
            calendarHeatmapFilter=CalendarHeatmapFilter(bucketBySessionStart=True) if unique_tab else None,
            properties=[],
        )

    @staticmethod
    def _heatmap_as_dicts(
        structured: EventsHeatMapStructuredResult,
    ) -> tuple[set[tuple[int, int, int]], set[tuple[int, int]], set[tuple[int, int]], int]:
        cells = {(d.row, d.column, d.value) for d in structured.data}
        rows = {(r.row, r.value) for r in structured.rowAggregations}
        cols = {(c.column, c.value) for c in structured.columnAggregations}
        return cells, rows, cols, structured.allAggregations

    @freeze_time("2024-01-15T12:00:00Z")
    def test_unique_tab_matches_live_calendar_heatmap(self) -> None:
        self._seed()
        query = self._build_query(unique_tab=True)

        live = CalendarHeatmapTrendsQueryRunner(team=self.team, query=query).calculate()

        with self._enable():
            precomputed = WebCalendarHeatmapTrendsQueryRunner(team=self.team, query=query).calculate()

        assert PreaggregationJob.objects.filter(team_id=self.team.pk).count() > 0
        live_hm = live.results[0]["calendar_heatmap_data"]
        pre_hm = precomputed.results[0]["calendar_heatmap_data"]
        assert self._heatmap_as_dicts(pre_hm) == self._heatmap_as_dicts(live_hm)
        assert precomputed.results[0]["count"] == live.results[0]["count"]

    @freeze_time("2024-01-15T12:00:00Z")
    def test_total_events_tab_falls_back(self) -> None:
        # The total tab buckets by raw event timestamp; the session-start-keyed
        # buckets can't reproduce that, so serving it would shift midnight- and
        # hour-spanning activity into wrong cells. It must take the live path.
        self._seed()
        query = self._build_query(unique_tab=False)
        with self._enable():
            response = WebCalendarHeatmapTrendsQueryRunner(team=self.team, query=query).calculate()
        assert PreaggregationJob.objects.filter(team_id=self.team.pk).count() == 0
        assert response.results[0]["count"] > 0

    @parameterized.expand(
        [
            ("distinct_id_aggregation",),
            ("mixed_event_types",),
            ("sub_hour_range",),
        ]
    )
    def test_falls_back_when_buckets_cannot_reproduce_live_semantics(self, case: str) -> None:
        with ExitStack() as stack:
            stack.enter_context(freeze_time("2024-01-15T12:00:00Z"))
            self._seed()
            query = self._build_query()
            if case == "distinct_id_aggregation":
                stack.enter_context(
                    patch.object(type(self.team), "aggregate_users_by_distinct_id", property(lambda self: True))
                )
            elif case == "mixed_event_types":
                EventDefinition.objects.create(team=self.team, name="$screen")
            else:
                query.dateRange = DateRange(
                    date_from="2024-01-02T10:15:00", date_to="2024-01-02T12:45:00", explicitDate=True
                )
            stack.enter_context(self._enable())
            response = WebCalendarHeatmapTrendsQueryRunner(team=self.team, query=query).calculate()
        assert PreaggregationJob.objects.filter(team_id=self.team.pk).count() == 0
        assert response.results[0]["count"] > 0

    def test_dispatch_routes_wa_tagged_heatmap_queries(self) -> None:
        tagged = self._build_query().model_dump()
        tagged["tags"] = {"productKey": "web_analytics"}
        with override_settings(WEB_ANALYTICS_TRENDS_PRECOMPUTE_TEAM_IDS=[self.team.pk]):
            assert isinstance(get_query_runner(tagged, self.team), WebCalendarHeatmapTrendsQueryRunner)

        # Flag off: even tagged queries stay on the untouched vanilla wrapper.
        flag_off = patch(
            "products.web_analytics.backend.hogql_queries.web_trends_lazy_precompute.posthoganalytics.feature_enabled",
            return_value=False,
        )
        with flag_off:
            runner = get_query_runner(tagged, self.team)
            assert isinstance(runner, CalendarHeatmapTrendsQueryRunner)
            assert not isinstance(runner, WebCalendarHeatmapTrendsQueryRunner)

        with override_settings(WEB_ANALYTICS_TRENDS_PRECOMPUTE_TEAM_IDS=[self.team.pk]):
            runner = get_query_runner(self._build_query(), self.team)
        assert isinstance(runner, CalendarHeatmapTrendsQueryRunner)
        assert not isinstance(runner, WebCalendarHeatmapTrendsQueryRunner)
