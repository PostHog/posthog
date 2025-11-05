from posthog.temporal.data_imports.sources.stripe.constants import SUBSCRIPTION_RESOURCE_NAME

from products.revenue_analytics.backend.views.schemas.subscription import SCHEMA as SUBSCRIPTION_SCHEMA
from products.revenue_analytics.backend.views.sources.stripe.subscription import build
from products.revenue_analytics.backend.views.sources.test.stripe.base import StripeSourceBaseTest


class TestSubscriptionStripeBuilder(StripeSourceBaseTest):
    def setUp(self):
        super().setUp()
        self.setup_stripe_external_data_source()

    def test_build_subscription_query_with_subscription_schema(self):
        """Test building subscription query when subscription schema exists."""
        # Setup with only subscription schema
        self.setup_stripe_external_data_source(schemas=[SUBSCRIPTION_RESOURCE_NAME])
        subscription_table = self.get_stripe_table_by_schema_name(SUBSCRIPTION_RESOURCE_NAME)

        # Test the query structure
        query = build(self.stripe_handle)
        self.assertQueryContainsFields(query.query, SUBSCRIPTION_SCHEMA)
        self.assertBuiltQueryStructure(query, str(subscription_table.id), f"stripe.{self.external_data_source.prefix}")

        # Print and snapshot the generated HogQL query
        query_sql = query.query.to_hogql()
        self.assertQueryMatchesSnapshot(query_sql, replace_all_numbers=True)

    def test_build_with_no_subscription_schema(self):
        """Test that build returns view even when no subscription schema exists."""
        # Setup without subscription schema
        self.setup_stripe_external_data_source(schemas=[])

        # Test the query structure
        query = build(self.stripe_handle)
        self.assertQueryContainsFields(query.query, SUBSCRIPTION_SCHEMA)
        self.assertBuiltQueryStructure(
            query,
            str(self.stripe_handle.source.id),  # type: ignore
            f"stripe.{self.external_data_source.prefix}",
            expected_test_comments="no_schema",
        )

        # Print and snapshot the generated HogQL query
        query_sql = query.query.to_hogql()
        self.assertQueryMatchesSnapshot(query_sql, replace_all_numbers=True)

    def test_build_with_subscription_schema_but_no_table(self):
        """Test that build returns view even when subscription schema exists but has no table."""
        # Setup with subscription schema but no table
        self.setup_stripe_external_data_source_with_specific_schemas(
            [{"name": SUBSCRIPTION_RESOURCE_NAME, "table_name": None}]
        )

        # Set the table to None to simulate missing table
        subscription_schema = self.get_stripe_schema_by_name(SUBSCRIPTION_RESOURCE_NAME)
        subscription_schema.table = None

        # Test the query structure
        query = build(self.stripe_handle)
        self.assertQueryContainsFields(query.query, SUBSCRIPTION_SCHEMA)
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
        """Test that build returns none when source is None."""
        handle = self.create_stripe_handle_without_source()

        with self.assertRaises(ValueError):
            build(handle)

    def test_subscription_query_contains_required_fields(self):
        """Test that the generated query contains all required subscription fields."""
        self.setup_stripe_external_data_source(schemas=[SUBSCRIPTION_RESOURCE_NAME])

        query = build(self.stripe_handle)
        query_sql = query.query.to_hogql()

        # Check for specific fields in the query based on the subscription schema
        self.assertIn("id", query_sql)
        self.assertIn("source_label", query_sql)

        # Check that source_label contains the expected prefix
        expected_prefix = f"stripe.{self.external_data_source.prefix}"
        self.assertIn(f"'{expected_prefix}'", query_sql)
