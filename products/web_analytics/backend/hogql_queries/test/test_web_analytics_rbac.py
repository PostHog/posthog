from posthog.test.base import APIBaseTest

from parameterized import parameterized

from posthog.schema import (
    ActorsQuery,
    DateRange,
    MarketingAnalyticsActorsBreakdown,
    MarketingAnalyticsActorsQuery,
    MarketingAnalyticsTableQuery,
    WebOverviewQuery,
)

from posthog.constants import AvailableFeature
from posthog.hogql_queries.actors_query_runner import ActorsQueryRunner
from posthog.hogql_queries.query_runner import ExecutionMode

from products.access_control.backend.facade.user_access_control import UserAccessControlError
from products.access_control.backend.models.access_control import AccessControl
from products.web_analytics.backend.hogql_queries.web_overview import WebOverviewQueryRunner


class TestWebAnalyticsRBAC(APIBaseTest):
    @parameterized.expand([ExecutionMode.CALCULATE_BLOCKING_ALWAYS, ExecutionMode.CACHE_ONLY_NEVER_CALCULATE])
    def test_marketing_actors_check_access_before_calculation_or_cache(self, mode: ExecutionMode) -> None:
        AccessControl.objects.create(team=self.team, resource="web_analytics", access_level="none")
        assert self.organization.available_product_features is not None
        self.organization.available_product_features.append({"key": AvailableFeature.ACCESS_CONTROL})
        self.organization.save()
        runner = ActorsQueryRunner(
            team=self.team,
            query=ActorsQuery(
                source=MarketingAnalyticsActorsQuery(
                    source=MarketingAnalyticsTableQuery(dateRange=DateRange(date_from="-7d"), properties=[]),
                    conversionGoalId="purchases",
                    breakdown=MarketingAnalyticsActorsBreakdown(value="winter-sale", source="google"),
                )
            ),
        )
        with self.assertRaises(UserAccessControlError):
            runner.run(execution_mode=mode, user=self.user)

    def test_validate_query_runner_access_with_viewer(self):
        query = WebOverviewQuery(
            dateRange=DateRange(date_from="2024-01-01", date_to="2024-01-31"),
            properties=[],
        )
        runner = WebOverviewQueryRunner(team=self.team, query=query)

        # By default, users should have access
        assert runner.validate_query_runner_access(self.user)

    def test_validate_query_runner_access_with_editor(self):
        AccessControl.objects.create(team=self.team, resource="web_analytics", access_level="editor")
        self.organization.available_product_features.append({"key": AvailableFeature.ACCESS_CONTROL})  # type: ignore[union-attr]
        self.organization.save()

        query = WebOverviewQuery(
            dateRange=DateRange(date_from="2024-01-01", date_to="2024-01-31"),
            properties=[],
        )
        runner = WebOverviewQueryRunner(team=self.team, query=query)

        assert runner.validate_query_runner_access(self.user)

    def test_validate_query_runner_access_without_access(self):
        AccessControl.objects.create(team=self.team, resource="web_analytics", access_level="none")
        self.organization.available_product_features.append({"key": AvailableFeature.ACCESS_CONTROL})  # type: ignore[union-attr]
        self.organization.save()

        query = WebOverviewQuery(
            dateRange=DateRange(date_from="2024-01-01", date_to="2024-01-31"),
            properties=[],
        )
        runner = WebOverviewQueryRunner(team=self.team, query=query)

        with self.assertRaises(UserAccessControlError):
            runner.validate_query_runner_access(self.user)

    def test_validate_query_runner_access_with_manager(self):
        AccessControl.objects.create(team=self.team, resource="web_analytics", access_level="manager")
        self.organization.available_product_features.append({"key": AvailableFeature.ACCESS_CONTROL})  # type: ignore[union-attr]
        self.organization.save()

        query = WebOverviewQuery(
            dateRange=DateRange(date_from="2024-01-01", date_to="2024-01-31"),
            properties=[],
        )
        runner = WebOverviewQueryRunner(team=self.team, query=query)

        assert runner.validate_query_runner_access(self.user)
