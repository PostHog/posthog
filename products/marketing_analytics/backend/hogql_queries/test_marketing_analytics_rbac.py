from posthog.test.base import APIBaseTest

from parameterized import parameterized

from posthog.schema import DateRange, MarketingAnalyticsAggregatedQuery

from posthog.constants import AvailableFeature

from products.access_control.backend.facade.user_access_control import UserAccessControlError
from products.access_control.backend.models.access_control import AccessControl
from products.marketing_analytics.backend.hogql_queries.marketing_analytics_aggregated_query_runner import (
    MarketingAnalyticsAggregatedQueryRunner,
)


class TestMarketingAnalyticsRBAC(APIBaseTest):
    @parameterized.expand(
        [
            ("default", None, None, True),
            ("marketing_viewer", "marketing_analytics", "viewer", True),
            ("marketing_none", "marketing_analytics", "none", False),
            ("web_analytics_none", "web_analytics", "none", True),
        ]
    )
    def test_validate_query_runner_access(
        self, _name: str, resource: str | None, access_level: str | None, has_access: bool
    ) -> None:
        if resource is not None:
            AccessControl.objects.create(team=self.team, resource=resource, access_level=access_level)
        self.organization.available_product_features = [{"key": AvailableFeature.ACCESS_CONTROL}]
        self.organization.save()

        runner = MarketingAnalyticsAggregatedQueryRunner(
            team=self.team,
            query=MarketingAnalyticsAggregatedQuery(dateRange=DateRange(date_from="-7d"), properties=[]),
        )

        if has_access:
            assert runner.validate_query_runner_access(self.user)
        else:
            with self.assertRaises(UserAccessControlError):
                runner.validate_query_runner_access(self.user)
