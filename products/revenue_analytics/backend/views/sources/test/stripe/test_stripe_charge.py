from posthog.temporal.data_imports.sources.stripe.constants import CHARGE_RESOURCE_NAME

from products.revenue_analytics.backend.views.schemas.charge import SCHEMA as CHARGE_SCHEMA
from products.revenue_analytics.backend.views.sources.stripe.charge import build
from products.revenue_analytics.backend.views.sources.test.stripe.base import StripeSourceBaseTest


class TestChargeStripeBuilder(StripeSourceBaseTest):
    def setUp(self):
        super().setUp()
        self.setup_stripe_external_data_source()

    def test_build_charge_query_with_charge_schema(self):
        """Test building charge query when charge schema exists."""
        # Setup with only charge schema
        self.setup_stripe_external_data_source(schemas=[CHARGE_RESOURCE_NAME])

        query = build(self.stripe_handle)
        charge_table = self.get_stripe_table_by_schema_name(CHARGE_RESOURCE_NAME)

        # Test the query structure
        self.assertQueryContainsFields(query.query, CHARGE_SCHEMA)
        self.assertBuiltQueryStructure(query, str(charge_table.id), f"stripe.{self.external_data_source.prefix}")

        # Print and snapshot the generated HogQL query
        query_sql = query.query.to_hogql()
        self.assertQueryMatchesSnapshot(query_sql, replace_all_numbers=True)

    def test_build_with_no_charge_schema(self):
        """Test that build returns view even when no charge schema exists."""
        # Setup without charge schema
        self.setup_stripe_external_data_source(schemas=[])

        query = build(self.stripe_handle)

        # Test the query structure
        self.assertQueryContainsFields(query.query, CHARGE_SCHEMA)
        self.assertBuiltQueryStructure(
            query,
            str(self.stripe_handle.source.id),  # type: ignore
            f"stripe.{self.external_data_source.prefix}",
            expected_test_comments="no_schema",
        )

        # Print and snapshot the generated HogQL query
        query_sql = query.query.to_hogql()
        self.assertQueryMatchesSnapshot(query_sql, replace_all_numbers=True)

    def test_build_with_charge_schema_but_no_table(self):
        """Test that build returns view even when charge schema exists but has no table."""
        # Setup with charge schema but no table
        self.setup_stripe_external_data_source_with_specific_schemas(
            [{"name": CHARGE_RESOURCE_NAME, "table_name": None}]
        )

        # Set the table to None to simulate missing table
        charge_schema = self.get_stripe_schema_by_name(CHARGE_RESOURCE_NAME)
        charge_schema.table = None

        query = build(self.stripe_handle)

        # Test the query structure
        self.assertQueryContainsFields(query.query, CHARGE_SCHEMA)
        self.assertBuiltQueryStructure(
            query,
            str(self.stripe_handle.source.id),  # type: ignore
            f"stripe.{self.external_data_source.prefix}",
            expected_test_comments="no_table",
        )

        # Print and snapshot the generated HogQL query
        query_sql = query.query.to_hogql()
        self.assertQueryMatchesSnapshot(query_sql, replace_all_numbers=True)

    def test_build_with_no_source(self):
        """Test that build returns empty when source is None."""
        handle = self.create_stripe_handle_without_source()

        with self.assertRaises(ValueError):
            build(handle)

    def test_charge_query_currency_conversion(self):
        """Test that charge query includes currency conversion logic."""
        # Set team base currency to test conversion
        self.set_team_base_currency("EUR")

        self.setup_stripe_external_data_source(schemas=[CHARGE_RESOURCE_NAME])

        query = build(self.stripe_handle)
        query_sql = query.query.to_hogql()

        # Check for currency conversion functions in the query
        # The specific implementation may vary, but should include conversion logic
        self.assertIn("currency", query_sql)
        self.assertIn("EUR", query_sql)

        # Print and snapshot for currency conversion case
        self.assertQueryMatchesSnapshot(query_sql, replace_all_numbers=True)
