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

        queries = list(build(self.stripe_handle))

        # Should build one query for the customer schema
        self.assertEqual(len(queries), 1)

        customer_query = queries[0]
        customer_table = self.get_stripe_table_by_schema_name(CUSTOMER_RESOURCE_NAME)

        # Test the query structure
        self.assertQueryContainsFields(customer_query.query, CUSTOMER_SCHEMA)
        self.assertBuiltQueryStructure(
            customer_query, str(customer_table.id), f"stripe.{self.external_data_source.prefix}"
        )

        # Print and snapshot the generated HogQL query
        query_sql = customer_query.query.to_hogql()
        self.assertQueryMatchesSnapshot(query_sql, replace_all_numbers=True)

    def test_build_customer_query_with_customer_and_invoice_schemas(self):
        """Test building customer query when both customer and invoice schemas exist."""
        # Setup with both customer and invoice schemas
        self.setup_stripe_external_data_source(schemas=[CUSTOMER_RESOURCE_NAME, INVOICE_RESOURCE_NAME])

        queries = list(build(self.stripe_handle))

        # Should build one query for the customer schema
        self.assertEqual(len(queries), 1)

        customer_query = queries[0]
        customer_table = self.get_stripe_table_by_schema_name(CUSTOMER_RESOURCE_NAME)

        # Test the query structure
        self.assertQueryContainsFields(customer_query.query, CUSTOMER_SCHEMA)
        self.assertBuiltQueryStructure(
            customer_query, str(customer_table.id), f"stripe.{self.external_data_source.prefix}"
        )

        # Print and snapshot the generated HogQL query (should be different from customer-only)
        query_sql = customer_query.query.to_hogql()
        self.assertQueryMatchesSnapshot(query_sql, replace_all_numbers=True)

    def test_build_with_no_customer_schema(self):
        """Test that build returns view even when no customer schema exists."""
        # Setup without customer schema
        self.setup_stripe_external_data_source(schemas=[INVOICE_RESOURCE_NAME])

        queries = list(build(self.stripe_handle))

        # Should return no queries
        self.assertEqual(len(queries), 1)
        customer_query = queries[0]
        self.assertQueryContainsFields(customer_query.query, CUSTOMER_SCHEMA)
        self.assertBuiltQueryStructure(
            customer_query,
            f"stripe.{self.external_data_source.prefix}.no_source",
            f"stripe.{self.external_data_source.prefix}",
        )

        # Print and snapshot the generated HogQL query
        self.assertQueryMatchesSnapshot(customer_query.query.to_hogql(), replace_all_numbers=True)

    def test_build_with_customer_schema_but_no_table(self):
        """Test that build returns view even when customer schema exists but has no table."""
        # Setup with customer schema but no table
        self.setup_stripe_external_data_source_with_specific_schemas(
            [{"name": CUSTOMER_RESOURCE_NAME, "table_name": None}]
        )

        # Set the table to None to simulate missing table
        customer_schema = self.get_stripe_schema_by_name(CUSTOMER_RESOURCE_NAME)
        customer_schema.table = None

        queries = list(build(self.stripe_handle))

        # Should return no queries
        self.assertEqual(len(queries), 1)
        customer_query = queries[0]

        # Test the query structure
        self.assertQueryContainsFields(customer_query.query, CUSTOMER_SCHEMA)
        self.assertBuiltQueryStructure(
            customer_query,
            f"stripe.{self.external_data_source.prefix}.no_table",
            f"stripe.{self.external_data_source.prefix}",
        )

        # Print and snapshot the generated HogQL query
        query_sql = customer_query.query.to_hogql()
        self.assertQueryMatchesSnapshot(query_sql, replace_all_numbers=True)

    def test_build_with_no_source(self):
        """Test that build returns empty when source is None."""
        handle = self.create_stripe_handle_without_source()

        queries = list(build(handle))

        # Should return no queries
        self.assertEqual(len(queries), 0)

    def test_customer_query_contains_required_fields(self):
        """Test that the generated query contains all required customer fields."""
        self.setup_stripe_external_data_source(schemas=[CUSTOMER_RESOURCE_NAME])

        queries = list(build(self.stripe_handle))
        customer_query = queries[0]

        query_sql = customer_query.query.to_hogql()

        # Check for specific fields in the query based on the customer schema
        self.assertIn("id", query_sql)
        self.assertIn("source_label", query_sql)

        # Check that source_label contains the expected prefix
        expected_prefix = f"stripe.{self.external_data_source.prefix}"
        self.assertIn(f"'{expected_prefix}'", query_sql)
