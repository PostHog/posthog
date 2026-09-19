from posthog.test.base import BaseTest

from parameterized import parameterized
from rest_framework.exceptions import ValidationError

from posthog.schema import Breakdown, BreakdownFilter, RetentionFilter, RetentionQuery

from products.product_analytics.backend.hogql_queries.retention.retention_query_runner import RetentionQueryRunner


class TestRetentionBreakdownConversion(BaseTest):
    def _runner(self, breakdown_filter: BreakdownFilter) -> RetentionQueryRunner:
        return RetentionQueryRunner(
            query=RetentionQuery(retentionFilter=RetentionFilter(), breakdownFilter=breakdown_filter),
            team=self.team,
        )

    @parameterized.expand(
        [
            ("plain_value", "$browser"),
            ("single_item_list", ["$browser"]),
        ]
    )
    def test_property_breakdown_converts_to_one_breakdown(self, _name: str, breakdown: str | list[str]) -> None:
        runner = self._runner(BreakdownFilter(breakdown=breakdown, breakdown_type="event"))

        assert runner.query.breakdownFilter is not None
        assert runner.query.breakdownFilter.breakdowns == [Breakdown(type="event", property="$browser")]

    def test_several_property_values_raise_a_validation_error(self) -> None:
        with self.assertRaises(ValidationError) as context:
            self._runner(BreakdownFilter(breakdown=["$browser", "$os"], breakdown_type="event"))

        self.assertIn("Retention supports one breakdown property at a time.", str(context.exception))
