import json

from freezegun import freeze_time

from posthog.schema import CurrencyCode

from posthog.hogql.database.schema.test.base import RevenueAnalyticsTestBase
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.temporal.data_imports.sources.stripe.constants import (
    CHARGE_RESOURCE_NAME,
    CUSTOMER_RESOURCE_NAME,
    INVOICE_RESOURCE_NAME,
    SUBSCRIPTION_RESOURCE_NAME,
)

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

    def test_build_customer_query_with_all_schemas_for_metadata_resolution(self):
        self.setup_stripe_external_data_source(
            schemas=[CUSTOMER_RESOURCE_NAME, INVOICE_RESOURCE_NAME, SUBSCRIPTION_RESOURCE_NAME, CHARGE_RESOURCE_NAME]
        )
        customer_table = self.get_stripe_table_by_schema_name(CUSTOMER_RESOURCE_NAME)

        query = build(self.stripe_handle)

        self.assertQueryContainsFields(query.query, CUSTOMER_SCHEMA)
        self.assertBuiltQueryStructure(query, str(customer_table.id), f"stripe.{self.external_data_source.prefix}")

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

    def test_build_customer_query_with_customer_and_subscription_schemas(self):
        self.setup_stripe_external_data_source(schemas=[CUSTOMER_RESOURCE_NAME, SUBSCRIPTION_RESOURCE_NAME])
        customer_table = self.get_stripe_table_by_schema_name(CUSTOMER_RESOURCE_NAME)

        query = build(self.stripe_handle)

        self.assertQueryContainsFields(query.query, CUSTOMER_SCHEMA)
        self.assertBuiltQueryStructure(query, str(customer_table.id), f"stripe.{self.external_data_source.prefix}")

        query_sql = query.query.to_hogql()
        self.assertQueryMatchesSnapshot(query_sql, replace_all_numbers=True)

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


class TestCustomerStripeMetadataResolution(RevenueAnalyticsTestBase):
    """Integration tests that assert the metadata coalescing values produced by the customer view builder"""

    def setUp(self):
        super().setUp()
        self.create_sources()
        self.create_source_table("subscription")
        self.create_source_table("charge")
        self.team.base_currency = CurrencyCode.GBP.value
        self.team.save()
        self.view_name = f"stripe.posthog_test.{CUSTOMER_SCHEMA.source_suffix}"

    def _query_metadata(self) -> dict[str, dict]:
        with freeze_time(self.QUERY_TIMESTAMP):
            response = execute_hogql_query(
                parse_select(f"SELECT id, metadata FROM {self.view_name} ORDER BY id"),
                self.team,
                modifiers=self.MODIFIERS,
            )
        return {row[0]: json.loads(row[1]) for row in response.results}

    def test_metadata_resolution_from_customer(self):
        """cus_1 has posthog_person_distinct_id set directly on the customer object."""
        results = self._query_metadata()

        self.assertEqual("person_cus_1", results["cus_1"]["posthog_person_distinct_id"])
        self.assertEqual("customer", results["cus_1"]["posthog_person_distinct_id_source"])

    def test_metadata_resolution_from_subscription(self):
        """cus_2 has no distinct_id on the customer, but sub_2 has it in metadata."""
        results = self._query_metadata()

        self.assertEqual("person_cus_2", results["cus_2"]["posthog_person_distinct_id"])
        self.assertEqual("subscription::sub_2", results["cus_2"]["posthog_person_distinct_id_source"])

    def test_metadata_resolution_from_charge(self):
        """cus_3 has no distinct_id on the customer, but ch_3 has it in metadata."""
        results = self._query_metadata()

        self.assertEqual("person_cus_3", results["cus_3"]["posthog_person_distinct_id"])
        self.assertEqual("charge::ch_3", results["cus_3"]["posthog_person_distinct_id_source"])

    def test_no_metadata_when_absent_everywhere(self):
        """cus_4 has no distinct_id on customer, subscriptions, or charges."""
        results = self._query_metadata()

        self.assertNotIn("posthog_person_distinct_id", results["cus_4"])
        self.assertNotIn("posthog_person_distinct_id_source", results["cus_4"])

    def test_freshest_child_wins_across_types(self):
        """cus_5 has distinct_id on both sub_5 (Feb 2025) and ch_15 (Mar 2025).
        The charge is newer, so it should win."""
        results = self._query_metadata()

        self.assertEqual("person_cus_5_from_charge", results["cus_5"]["posthog_person_distinct_id"])
        self.assertEqual("charge::ch_15", results["cus_5"]["posthog_person_distinct_id_source"])
