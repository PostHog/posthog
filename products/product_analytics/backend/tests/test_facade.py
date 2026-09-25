from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db import connection, transaction
from django.utils.timezone import now

from parameterized import parameterized

from posthog.schema import TrendsQueryResponse

from posthog.clickhouse.query_tagging import reset_query_tags, tag_queries
from posthog.models.team import Team

from products.product_analytics.backend.facade.api import (
    insight_variables_for_team,
    insights_including_soft_deleted_for_team,
    record_insight_view,
)
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


class TestInsightViewedCompatibility(BaseTest):
    def test_context_fields_default_to_unattributed_and_history_writes_are_monotonic(self) -> None:
        from products.product_analytics.backend.facade.api import record_insight_views

        insight = Insight.objects.create(team=self.team)
        latest = now()
        for at in [latest, latest - timedelta(days=1)]:
            record_insight_views(
                team_id=self.team.pk, user_id=self.user.pk, last_viewed_at_by_insight_id={insight.pk: at}
            )
        row = InsightViewed.objects.get(insight=insight)
        assert row.source == "" and row.dashboard_id is None
        assert row.last_viewed_at == latest

    def test_readers_deduplicate_future_contexts_and_legacy_writes_do_not_renew_them(self) -> None:
        from products.product_analytics.backend.facade.api import (
            recent_viewers_by_insight,
            recently_viewed_insights,
            record_insight_views,
        )

        insight = Insight.objects.create(team=self.team)
        earlier = now() - timedelta(days=1)
        record_insight_views(
            team_id=self.team.pk, user_id=self.user.pk, last_viewed_at_by_insight_id={insight.pk: earlier}
        )
        # Emulate the later constraint migration inside a rollback-only test transaction.
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
                cursor.execute("ALTER TABLE posthog_insightviewed DROP CONSTRAINT posthog_unique_insightviewed")
                cursor.execute(
                    "CREATE UNIQUE INDEX test_insightviewed_context_unique ON posthog_insightviewed (COALESCE(team_id, 0), COALESCE(user_id, 0), insight_id, source, COALESCE(dashboard_id, 0))"
                )
            context = InsightViewed.objects.create(
                team=self.team, user=self.user, insight=insight, source="mcp", last_viewed_at=earlier
            )
            latest = now()
            record_insight_views(
                team_id=self.team.pk, user_id=self.user.pk, last_viewed_at_by_insight_id={insight.pk: latest}
            )
            assert InsightViewed.objects.filter(insight=insight, source="").count() == 1
            context.refresh_from_db()
            assert context.last_viewed_at == earlier
            recent = recently_viewed_insights(team_id=self.team.pk, user_id=self.user.pk, limit=1)
            assert [item.pk for item in recent] == [insight.pk]
            assert recent[0].last_viewed_at == latest
            assert recent_viewers_by_insight(
                team_id=self.team.pk, insight_ids=[insight.pk], since=earlier, max_per_insight=5
            ) == {insight.pk: [self.user]}
            transaction.set_rollback(True)


class TestInsightReads(BaseTest):
    def test_including_soft_deleted_insights_stays_scoped_to_the_team(self) -> None:
        deleted_insight = Insight.objects.create(team=self.team, name="Deleted", deleted=True)
        live_insight = Insight.objects.create(team=self.team, name="Live")
        other_team = Team.objects.create(organization=self.organization)
        other_team_insight = Insight.objects.create(team=other_team, name="Other team")

        insights = insights_including_soft_deleted_for_team(
            team_id=self.team.pk,
            insight_ids={deleted_insight.pk, live_insight.pk, other_team_insight.pk},
        )

        assert {insight.pk for insight in insights} == {deleted_insight.pk, live_insight.pk}


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
            enforce_budget.assert_not_called()

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


class TestConcurrentInsightQueryDemand(NonAtomicBaseTest):
    def test_concurrent_first_requests_create_one_context(self) -> None:
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier

        from django.db import connections

        from products.product_analytics.backend.facade.api import record_insight_query_demand

        insight = Insight.objects.create(team=self.team)
        team_id, insight_id = self.team.pk, insight.pk
        barrier = Barrier(2)

        def request() -> None:
            try:
                barrier.wait(timeout=10)
                record_insight_query_demand(team_id=team_id, insight_ids=[insight_id])
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            first, second = executor.submit(request), executor.submit(request)
            first.result(timeout=20)
            second.result(timeout=20)
        assert apps.get_model("product_analytics", "InsightQueryDemand").objects.filter(insight=insight).count() == 1


class TestInsightQueryDemandRecording(BaseTest):
    def test_demand_is_shared_across_callers_and_monotonic(self) -> None:
        from products.product_analytics.backend.facade.api import record_insight_query_demand

        demand = apps.get_model("product_analytics", "InsightQueryDemand")
        insight = Insight.objects.create(team=self.team)
        first = now()
        with time_machine.travel(first, tick=False):
            record_insight_query_demand(team_id=self.team.pk, insight_ids=[insight.pk])
        with time_machine.travel(first + timedelta(seconds=30), tick=False):
            record_insight_query_demand(team_id=self.team.pk, insight_ids=[insight.pk])
        assert demand.objects.get(insight=insight).last_requested_at == first
        with time_machine.travel(first + timedelta(minutes=2), tick=False):
            record_insight_query_demand(team_id=self.team.pk, insight_ids=[insight.pk])
        with time_machine.travel(first - timedelta(days=1), tick=False):
            record_insight_query_demand(team_id=self.team.pk, insight_ids=[insight.pk])
        assert demand.objects.get(insight=insight).last_requested_at == first + timedelta(minutes=2)
        assert not InsightViewed.objects.filter(insight=insight).exists()

    def test_dashboard_demand_is_distinct_and_requires_a_live_tile(self) -> None:
        from products.product_analytics.backend.facade.api import record_insight_query_demand

        demand = apps.get_model("product_analytics", "InsightQueryDemand")
        dashboard = apps.get_model("dashboards", "Dashboard").objects.create(team=self.team)
        insight = Insight.objects.create(team=self.team)
        record_insight_query_demand(team_id=self.team.pk, insight_ids=[insight.pk], dashboard_id=dashboard.pk)
        assert not demand.objects.exists()
        apps.get_model("dashboards", "DashboardTile").objects.create(insight=insight, dashboard=dashboard)
        record_insight_query_demand(team_id=self.team.pk, insight_ids=[insight.pk], dashboard_id=dashboard.pk)
        record_insight_query_demand(team_id=self.team.pk, insight_ids=[insight.pk])
        assert demand.objects.filter(insight=insight).count() == 2
        other_team = Team.objects.create(organization=self.organization)
        record_insight_query_demand(team_id=other_team.pk, insight_ids=[insight.pk])
        assert not demand.objects.filter(team=other_team).exists()
        insight.deleted = True
        insight.save()
        at = demand.objects.get(insight=insight, dashboard=None).last_requested_at
        with time_machine.travel(now() + timedelta(days=1), tick=False):
            record_insight_query_demand(team_id=self.team.pk, insight_ids=[insight.pk])
        assert demand.objects.get(insight=insight, dashboard=None).last_requested_at == at

    def test_recent_demand_has_throttle_grace_and_retention_is_team_scoped(self) -> None:
        from products.product_analytics.backend.facade.api import (
            prune_insight_query_demand,
            standalone_insights_with_recent_demand,
        )

        demand = apps.get_model("product_analytics", "InsightQueryDemand")
        insight = Insight.objects.create(team=self.team)
        threshold = now() - timedelta(days=7)
        row = demand.objects.create(
            team=self.team, insight=insight, last_requested_at=threshold - timedelta(seconds=59)
        )
        assert standalone_insights_with_recent_demand(
            team_id=self.team.pk, insight_ids=[insight.pk], threshold=threshold
        ) == {insight.pk}
        row.last_requested_at = threshold - timedelta(seconds=61)
        row.save()
        assert (
            standalone_insights_with_recent_demand(team_id=self.team.pk, insight_ids=[insight.pk], threshold=threshold)
            == set()
        )
        other_team = Team.objects.create(organization=self.organization)
        other_insight = Insight.objects.create(team=other_team)
        other = demand.objects.create(
            team=other_team, insight=other_insight, last_requested_at=now() - timedelta(days=31)
        )
        row.last_requested_at = now() - timedelta(days=31)
        row.save()
        prune_insight_query_demand(team_id=self.team.pk)
        assert not demand.objects.filter(pk=row.pk).exists()
        assert demand.objects.filter(pk=other.pk).exists()


