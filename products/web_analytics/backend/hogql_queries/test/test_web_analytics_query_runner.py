from freezegun import freeze_time
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    snapshot_clickhouse_queries,
)
from unittest import mock

from parameterized import parameterized

from posthog.schema import DateRange, HogQLQueryModifiers, WebOverviewQuery, WebStatsBreakdown, WebStatsTableQuery

from posthog.clickhouse.query_tagging import tag_queries

from products.web_analytics.backend.hogql_queries.stats_table import WebStatsTableQueryRunner
from products.web_analytics.backend.hogql_queries.web_overview import WebOverviewQueryRunner


@snapshot_clickhouse_queries
class TestWebStatsTableQueryRunner(ClickhouseTestMixin, APIBaseTest):
    def _create_events(self, data, event="$pageview"):
        for id, timestamps in data:
            with freeze_time(timestamps[0][0]):
                _create_person(
                    team_id=self.team.pk,
                    distinct_ids=[id],
                    properties={
                        "name": id,
                        **({"email": "test@posthog.com"} if id == "test" else {}),
                    },
                )
            for timestamp, *rest in timestamps:
                properties = rest[0] if rest else {}
                _create_event(
                    team=self.team,
                    event=event,
                    distinct_id=id,
                    timestamp=timestamp,
                    properties={
                        **properties,
                    },
                )

    def _create_web_stats_table_query(self, date_from, date_to, properties, breakdown_by=WebStatsBreakdown.PAGE):
        query = WebStatsTableQuery(
            dateRange=DateRange(date_from=date_from, date_to=date_to), properties=properties, breakdownBy=breakdown_by
        )
        return WebStatsTableQueryRunner(team=self.team, query=query)

    def _create__web_overview_query(self, date_from, date_to, properties):
        query = WebOverviewQuery(
            dateRange=DateRange(date_from=date_from, date_to=date_to),
            properties=properties,
        )
        return WebOverviewQueryRunner(team=self.team, query=query)

    @parameterized.expand(
        [
            ("simple_breakdown", WebStatsBreakdown.PAGE, False, False, None, "stats_table_simple_breakdown_query"),
            (
                "channel_type",
                WebStatsBreakdown.INITIAL_CHANNEL_TYPE,
                False,
                False,
                None,
                "stats_table_channel_type_query",
            ),
            ("path_bounce", WebStatsBreakdown.PAGE, True, False, None, "stats_table_path_bounce_query"),
            (
                "path_bounce_and_avg_time",
                WebStatsBreakdown.PAGE,
                False,
                True,
                None,
                "stats_table_path_bounce_and_avg_time_query",
            ),
            (
                "entry_bounce",
                WebStatsBreakdown.INITIAL_PAGE,
                True,
                False,
                None,
                "stats_table_entry_bounce_query",
            ),
            (
                "frustration_metrics",
                WebStatsBreakdown.FRUSTRATION_METRICS,
                False,
                False,
                None,
                "stats_table_frustration_metrics_query",
            ),
            (
                "preaggregated",
                WebStatsBreakdown.PAGE,
                False,
                False,
                HogQLQueryModifiers(useWebAnalyticsPreAggregatedTables=True),
                "stats_table_preaggregated_path_breakdown_query",
            ),
            (
                "preaggregated_entry_bounce",
                WebStatsBreakdown.INITIAL_PAGE,
                True,
                False,
                HogQLQueryModifiers(useWebAnalyticsPreAggregatedTables=True),
                "stats_table_preaggregated_entry_bounce_query",
            ),
            (
                "preaggregated_generic",
                WebStatsBreakdown.INITIAL_CHANNEL_TYPE,
                False,
                False,
                HogQLQueryModifiers(useWebAnalyticsPreAggregatedTables=True),
                "stats_table_preaggregated_query",
            ),
        ]
    )
    def test_stats_table_query_type_tracks_strategy(
        self,
        _name: str,
        breakdown_by: WebStatsBreakdown,
        include_bounce_rate: bool,
        include_avg_time_on_page: bool,
        modifiers: HogQLQueryModifiers | None,
        expected_query_type: str,
    ) -> None:
        query = WebStatsTableQuery(
            dateRange=DateRange(date_from="2023-12-08", date_to="2023-12-15"),
            properties=[],
            breakdownBy=breakdown_by,
            includeBounceRate=include_bounce_rate,
            includeAvgTimeOnPage=include_avg_time_on_page,
        )
        runner = WebStatsTableQueryRunner(team=self.team, query=query, modifiers=modifiers)

        if modifiers and modifiers.useWebAnalyticsPreAggregatedTables:
            self.team.web_analytics_pre_aggregated_tables_version = "v2"

        self.assertEqual(runner.clickhouse_query_type(), expected_query_type)


class TestWebAnalyticsBreakdownTagging(ClickhouseTestMixin, APIBaseTest):
    @parameterized.expand(
        [
            ("page", WebStatsBreakdown.PAGE, ["Page"]),
            ("browser", WebStatsBreakdown.BROWSER, ["Browser"]),
            ("initial_channel_type", WebStatsBreakdown.INITIAL_CHANNEL_TYPE, ["InitialChannelType"]),
            ("country", WebStatsBreakdown.COUNTRY, ["Country"]),
        ]
    )
    def test_calculate_tags_breakdown_by_for_stats_table_query(
        self,
        _name: str,
        breakdown_by: WebStatsBreakdown,
        expected_breakdown_by: list[str],
    ) -> None:
        query = WebStatsTableQuery(
            dateRange=DateRange(date_from="2023-12-08", date_to="2023-12-15"),
            properties=[],
            breakdownBy=breakdown_by,
        )
        runner = WebStatsTableQueryRunner(team=self.team, query=query)

        with mock.patch(
            "products.web_analytics.backend.hogql_queries.web_analytics_query_runner.tag_queries",
            wraps=tag_queries,
        ) as spy:
            runner.calculate()

        breakdown_calls = [c for c in spy.call_args_list if "breakdown_by" in c.kwargs]
        self.assertEqual(len(breakdown_calls), 1, f"expected one breakdown_by tag, got: {spy.call_args_list}")
        self.assertEqual(breakdown_calls[0].kwargs["breakdown_by"], expected_breakdown_by)

    def test_calculate_does_not_tag_breakdown_by_when_query_has_no_breakdown(self) -> None:
        query = WebOverviewQuery(
            dateRange=DateRange(date_from="2023-12-08", date_to="2023-12-15"),
            properties=[],
        )
        runner = WebOverviewQueryRunner(team=self.team, query=query)

        with mock.patch(
            "products.web_analytics.backend.hogql_queries.web_analytics_query_runner.tag_queries",
            wraps=tag_queries,
        ) as spy:
            runner.calculate()

        breakdown_calls = [c for c in spy.call_args_list if "breakdown_by" in c.kwargs]
        self.assertEqual(breakdown_calls, [], f"did not expect any breakdown_by tag, got: {spy.call_args_list}")
