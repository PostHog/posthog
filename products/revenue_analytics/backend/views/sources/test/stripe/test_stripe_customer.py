from posthog.temporal.data_imports.sources.stripe.constants import CUSTOMER_RESOURCE_NAME, INVOICE_RESOURCE_NAME

from products.revenue_analytics.backend.views.schemas.customer import SCHEMA as CUSTOMER_SCHEMA
from products.revenue_analytics.backend.views.sources.stripe.customer import build
from products.revenue_analytics.backend.views.sources.test.stripe.base import StripeSourceBaseTest


class TestCustomerStripeBuilder(StripeSourceBaseTest):
    def setUp(self):
        super().setUp()
        self.setup_stripe_external_data_source()

    def test_build_customer_query_with_customer_schema(self):
        """Test building customer query when customer schema exists."""
        # Setup with only customer schema
        self.setup_stripe_external_data_source(schemas=[CUSTOMER_RESOURCE_NAME])
        customer_table = self.get_stripe_table_by_schema_name(CUSTOMER_RESOURCE_NAME)

        query = build(self.stripe_handle)

        # Test the query structure
        self.assertQueryContainsFields(query.query, CUSTOMER_SCHEMA)
        self.assertBuiltQueryStructure(query, str(customer_table.id), f"stripe.{self.external_data_source.prefix}")

        # Print and snapshot the generated HogQL query
        query_sql = query.query.to_hogql()
        self.assertQueryMatchesSnapshot(query_sql, replace_all_numbers=True)

    def test_build_customer_query_with_customer_and_invoice_schemas(self):
        """Test building customer query when both customer and invoice schemas exist."""
        # Setup with both customer and invoice schemas
        self.setup_stripe_external_data_source(schemas=[CUSTOMER_RESOURCE_NAME, INVOICE_RESOURCE_NAME])
        customer_table = self.get_stripe_table_by_schema_name(CUSTOMER_RESOURCE_NAME)

        query = build(self.stripe_handle)

        # Test the query structure
        self.assertQueryContainsFields(query.query, CUSTOMER_SCHEMA)
        self.assertBuiltQueryStructure(query, str(customer_table.id), f"stripe.{self.external_data_source.prefix}")

        # Print and snapshot the generated HogQL query (should be different from customer-only)
        query_sql = query.query.to_hogql()
        self.assertQueryMatchesSnapshot(query_sql, replace_all_numbers=True)

    def test_build_with_no_customer_schema(self):
        """Test that build returns view even when no customer schema exists."""
        # Setup without customer schema
        self.setup_stripe_external_data_source(schemas=[INVOICE_RESOURCE_NAME])

        query = build(self.stripe_handle)

        self.assertQueryContainsFields(query.query, CUSTOMER_SCHEMA)
        self.assertBuiltQueryStructure(
            query,
            str(self.stripe_handle.source.id),  # type: ignore
            f"stripe.{self.external_data_source.prefix}",
            expected_test_comments="no_schema",
        )

        # Print and snapshot the generated HogQL query
        self.assertQueryMatchesSnapshot(query.query.to_hogql(), replace_all_numbers=True)

    def test_build_with_customer_schema_but_no_table(self):
        """Test that build returns view even when customer schema exists but has no table."""
        # Setup with customer schema but no table
        self.setup_stripe_external_data_source_with_specific_schemas(
            [{"name": CUSTOMER_RESOURCE_NAME, "table_name": None}]
        )

        # Set the table to None to simulate missing table
        customer_schema = self.get_stripe_schema_by_name(CUSTOMER_RESOURCE_NAME)
        customer_schema.table = None

        query = build(self.stripe_handle)

        # Test the query structure
        self.assertQueryContainsFields(query.query, CUSTOMER_SCHEMA)
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

    def test_customer_query_contains_required_fields(self):
        """Test that the generated query contains all required customer fields."""
        self.setup_stripe_external_data_source(schemas=[CUSTOMER_RESOURCE_NAME])

        query = build(self.stripe_handle)
        query_sql = query.query.to_hogql()

        # Check for specific fields in the query based on the customer schema
        self.assertIn("id", query_sql)
        self.assertIn("source_label", query_sql)

        # Check that source_label contains the expected prefix
        expected_prefix = f"stripe.{self.external_data_source.prefix}"
        self.assertIn(f"'{expected_prefix}'", query_sql)
