from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    snapshot_clickhouse_queries,
)

from products.revenue_analytics.backend.views.revenue_analytics_invoice_item_view import calculate_months_for_period


class TestRevenueAnalyticsInvoiceItemView(ClickhouseTestMixin, APIBaseTest):
    @parameterized.expand(
        [
            # Same month
            ("2021-01-01", "2021-01-07", 1),
            ("2021-01-01", "2021-01-31", 1),
            # Adjacent months but still 1-month period
            ("2021-01-01", "2021-02-01", 1),
            ("2021-01-15", "2021-02-15", 1),
            # Multi-month periods
            ("2021-01-01", "2021-03-31", 3),
            ("2021-01-01", "2021-06-30", 6),
            ("2021-01-01", "2021-12-31", 12),
            # Cross-year periods
            ("2021-12-01", "2022-01-31", 2),
            ("2021-01-01", "2022-12-31", 24),
            # Edge cases - partial months
            ("2021-01-15", "2021-01-31", 1),
            ("2021-01-01", "2021-01-15", 1),
            ("2021-01-25", "2021-02-10", 1),
            # Leap year
            ("2020-02-01", "2020-02-29", 1),
            ("2020-01-01", "2020-12-31", 12),
            # Ever-increasing periods on limit
            ("2021-01-01", "2021-02-01", 1),
            ("2021-01-01", "2021-02-05", 1),
            ("2021-01-01", "2021-02-10", 1),
            ("2021-01-01", "2021-02-14", 1),
            ("2021-01-01", "2021-02-15", 1),
            ("2021-01-01", "2021-02-16", 2),
            ("2021-01-01", "2021-02-17", 2),
            ("2021-01-01", "2021-02-20", 2),
            ("2021-01-01", "2021-02-25", 2),
            ("2021-01-01", "2021-02-28", 2),
        ]
    )
    def test_calculate_months_for_period_parameterized(self, start_date, end_date, expected_months):
        response = execute_hogql_query(
            ast.SelectQuery(
                select=[
                    calculate_months_for_period(
                        start_timestamp=ast.Call(name="toDateTime", args=[ast.Constant(value=start_date)]),
                        end_timestamp=ast.Call(name="toDateTime", args=[ast.Constant(value=end_date)]),
                    )
                ]
            ),
            self.team,
        ).results

        assert response[0][0] == expected_months

    @snapshot_clickhouse_queries
    def test_calculate_months_query_snapshot(self):
        response = execute_hogql_query(
            ast.SelectQuery(
                select=[
                    calculate_months_for_period(
                        start_timestamp=ast.Call(name="toDateTime", args=[ast.Constant(value="2021-01-01")]),
                        end_timestamp=ast.Call(name="toDateTime", args=[ast.Constant(value="2021-01-07")]),
                    )
                ]
            ),
            self.team,
        ).results

        assert response[0][0] == 1
