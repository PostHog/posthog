import time_machine
from posthog.test.base import _create_event, _create_person, flush_persons_and_events

from django.test import override_settings

from parameterized import parameterized

from posthog.schema import (
    ActionConversionGoal,
    CompareFilter,
    CustomEventConversionGoal,
    DateRange,
    EventPropertyFilter,
    HogQLQueryModifiers,
    SessionTableVersion,
    WebStatsBreakdown,
    WebStatsTableQuery,
)

from posthog.clickhouse.client.execute import sync_execute
from posthog.models.utils import uuid7
from posthog.models.web_preaggregated.sql import WEB_STATS_INSERT_SQL

from products.actions.backend.models.action import Action
from products.web_analytics.backend.hogql_queries.stats_table import WebStatsTableQueryRunner
from products.web_analytics.backend.hogql_queries.test.web_preaggregated_test_base import (
    WebAnalyticsPreAggregatedTestBase,
)


class TestWebStatsTablePreAggregatedConversions(WebAnalyticsPreAggregatedTestBase):
    def _setup_test_data(self, user_prefix="user"):
        with time_machine.travel("2024-01-01T09:00:00Z", tick=False):
            _create_person(team_id=self.team.pk, distinct_ids=[f"{user_prefix}1"])
            _create_person(team_id=self.team.pk, distinct_ids=[f"{user_prefix}2"])

        # Use uuid7 with different timestamps to generate unique session IDs
        self.session1_id = str(uuid7("2024-01-01T10:00:00"))
        self.session2_id = str(uuid7("2024-01-01T11:00:00"))

        # Session 1: visits /page1 and converts
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id=f"{user_prefix}1",
            timestamp="2024-01-01T10:00:00Z",
            properties={
                "$session_id": self.session1_id,
                "$current_url": "https://example.com/page1",
                "$pathname": "/page1",
            },
        )

        # Session 2: visits /page2 but doesn't convert
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id=f"{user_prefix}2",
            timestamp="2024-01-01T11:00:00Z",
            properties={
                "$session_id": self.session2_id,
                "$current_url": "https://example.com/page2",
                "$pathname": "/page2",
            },
        )

        flush_persons_and_events()

    def test_conversion_goal_with_preaggregated_tables(self):
        """Test that conversion goals work with pre-aggregated tables by using hybrid approach"""
        self._setup_test_data(user_prefix="hybrid")

        # Create a conversion action
        action = Action.objects.create(
            team=self.team,
            name="Converted",
            steps_json=[
                {
                    "event": "$pageview",
                    "url": "/page1",
                    "url_matching": "contains",
                }
            ],
        )

        # Populate pre-aggregated stats table with visitor data
        sql = WEB_STATS_INSERT_SQL(
            date_start="2024-01-01", date_end="2024-01-02", team_ids=[self.team.pk], select_only=True
        )
        sync_execute(f"INSERT INTO web_pre_aggregated_stats {sql}")

        with time_machine.travel("2024-01-02T00:00:00Z", tick=False):
            modifiers = HogQLQueryModifiers(
                sessionTableVersion=SessionTableVersion.V2,
                useWebAnalyticsPreAggregatedTables=True,
            )
            query = WebStatsTableQuery(
                dateRange=DateRange(date_from="2024-01-01", date_to="2024-01-02"),
                breakdownBy=WebStatsBreakdown.PAGE,
                conversionGoal=ActionConversionGoal(actionId=action.id),
                properties=[],
            )
            runner = WebStatsTableQueryRunner(team=self.team, query=query, modifiers=modifiers)

            # Verify pre-aggregated tables can be used
            assert runner.preaggregated_query_builder.can_use_preaggregated_tables()

            # Execute the query
            response = runner.calculate()

            # Verify we get conversion data
            assert response.results is not None
            assert len(response.results) >= 2  # At least 2 pages

            # Verify columns include conversion metrics
            assert response.columns is not None
            assert "context.columns.visitors" in response.columns
            assert "context.columns.total_conversions" in response.columns
            assert "context.columns.unique_conversions" in response.columns
            assert "context.columns.conversion_rate" in response.columns

            # Find the row with the conversion
            page1_row = next((row for row in response.results if row[0] == "/page1"), None)
            assert page1_row is not None
            visitors_current, visitors_previous = page1_row[1]
            total_conversions_current, total_conversions_previous = page1_row[2]
            unique_conversions_current, unique_conversions_previous = page1_row[3]
            conversion_rate_current, conversion_rate_previous = page1_row[4]

            # Page1 should have at least 1 visitor and 1 conversion
            assert visitors_current >= 1
            assert total_conversions_current >= 1.0
            assert unique_conversions_current >= 1.0
            assert conversion_rate_current > 0

            # Page 2 should have no conversions
            page2_row = next((row for row in response.results if row[0] == "/page2"), None)
            assert page2_row is not None

            visitors_current, visitors_previous = page2_row[1]
            total_conversions_current, total_conversions_previous = page2_row[2]
            unique_conversions_current, unique_conversions_previous = page2_row[3]
            conversion_rate_current, conversion_rate_previous = page2_row[4]

            # Page2 should have visitors but no conversions
            assert visitors_current >= 1
            assert total_conversions_current == 0.0
            assert unique_conversions_current == 0.0
            assert conversion_rate_current == 0.0
            query.includeTrafficMetrics = True
            traffic_response = WebStatsTableQueryRunner(team=self.team, query=query, modifiers=modifiers).calculate()
            assert traffic_response.columns is not None
            traffic_row = dict(
                zip(traffic_response.columns, next(row for row in traffic_response.results if row[0] == "/page1"))
            )
            assert traffic_row["context.columns.sessions"][0] >= 1
            assert traffic_row["context.columns.views"][0] >= 1
            assert traffic_row["context.columns.unique_conversions"][0] >= 1
            query.conversionGoal = None
            without_goal = WebStatsTableQueryRunner(team=self.team, query=query, modifiers=modifiers).calculate()
            assert without_goal.columns is not None
            without_goal_row = dict(
                zip(without_goal.columns, next(row for row in without_goal.results if row[0] == "/page1"))
            )
            assert without_goal_row["context.columns.sessions"] == traffic_row["context.columns.sessions"]
            assert without_goal_row["context.columns.views"] == traffic_row["context.columns.views"]

    def test_traffic_population_excludes_goal_only_sessions(self):
        for i in range(3):
            distinct_id = f"goal_only_{i}"
            _create_person(team_id=self.team.pk, distinct_ids=[distinct_id])
            _create_event(
                team=self.team,
                event="customer_created",
                distinct_id=distinct_id,
                timestamp="2024-01-01T12:00:00Z",
                properties={
                    "$session_id": str(uuid7("2024-01-01T12:00:00")),
                    "$current_url": "https://example.com/page1",
                    "$pathname": "/page1",
                },
            )
        flush_persons_and_events()
        sql = WEB_STATS_INSERT_SQL(
            date_start="2024-01-01", date_end="2024-01-02", team_ids=[self.team.pk], select_only=True
        )
        sync_execute(f"INSERT INTO web_pre_aggregated_stats {sql}")
        with time_machine.travel("2024-01-02T00:00:00Z", tick=False):
            for preaggregated in [False, True]:
                for goal in [CustomEventConversionGoal(customEventName="customer_created"), None]:
                    response = WebStatsTableQueryRunner(
                        team=self.team,
                        query=WebStatsTableQuery(
                            dateRange=DateRange(date_from="2024-01-01", date_to="2024-01-02"),
                            breakdownBy=WebStatsBreakdown.PAGE,
                            conversionGoal=goal,
                            includeTrafficMetrics=True,
                            properties=[],
                        ),
                        modifiers=HogQLQueryModifiers(
                            sessionTableVersion=SessionTableVersion.V2,
                            useWebAnalyticsPreAggregatedTables=preaggregated,
                        ),
                    ).calculate()
                    assert response.columns is not None
                    row = dict(zip(response.columns, next(row for row in response.results if row[0] == "/page1")))
                    assert row["context.columns.visitors"][0] == 1
                    assert row["context.columns.sessions"][0] == 1
                    assert row["context.columns.views"][0] == 1
                    if goal:
                        assert row["context.columns.unique_conversions"][0] == 3
                        assert row["context.columns.conversion_rate"][0] == 3

    @parameterized.expand(
        [
            ("join_bounce", False, False, False),
            ("join_time", False, False, True),
            ("no_join_bounce", True, False, False),
            ("no_join_time", True, False, True),
            ("session_set_bounce", False, True, False),
            ("session_set_time", False, True, True),
        ]
    )
    def test_page_traffic_metrics_with_engagement(
        self, _name: str, no_join: bool, session_set: bool, average_time: bool
    ) -> None:
        with (
            override_settings(
                WEB_ANALYTICS_NO_JOIN_TEAM_IDS=[self.team.pk] if no_join else [],
                WEB_ANALYTICS_SESSION_ID_SET_TEAM_IDS=[self.team.pk] if session_set else [],
            ),
            time_machine.travel("2024-01-02T00:00:00Z", tick=False),
        ):
            response = WebStatsTableQueryRunner(
                team=self.team,
                query=WebStatsTableQuery(
                    dateRange=DateRange(date_from="2024-01-01", date_to="2024-01-02"),
                    compareFilter=CompareFilter(compare=True),
                    breakdownBy=WebStatsBreakdown.PAGE,
                    includeTrafficMetrics=True,
                    includeBounceRate=True,
                    includeAvgTimeOnPage=average_time,
                    properties=[EventPropertyFilter(key="$pathname", value="/page1")] if session_set else [],
                ),
                modifiers=HogQLQueryModifiers(
                    sessionTableVersion=SessionTableVersion.V2, useWebAnalyticsPreAggregatedTables=False
                ),
            ).calculate()
            assert response.columns is not None
            row = dict(zip(response.columns, next(row for row in response.results if row[0] == "/page1")))
            assert row["context.columns.sessions"] == (1, 0)
            assert row["context.columns.visitors"] == (1, 0)
            assert row["context.columns.views"] == (1, 0)
            assert row["context.columns.bounce_rate"][0] == 1
            if average_time:
                assert "context.columns.avg_time_on_page" in row

    def test_conversion_goal_with_preaggregated_tables_bounce_style(self):
        """Test conversion goals using bounce-rate-style query pattern (alternative implementation)"""
        from products.web_analytics.backend.hogql_queries.stats_table_pre_aggregated import (
            StatsTablePreAggregatedQueryBuilder,
        )

        # Enable bounce-style query for this test
        original_flag = StatsTablePreAggregatedQueryBuilder.USE_BOUNCE_STYLE_CONVERSION_QUERY
        StatsTablePreAggregatedQueryBuilder.USE_BOUNCE_STYLE_CONVERSION_QUERY = True

        try:
            self._setup_test_data(user_prefix="bounce")

            action = Action.objects.create(
                team=self.team,
                name="Converted",
                steps_json=[
                    {
                        "event": "$pageview",
                        "url": "/page1",
                        "url_matching": "contains",
                    }
                ],
            )

            # Populate pre-aggregated stats table with visitor data
            sql = WEB_STATS_INSERT_SQL(
                date_start="2024-01-01", date_end="2024-01-02", team_ids=[self.team.pk], select_only=True
            )
            sync_execute(f"INSERT INTO web_pre_aggregated_stats {sql}")

            with time_machine.travel("2024-01-02T00:00:00Z", tick=False):
                modifiers = HogQLQueryModifiers(
                    sessionTableVersion=SessionTableVersion.V2,
                    useWebAnalyticsPreAggregatedTables=True,
                )
                query = WebStatsTableQuery(
                    dateRange=DateRange(date_from="2024-01-01", date_to="2024-01-02"),
                    breakdownBy=WebStatsBreakdown.PAGE,
                    conversionGoal=ActionConversionGoal(actionId=action.id),
                    properties=[],
                )
                runner = WebStatsTableQueryRunner(team=self.team, query=query, modifiers=modifiers)

                # Verify pre-aggregated tables can be used
                assert runner.preaggregated_query_builder.can_use_preaggregated_tables()

                # Execute the query
                response = runner.calculate()

                # Verify we get conversion data
                assert response.results is not None
                assert len(response.results) >= 2  # At least 2 pages

                # Verify columns include conversion metrics
                assert response.columns is not None
                assert "context.columns.visitors" in response.columns
                assert "context.columns.total_conversions" in response.columns
                assert "context.columns.unique_conversions" in response.columns
                assert "context.columns.conversion_rate" in response.columns

                # Find the row with the conversion
                page1_row = next((row for row in response.results if row[0] == "/page1"), None)
                assert page1_row is not None
                visitors_current, visitors_previous = page1_row[1]
                total_conversions_current, total_conversions_previous = page1_row[2]
                unique_conversions_current, unique_conversions_previous = page1_row[3]
                conversion_rate_current, conversion_rate_previous = page1_row[4]

                # Page1 should have at least 1 visitor and 1 conversion
                assert visitors_current >= 1
                assert total_conversions_current >= 1.0
                assert unique_conversions_current >= 1.0
                assert conversion_rate_current > 0

                # Page 2 should have no conversions
                page2_row = next((row for row in response.results if row[0] == "/page2"), None)
                assert page2_row is not None

                visitors_current, visitors_previous = page2_row[1]
                total_conversions_current, total_conversions_previous = page2_row[2]
                unique_conversions_current, unique_conversions_previous = page2_row[3]
                conversion_rate_current, conversion_rate_previous = page2_row[4]

                # Page2 should have visitors but no conversions
                assert visitors_current >= 1
                assert total_conversions_current == 0.0
                assert unique_conversions_current == 0.0
                assert conversion_rate_current == 0.0
        finally:
            # Restore original flag value
            StatsTablePreAggregatedQueryBuilder.USE_BOUNCE_STYLE_CONVERSION_QUERY = original_flag
