from datetime import datetime

import time_machine
from posthog.test.base import BaseTest, QueryMatchingTest, _create_action, _create_event, _create_person
from unittest.mock import patch

from parameterized import parameterized

from posthog.schema import (
    ActionsNode,
    BaseMathType,
    Breakdown,
    BreakdownFilter,
    BreakdownType,
    ChartDisplayType,
    DataWarehouseNode,
    DateRange,
    EventsNode,
    HogQLQueryResponse,
    IntervalType,
    TrendsFilter,
    TrendsQuery,
)

from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.query import HogQLQueryExecutor
from posthog.hogql.timings import HogQLTimings

from posthog.hogql_queries.utils.query_date_range import QueryDateRange

from products.product_analytics.backend.hogql_queries.trends.trends_query_builder import TrendsQueryBuilder


class TestTrendsQueryBuilder(QueryMatchingTest, BaseTest):
    allow_dual_schema_snapshots = True

    def setUp(self):
        super().setUp()

        with time_machine.travel("2023-02-01", tick=False):
            _create_person(
                distinct_ids=["some_id"],
                team_id=self.team.pk,
                properties={"$some_prop": "something", "$another_prop": "something"},
            )
            _create_event(
                event="$pageview",
                team=self.team,
                distinct_id="some_id",
                properties={"$geoip_country_code": "AU"},
            )

    def get_response(self, trends_query: TrendsQuery) -> HogQLQueryResponse:
        query_date_range = QueryDateRange(
            date_range=trends_query.dateRange,
            team=self.team,
            interval=trends_query.interval,
            now=datetime.now(),
        )

        timings = HogQLTimings()
        modifiers = create_default_modifiers_for_team(self.team)

        if isinstance(trends_query.series[0], DataWarehouseNode):
            raise Exception("Data Warehouse queries are not supported in this test")

        query_builder = TrendsQueryBuilder(
            trends_query=trends_query,
            team=self.team,
            query_date_range=query_date_range,
            series=trends_query.series[0],
            timings=timings,
            modifiers=modifiers,
        )

        query = query_builder.build_query()

        return HogQLQueryExecutor(
            query=query,
            team=self.team,
            timings=timings,
        ).execute()

    def test_column_names(self):
        trends_query = TrendsQuery(
            kind="TrendsQuery",
            dateRange=DateRange(date_from="2023-01-01"),
            series=[EventsNode(event="$pageview", math=BaseMathType.TOTAL)],
        )

        response = self.get_response(trends_query)

        assert response.columns is not None
        assert set(response.columns).issubset({"date", "total", "breakdown_value"})

    @parameterized.expand(
        [
            ("hour", "UTC", "total", None, None, "$pageview", False),
            ("day", "Pacific/Auckland", "total", None, None, "$pageview", False),
            ("hour", "UTC", "total", None, None, "missing_event", False),
            ("hour", "UTC", "dau", None, None, "$pageview", False),
            ("hour", "UTC", "total", 3, None, "$pageview", False),
            ("hour", "UTC", "total", None, "ActionsLineGraphCumulative", "$pageview", False),
            ("hour", "UTC", "total", None, None, "$pageview", True),
            ("hour", "UTC", "total", None, None, "$pageview", False, True),
        ]
    )
    @time_machine.travel("2023-02-03", tick=False)
    def test_rank_before_arrays_preserves_results(
        self,
        interval: IntervalType,
        project_timezone: str,
        math: BaseMathType,
        smoothing: int | None,
        display: ChartDisplayType | None,
        event: str,
        multiple: bool,
        action: bool = False,
    ) -> None:
        self.team.timezone = project_timezone
        self.team.save()
        for bucket, count in [("a", 4), ("b", 3), ("c", 3), ("d", 2), (None, 6), ("", 1)]:
            for index in range(count):
                _create_event(
                    event="$pageview",
                    team=self.team,
                    distinct_id="some_id",
                    timestamp=f"2023-02-{1 + index % 2:02d}T{index % 2:02d}:00:00Z",
                    properties={"bucket": bucket},
                )
        series: EventsNode | ActionsNode = EventsNode(event=event, math=math)
        if action:
            saved_action = _create_action(team=self.team, name=event)
            series = ActionsNode(id=saved_action.id, math=math)
        query = TrendsQuery(
            dateRange=DateRange(date_from="2023-02-01", date_to="2023-02-02"),
            interval=interval,
            series=[series],
            breakdownFilter=(
                BreakdownFilter(breakdowns=[Breakdown(property="bucket", type="event")], breakdown_limit=2)
                if multiple
                else BreakdownFilter(breakdown="bucket", breakdown_type="event", breakdown_limit=2)
            ),
            trendsFilter=TrendsFilter(smoothingIntervals=smoothing, display=display),
        )
        flag_path = (
            "products.product_analytics.backend.hogql_queries.trends.trends_query_builder.feature_enabled_or_false"
        )
        with patch(flag_path, return_value=False):
            original = self.get_response(query)
        with patch(flag_path, side_effect=lambda flag, *args, **kwargs: flag == "trends-breakdown-rank-before-arrays"):
            optimized = self.get_response(query)
        assert optimized.results == original.results
        assert optimized.columns == original.columns
        assert optimized.types == original.types
        if math == "total" and smoothing is None and display is None:
            assert optimized.clickhouse is not None
            assert "dense_rank()" in optimized.clickhouse
            assert "arrayFold" not in optimized.clickhouse
            if event == "$pageview":
                assert len(optimized.results) == 3
                assert optimized.results[0][2] == (["a"] if multiple else "a")
                assert optimized.results[1][2] == (["b"] if multiple else "b")
                if interval == "day":
                    assert len(optimized.results[1][1]) == 2
                    assert optimized.results[1][1][0] > optimized.results[1][1][1] > 0
        else:
            assert optimized.clickhouse == original.clickhouse

    @time_machine.travel("2023-02-03", tick=False)
    def test_rank_before_arrays_sql(self) -> None:
        query = TrendsQuery(
            dateRange=DateRange(date_from="2023-02-01", date_to="2023-02-02"),
            series=[EventsNode(event="$pageview", math="total")],
            breakdownFilter=BreakdownFilter(breakdown="bucket", breakdown_type="event", breakdown_limit=2),
        )
        with patch(
            "products.product_analytics.backend.hogql_queries.trends.trends_query_builder.feature_enabled_or_false",
            side_effect=lambda flag, *args, **kwargs: flag == "trends-breakdown-rank-before-arrays",
        ):
            response = self.get_response(query)
        self.assertQueryMatchesSnapshot(response.clickhouse)

    def assert_column_names_with_display_type(self, display_type: ChartDisplayType):
        trends_query = TrendsQuery(
            kind="TrendsQuery",
            dateRange=DateRange(date_from="2023-01-01"),
            series=[EventsNode(event="$pageview")],
            trendsFilter=TrendsFilter(display=display_type),
        )

        response = self.get_response(trends_query)

        assert response.columns is not None
        assert set(response.columns).issubset({"date", "total", "breakdown_value"})

    def assert_column_names_with_display_type_and_breakdowns(self, display_type: ChartDisplayType):
        trends_query = TrendsQuery(
            kind="TrendsQuery",
            dateRange=DateRange(date_from="2023-01-01"),
            series=[EventsNode(event="$pageview")],
            trendsFilter=TrendsFilter(display=display_type),
            breakdownFilter=BreakdownFilter(breakdown="$geoip_country_code", breakdown_type=BreakdownType.EVENT),
        )

        response = self.get_response(trends_query)

        assert response.columns is not None
        assert set(response.columns).issubset({"date", "total", "breakdown_value"})

    def test_column_names_with_display_type(self):
        self.assert_column_names_with_display_type(ChartDisplayType.ACTIONS_AREA_GRAPH)
        self.assert_column_names_with_display_type(ChartDisplayType.ACTIONS_BAR)
        self.assert_column_names_with_display_type(ChartDisplayType.ACTIONS_BAR_VALUE)
        self.assert_column_names_with_display_type(ChartDisplayType.ACTIONS_LINE_GRAPH)
        self.assert_column_names_with_display_type(ChartDisplayType.ACTIONS_PIE)
        self.assert_column_names_with_display_type(ChartDisplayType.BOLD_NUMBER)
        self.assert_column_names_with_display_type(ChartDisplayType.WORLD_MAP)
        self.assert_column_names_with_display_type(ChartDisplayType.ACTIONS_LINE_GRAPH_CUMULATIVE)

    def test_column_names_with_display_type_and_breakdowns(self):
        self.assert_column_names_with_display_type_and_breakdowns(ChartDisplayType.ACTIONS_AREA_GRAPH)
        self.assert_column_names_with_display_type_and_breakdowns(ChartDisplayType.ACTIONS_BAR)
        self.assert_column_names_with_display_type_and_breakdowns(ChartDisplayType.ACTIONS_BAR_VALUE)
        self.assert_column_names_with_display_type_and_breakdowns(ChartDisplayType.ACTIONS_LINE_GRAPH)
        self.assert_column_names_with_display_type_and_breakdowns(ChartDisplayType.ACTIONS_PIE)
        self.assert_column_names_with_display_type_and_breakdowns(ChartDisplayType.WORLD_MAP)
        self.assert_column_names_with_display_type_and_breakdowns(ChartDisplayType.ACTIONS_LINE_GRAPH_CUMULATIVE)
