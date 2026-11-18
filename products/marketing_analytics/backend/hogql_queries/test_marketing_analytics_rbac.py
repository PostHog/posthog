from posthog.test.base import APIBaseTest

from parameterized import parameterized
from rest_framework import status

from posthog.schema import DateRange, MarketingAnalyticsAggregatedQuery, MarketingAnalyticsSearchQuery

from posthog.constants import AvailableFeature

from products.access_control.backend.facade.user_access_control import UserAccessControlError
from products.access_control.backend.models.access_control import AccessControl
from products.marketing_analytics.backend.hogql_queries.marketing_analytics_aggregated_query_runner import (
    MarketingAnalyticsAggregatedQueryRunner,
)
from products.marketing_analytics.backend.hogql_queries.marketing_search_query_runner import (
    MarketingAnalyticsSearchQueryRunner,
)

ACCESS_CASES = [
    ("default", None, None, True),
    ("marketing_viewer", "marketing_analytics", "viewer", True),
    ("marketing_none", "marketing_analytics", "none", False),
    ("web_analytics_none", "web_analytics", "none", True),
]

RUNNERS = [
    (
        "aggregated",
        lambda team: MarketingAnalyticsAggregatedQueryRunner(
            team=team, query=MarketingAnalyticsAggregatedQuery(dateRange=DateRange(date_from="-7d"), properties=[])
        ),
    ),
    (
        "search",
        lambda team: MarketingAnalyticsSearchQueryRunner(
            team=team, query=MarketingAnalyticsSearchQuery(dateRange=DateRange(date_from="-7d"), sources=[])
        ),
    ),
]


class TestMarketingAnalyticsRBAC(APIBaseTest):
    def _grant(self, resource: str | None, access_level: str | None) -> None:
        if resource is not None:
            AccessControl.objects.create(team=self.team, resource=resource, access_level=access_level)
        self.organization.available_product_features = [{"key": AvailableFeature.ACCESS_CONTROL}]
        self.organization.save()

    @parameterized.expand(
        [
            (f"{runner_name}_{case_name}", build_runner, resource, access_level, has_access)
            for runner_name, build_runner in RUNNERS
            for case_name, resource, access_level, has_access in ACCESS_CASES
        ]
    )
    def test_validate_query_runner_access(
        self, _name: str, build_runner, resource: str | None, access_level: str | None, has_access: bool
    ) -> None:
        self._grant(resource, access_level)
        runner = build_runner(self.team)

        if has_access:
            assert runner.validate_query_runner_access(self.user)
        else:
            with self.assertRaises(UserAccessControlError):
                runner.validate_query_runner_access(self.user)

    @parameterized.expand(
        [
            ("marketing_none", "marketing_analytics", "none", status.HTTP_403_FORBIDDEN),
            ("marketing_viewer", "marketing_analytics", "viewer", status.HTTP_200_OK),
            ("web_analytics_none", "web_analytics", "none", status.HTTP_200_OK),
        ]
    )
    def test_viewset_follows_marketing_analytics_access(
        self, _name: str, resource: str, access_level: str, expected_status: int
    ) -> None:
        self._grant(resource, access_level)

        response = self.client.get(f"/api/projects/{self.team.pk}/marketing_analytics/conversion_goals")

        assert response.status_code == expected_status, response.content
