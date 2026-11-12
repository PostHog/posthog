import time_machine
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    snapshot_clickhouse_queries,
)
from unittest import mock

from parameterized import parameterized

from posthog.schema import (
    DateRange,
    EventPropertyFilter,
    HogQLQueryModifiers,
    PersonPropertyFilter,
    PropertyOperator,
    SessionPropertyFilter,
    WebOverviewQuery,
    WebStatsBreakdown,
    WebStatsTableQuery,
)

from posthog.hogql.database.database import Database

from posthog.clickhouse.query_tagging import tag_queries
from posthog.models.scoping import team_scope

from products.data_tools.backend.models.expression import DataWarehouseExpression
from products.web_analytics.backend.hogql_queries.stats_table import WebStatsTableQueryRunner
from products.web_analytics.backend.hogql_queries.web_overview import WebOverviewQueryRunner

_DIMENSIONAL_RANGE = DateRange(date_from="2023-12-08", date_to="2023-12-15")


@snapshot_clickhouse_queries
class TestWebStatsTableQueryRunner(ClickhouseTestMixin, APIBaseTest):
    def _create_events(self, data, event="$pageview"):
        for id, timestamps in data:
            with time_machine.travel(timestamps[0][0], tick=False):
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
            # PAGE without bounce/avg-time displays no session-derived column,
            # so it takes the no-join simple-breakdown fast path.
            (
                "simple_breakdown",
                WebStatsBreakdown.PAGE,
                False,
                False,
                None,
                "stats_table_no_join_simple_breakdown_query",
            ),
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

    def test_bypass_run_does_not_share_cache_or_single_flight_with_user_run(self) -> None:
        query = WebOverviewQuery(dateRange=DateRange(date_from="2023-12-08", date_to="2023-12-15"), properties=[])

        user_run = WebOverviewQueryRunner(team=self.team, query=query)
        bypass_run = WebOverviewQueryRunner(team=self.team, query=query, bypass_warehouse_access_control=True)

        assert user_run.get_cache_key() != bypass_run.get_cache_key()
        assert user_run.single_flight_variant() != bypass_run.single_flight_variant()

    @parameterized.expand(
        [
            ("overview", WebOverviewQueryRunner, WebOverviewQuery(dateRange=_DIMENSIONAL_RANGE, properties=[])),
            (
                "stats_table",
                WebStatsTableQueryRunner,
                WebStatsTableQuery(dateRange=_DIMENSIONAL_RANGE, properties=[], breakdownBy=WebStatsBreakdown.PAGE),
            ),
        ]
    )
    def test_dimensional_read_kill_switch_changes_the_cache_key(self, _name, runner_class, query) -> None:
        self.team.modifiers = {"useWebAnalyticsDimensionalTables": True}

        def cache_key(reads_disabled: bool) -> str:
            with mock.patch(
                "products.web_analytics.backend.hogql_queries.web_dimensional_read.feature_enabled_or_false",
                return_value=reads_disabled,
            ):
                return runner_class(team=self.team, query=query).get_cache_key()

        assert cache_key(reads_disabled=False) != cache_key(reads_disabled=True)


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


class TestWebAnalyticsDatabaseBuild(ClickhouseTestMixin, APIBaseTest):
    @parameterized.expand(
        [
            ("stats_table_without_filters", "stats_table", [], False),
            ("overview_without_filters", "overview", [], False),
            (
                "stats_table_with_event_filter",
                "stats_table",
                [EventPropertyFilter(key="$browser", value="Chrome", operator=PropertyOperator.EXACT)],
                False,
            ),
            (
                "stats_table_with_person_filter",
                "stats_table",
                [PersonPropertyFilter(key="email", value="test@posthog.com", operator=PropertyOperator.EXACT)],
                True,
            ),
            (
                "overview_with_person_filter",
                "overview",
                [PersonPropertyFilter(key="email", value="test@posthog.com", operator=PropertyOperator.EXACT)],
                True,
            ),
            (
                "stats_table_with_built_in_session_filter",
                "stats_table",
                [SessionPropertyFilter(key="$entry_pathname", value="/", operator=PropertyOperator.EXACT)],
                False,
            ),
            (
                "stats_table_with_saved_session_expression_filter",
                "stats_table",
                [SessionPropertyFilter(key="is_long_session", value="1", operator=PropertyOperator.EXACT)],
                True,
            ),
        ]
    )
    def test_full_database_is_built_only_when_a_filter_can_read_the_warehouse(
        self, _name, kind, properties, builds_full_database
    ):
        with team_scope(self.team.id, canonical=True):
            DataWarehouseExpression.objects.create(
                team=self.team,
                table_name="sessions",
                field_name="is_long_session",
                expression="$session_duration > 60",
            )
        date_range = DateRange(date_from="2024-01-01", date_to="2024-01-02")
        runner: WebStatsTableQueryRunner | WebOverviewQueryRunner
        if kind == "stats_table":
            runner = WebStatsTableQueryRunner(
                team=self.team,
                query=WebStatsTableQuery(
                    dateRange=date_range, properties=properties, breakdownBy=WebStatsBreakdown.PAGE
                ),
            )
        else:
            runner = WebOverviewQueryRunner(
                team=self.team, query=WebOverviewQuery(dateRange=date_range, properties=properties)
            )

        with mock.patch.object(Database, "create_for", wraps=Database.create_for) as create_for:
            runner.calculate()

        assert create_for.called == builds_full_database
