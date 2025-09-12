from posthog.temporal.data_imports.sources.stripe.constants import PRODUCT_RESOURCE_NAME

from products.revenue_analytics.backend.views.schemas.product import SCHEMA as PRODUCT_SCHEMA
from products.revenue_analytics.backend.views.sources.stripe.product import build
from products.revenue_analytics.backend.views.sources.test.stripe.base import StripeSourceBaseTest


class TestProductStripeBuilder(StripeSourceBaseTest):
    def setUp(self):
        super().setUp()
        self.setup_stripe_external_data_source()

    def test_build_product_query_with_product_schema(self):
        """Test building product query when product schema exists."""
        # Setup with only product schema
        self.setup_stripe_external_data_source(schemas=[PRODUCT_RESOURCE_NAME])

        queries = list(build(self.stripe_handle))

        # Should build one query for the product schema
        self.assertEqual(len(queries), 1)

        product_query = queries[0]
        product_table = self.get_stripe_table_by_schema_name(PRODUCT_RESOURCE_NAME)

        # Test the query structure
        self.assertQueryContainsFields(product_query.query, PRODUCT_SCHEMA)
        self.assertBuiltQueryStructure(
            product_query, str(product_table.id), f"stripe.{self.external_data_source.prefix}"
        )

        # Print and snapshot the generated HogQL query
        query_sql = product_query.query.to_hogql()
        self.assertQueryMatchesSnapshot(query_sql, replace_all_numbers=True)

    def test_build_with_no_product_schema(self):
        """Test that build returns view even when no product schema exists."""
        # Setup without product schema
        self.setup_stripe_external_data_source(schemas=[])

        queries = list(build(self.stripe_handle))

        # Should return no queries
        self.assertEqual(len(queries), 1)
        product_query = queries[0]

        # Test the query structure
        self.assertQueryContainsFields(product_query.query, PRODUCT_SCHEMA)
        self.assertBuiltQueryStructure(
            product_query,
            f"stripe.{self.external_data_source.prefix}.no_source",
            f"stripe.{self.external_data_source.prefix}",
        )

        # Print and snapshot the generated HogQL query
        query_sql = product_query.query.to_hogql()
        self.assertQueryMatchesSnapshot(query_sql, replace_all_numbers=True)

    def test_build_with_product_schema_but_no_table(self):
        """Test that build returns view even when product schema exists but has no table."""
        # Setup with product schema but no table
        self.setup_stripe_external_data_source_with_specific_schemas(
            [{"name": PRODUCT_RESOURCE_NAME, "table_name": None}]
        )

        # Set the table to None to simulate missing table
        product_schema = self.get_stripe_schema_by_name(PRODUCT_RESOURCE_NAME)
        product_schema.table = None

        queries = list(build(self.stripe_handle))

        # Should return no queries
        self.assertEqual(len(queries), 1)
        product_query = queries[0]

        # Test the query structure
        self.assertQueryContainsFields(product_query.query, PRODUCT_SCHEMA)
        self.assertBuiltQueryStructure(
            product_query,
            f"stripe.{self.external_data_source.prefix}.no_table",
            f"stripe.{self.external_data_source.prefix}",
        )

        # Print and snapshot the generated HogQL query
        query_sql = product_query.query.to_hogql()
        self.assertQueryMatchesSnapshot(query_sql, replace_all_numbers=True)

    def test_build_with_no_source(self):
        """Test that build returns none when source is None."""
        handle = self.create_stripe_handle_without_source()

        queries = list(build(handle))

        # Should return no queries
        self.assertEqual(len(queries), 0)

    def test_product_query_contains_required_fields(self):
        """Test that the generated query contains all required product fields."""
        self.setup_stripe_external_data_source(schemas=[PRODUCT_RESOURCE_NAME])

        queries = list(build(self.stripe_handle))
        product_query = queries[0]

        query_sql = product_query.query.to_hogql()

        # Check for specific fields in the query
        self.assertIn("id", query_sql)
        self.assertIn("source_label", query_sql)
        self.assertIn("name", query_sql)

        # Check that source_label contains the expected prefix
        expected_prefix = f"stripe.{self.external_data_source.prefix}"
        self.assertIn(f"'{expected_prefix}'", query_sql)
