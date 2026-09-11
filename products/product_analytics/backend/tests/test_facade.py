from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils.timezone import now

from parameterized import parameterized

from posthog.schema import TrendsQueryResponse

from posthog.clickhouse.query_tagging import reset_query_tags, tag_queries
from posthog.models.team import Team

from products.product_analytics.backend.facade.api import insight_variables_for_team, record_insight_view
from products.product_analytics.backend.facade.queries import run_cached_trends_query
from products.product_analytics.backend.models.insight import Insight, InsightViewed
from products.product_analytics.backend.models.insight_variable import InsightVariable


class TestInsightVariableReads(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.variable = InsightVariable.objects.create(
            team=self.team, name="Country", code_name="country", type="String"
        )

    @parameterized.expand([("root_team",), ("environment_team",)])
    def test_variables_are_visible_from_the_whole_project(self, which_team: str) -> None:
        team = self.team
        if which_team == "environment_team":
            team = Team.objects.create(organization=self.organization, project=self.project, parent_team=self.team)

        assert [variable.code_name for variable in insight_variables_for_team(team.pk)] == ["country"]

    def test_a_team_in_another_project_sees_none_of_them(self) -> None:
        other_team = Team.objects.create(organization=self.organization)

        assert insight_variables_for_team(other_team.pk) == []


class TestRecordInsightView(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.insight = Insight.objects.create(team=self.team, name="Signups")

    @parameterized.expand([("anonymous", False), ("identified", True)])
    def test_viewing_twice_moves_the_timestamp_instead_of_adding_a_row(self, _name: str, identified: bool) -> None:
        viewer = {"team_id": self.team.pk, "user_id": self.user.pk} if identified else {}

        record_insight_view(insight_id=self.insight.pk, **viewer)
        first = InsightViewed.objects.get(insight_id=self.insight.pk)
        record_insight_view(insight_id=self.insight.pk, **viewer)

        assert InsightViewed.objects.filter(insight_id=self.insight.pk).count() == 1
        assert InsightViewed.objects.get(insight_id=self.insight.pk).last_viewed_at >= first.last_viewed_at

    def test_an_anonymous_view_does_not_replace_a_users_view(self) -> None:
        InsightViewed.objects.create(team=self.team, user=self.user, insight=self.insight, last_viewed_at=now())

        record_insight_view(insight_id=self.insight.pk)

        assert InsightViewed.objects.filter(insight_id=self.insight.pk).count() == 2


class TestRunCachedTrendsQuery(BaseTest):
    def tearDown(self) -> None:
        reset_query_tags()
        super().tearDown()

    def test_returns_only_the_result_fields_exposed_by_the_facade(self) -> None:
        refreshed_at = now()
        query = {"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": "$pageview"}]}
        with (
            patch(
                "products.product_analytics.backend.hogql_queries.trends.trends_query_runner.TrendsQueryRunner"
            ) as runner_type,
            patch("posthog.clickhouse.query_tagging.get_query_tag_value", return_value="personal_api_key"),
        ):
            runner_type.return_value.run.return_value = SimpleNamespace(
                results=[{"aggregated_value": 12}], last_refresh=refreshed_at
            )

            result = run_cached_trends_query(
                query=query, team=self.team, max_execution_time_seconds=20, cache_age_seconds=900
            )

        assert result.results == [{"aggregated_value": 12}]
        assert result.last_refresh == refreshed_at
        assert runner_type.call_args.kwargs["query"] == query
        assert runner_type.call_args.kwargs["team"] == self.team
        assert runner_type.call_args.kwargs["hogql_settings"].max_execution_time == 20
        assert runner_type.return_value.is_query_service is True
        assert runner_type.return_value.run.call_args.kwargs["cache_age_seconds"] == 900
        assert (
            runner_type.return_value.run.call_args.kwargs["execution_mode"].name
            == "RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE"
        )

    def test_recalculates_a_daily_cache_entry_after_fifteen_minutes(self) -> None:
        query = {
            "kind": "TrendsQuery",
            "series": [{"kind": "EventsNode", "event": "$pageview"}],
            "dateRange": {"date_from": "-14d"},
            "interval": "day",
        }
        start = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)
        with patch(
            "products.product_analytics.backend.hogql_queries.trends.trends_query_runner.TrendsQueryRunner.calculate",
            return_value=TrendsQueryResponse(results=[{"aggregated_value": 12}]),
        ) as calculate:
            with time_machine.travel(start, tick=False):
                run_cached_trends_query(
                    query=query, team=self.team, max_execution_time_seconds=20, cache_age_seconds=6 * 60 * 60
                )
            with time_machine.travel(start + timedelta(minutes=16), tick=False):
                cached = run_cached_trends_query(
                    query=query, team=self.team, max_execution_time_seconds=20, cache_age_seconds=6 * 60 * 60
                )
                refreshed = run_cached_trends_query(
                    query=query, team=self.team, max_execution_time_seconds=20, cache_age_seconds=15 * 60
                )

        assert cached.last_refresh == start
        assert refreshed.last_refresh == start + timedelta(minutes=16)
        assert calculate.call_count == 2

    def test_personal_api_key_uses_api_limits_and_session_keeps_org_limit(self) -> None:
        query = {"kind": "TrendsQuery", "series": [{"kind": "EventsNode", "event": "$pageview"}]}
        response = TrendsQueryResponse(results=[{"aggregated_value": 12}])

        with (
            patch(
                "products.product_analytics.backend.hogql_queries.trends.trends_query_runner.TrendsQueryRunner.calculate",
                return_value=response,
            ),
            patch("posthog.hogql_queries.query_runner.get_api_team_rate_limiter") as api_limiter,
            patch("posthog.hogql_queries.query_runner.get_app_org_rate_limiter") as org_limiter,
            patch(
                "products.product_analytics.backend.hogql_queries.trends.trends_query_runner.TrendsQueryRunner._enforce_api_queries_budget"
            ) as enforce_budget,
        ):
            tag_queries(access_method="personal_api_key")
            run_cached_trends_query(query=query, team=self.team, max_execution_time_seconds=20, cache_age_seconds=900)
            api_key_team_kwargs = api_limiter.return_value.run.call_args.kwargs
            api_key_org_kwargs = org_limiter.return_value.run.call_args.kwargs
            assert api_key_team_kwargs["is_api"] is True
            assert api_key_org_kwargs["is_api"] is True
            enforce_budget.assert_called_once()

            reset_query_tags()
            run_cached_trends_query(
                query={**query, "dateRange": {"date_from": "-7d"}},
                team=self.team,
                max_execution_time_seconds=20,
                cache_age_seconds=900,
            )
            session_team_kwargs = api_limiter.return_value.run.call_args.kwargs
            session_org_kwargs = org_limiter.return_value.run.call_args.kwargs
            assert session_team_kwargs["is_api"] is False
            assert session_org_kwargs["is_api"] is False
