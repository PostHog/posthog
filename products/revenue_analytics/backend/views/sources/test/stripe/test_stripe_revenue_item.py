from typing import Any

from posthog.test.base import snapshot_clickhouse_queries

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.temporal.data_imports.sources.stripe.constants import (
    CHARGE_RESOURCE_NAME,
    CUSTOMER_RESOURCE_NAME,
    INVOICE_RESOURCE_NAME,
    PRODUCT_RESOURCE_NAME,
    SUBSCRIPTION_RESOURCE_NAME,
)

from products.revenue_analytics.backend.views.schemas.revenue_item import SCHEMA as REVENUE_ITEM_SCHEMA
from products.revenue_analytics.backend.views.sources.stripe.revenue_item import (
    _calculate_months_for_period as calculate_months_for_period,
    build,
)
from products.revenue_analytics.backend.views.sources.test.stripe.base import StripeSourceBaseTest


class TestRevenueItemStripeBuilder(StripeSourceBaseTest):
    def setUp(self):
        super().setUp()
        self.setup_stripe_external_data_source()

    def test_build_revenue_item_query_with_all_schemas(self):
        """Test building revenue item query when all required schemas exist."""
        # Setup with all relevant schemas for revenue items
        schemas = [
            CHARGE_RESOURCE_NAME,
            CUSTOMER_RESOURCE_NAME,
            INVOICE_RESOURCE_NAME,
            PRODUCT_RESOURCE_NAME,
            SUBSCRIPTION_RESOURCE_NAME,
        ]
        self.setup_stripe_external_data_source(schemas=schemas)

        queries = list(build(self.stripe_handle))

        # Should build queries for revenue items
        self.assertGreater(len(queries), 0)

        revenue_query = queries[0]
        revenue_table = self.get_stripe_table_by_schema_name(INVOICE_RESOURCE_NAME)

        # Test the query structure
        self.assertQueryContainsFields(revenue_query.query, REVENUE_ITEM_SCHEMA)
        self.assertBuiltQueryStructure(
            revenue_query, str(revenue_table.id), f"stripe.{self.external_data_source.prefix}"
        )

        # Print and snapshot the generated HogQL query
        query_sql = revenue_query.query.to_hogql()
        self.assertQueryMatchesSnapshot(query_sql, replace_all_numbers=True)

    def test_build_revenue_item_query_with_minimal_schemas(self):
        """Test building revenue item query with minimal required schemas."""
        # Setup with minimal schemas that might be required
        schemas = [INVOICE_RESOURCE_NAME]
        self.setup_stripe_external_data_source(schemas=schemas)

        queries = list(build(self.stripe_handle))

        # Print and snapshot for minimal case
        if queries:
            query_sql = queries[0].query.to_hogql()
            self.assertQueryMatchesSnapshot(query_sql, replace_all_numbers=True)

    def test_build_with_subscription_schemas_only(self):
        """Test building revenue item query with subscription-related schemas only."""
        # Setup with subscription schemas
        schemas = [
            SUBSCRIPTION_RESOURCE_NAME,
            PRODUCT_RESOURCE_NAME,
        ]
        self.setup_stripe_external_data_source(schemas=schemas)

        queries = list(build(self.stripe_handle))

        # Print and snapshot for subscription case
        if queries:
            query_sql = queries[0].query.to_hogql()
            self.assertQueryMatchesSnapshot(query_sql, replace_all_numbers=True)

    def test_build_with_no_relevant_schemas(self):
        """Test that build returns view even when no relevant schemas exist."""
        # Setup without any relevant schemas
        self.setup_stripe_external_data_source(schemas=[])

        queries = list(build(self.stripe_handle))

        # Should return no queries
        self.assertEqual(len(queries), 1)
        revenue_query = queries[0]
        self.assertQueryContainsFields(revenue_query.query, REVENUE_ITEM_SCHEMA)
        self.assertBuiltQueryStructure(
            revenue_query,
            f"stripe.{self.external_data_source.prefix}.no_source",
            f"stripe.{self.external_data_source.prefix}",
        )
        # Print and snapshot the generated HogQL query
        self.assertQueryMatchesSnapshot(revenue_query.query.to_hogql(), replace_all_numbers=True)

    def test_build_with_no_source(self):
        """Test that build returns none when source is None."""
        handle = self.create_stripe_handle_without_source()

        queries = list(build(handle))

        # Should return no queries
        self.assertEqual(len(queries), 0)

    def test_revenue_item_query_contains_required_fields(self):
        """Test that the generated query contains all required revenue item fields."""
        # Setup with comprehensive schemas
        schemas = [
            CHARGE_RESOURCE_NAME,
            CUSTOMER_RESOURCE_NAME,
            INVOICE_RESOURCE_NAME,
            PRODUCT_RESOURCE_NAME,
        ]
        self.setup_stripe_external_data_source(schemas=schemas)

        queries = list(build(self.stripe_handle))

        if queries:
            revenue_query = queries[0]
            query_sql = revenue_query.query.to_hogql()

            # Check for specific fields in the query based on the revenue item schema
            self.assertIn("id", query_sql)
            self.assertIn("source_label", query_sql)

            # Check that source_label contains the expected prefix
            expected_prefix = f"stripe.{self.external_data_source.prefix}"
            self.assertIn(f"'{expected_prefix}'", query_sql)

    def test_revenue_item_query_with_currency_conversion(self):
        """Test revenue item query includes currency conversion logic."""
        # Set team base currency to test conversion
        self.set_team_base_currency("EUR")

        schemas = [CHARGE_RESOURCE_NAME, INVOICE_RESOURCE_NAME]
        self.setup_stripe_external_data_source(schemas=schemas)

        queries = list(build(self.stripe_handle))

        if queries:
            query_sql = queries[0].query.to_hogql()

            # Check for currency-related fields/functions
            # The specific implementation may vary
            self.assertIn("currency", query_sql.lower())

            # Print and snapshot for currency conversion case
            self.assertQueryMatchesSnapshot(query_sql, replace_all_numbers=True)

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
        response: list[list[Any]] = execute_hogql_query(
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
        response: list[list[Any]] = execute_hogql_query(
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
