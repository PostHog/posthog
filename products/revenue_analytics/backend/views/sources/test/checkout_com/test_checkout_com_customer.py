from products.revenue_analytics.backend.views.schemas.customer import SCHEMA as CUSTOMER_SCHEMA
from products.revenue_analytics.backend.views.sources.checkout_com.customer import build
from products.revenue_analytics.backend.views.sources.checkout_com.helpers import (
    CUSTOMER_RESOURCE_NAME,
    PAYMENT_RESOURCE_NAME,
)
from products.revenue_analytics.backend.views.sources.test.checkout_com.base import CheckoutComSourceBaseTest


class TestCustomerCheckoutComBuilder(CheckoutComSourceBaseTest):
    def test_build_customer_query_with_customers_and_payments_schemas(self):
        self.setup_checkout_com_external_data_source(schemas=[CUSTOMER_RESOURCE_NAME, PAYMENT_RESOURCE_NAME])

        query = build(self.checkout_com_handle)
        customer_table = self.get_checkout_com_table_by_schema_name(CUSTOMER_RESOURCE_NAME)

        self.assertQueryContainsFields(query.query, CUSTOMER_SCHEMA)
        self.assertBuiltQueryStructure(query, str(customer_table.id), f"checkoutcom.{self.external_data_source.prefix}")

        # Cohort comes from the earliest synced payment for each customer
        query_sql = query.query.to_hogql()
        self.assertIn(f"{self.external_data_source.prefix}_{PAYMENT_RESOURCE_NAME}", query_sql)

        self.assertQueryMatchesSnapshot(query_sql, replace_all_numbers=True)

    def test_build_customer_query_without_payments_schema(self):
        # Without the payments table there is no charge history, so cohort stays NULL
        self.setup_checkout_com_external_data_source(schemas=[CUSTOMER_RESOURCE_NAME])

        query = build(self.checkout_com_handle)
        customer_table = self.get_checkout_com_table_by_schema_name(CUSTOMER_RESOURCE_NAME)

        self.assertQueryContainsFields(query.query, CUSTOMER_SCHEMA)
        self.assertBuiltQueryStructure(query, str(customer_table.id), f"checkoutcom.{self.external_data_source.prefix}")

        query_sql = query.query.to_hogql()
        self.assertNotIn(f"{self.external_data_source.prefix}_{PAYMENT_RESOURCE_NAME}", query_sql)

        self.assertQueryMatchesSnapshot(query_sql, replace_all_numbers=True)

    def test_build_with_no_customers_schema_returns_empty_view(self):
        self.setup_checkout_com_external_data_source(schemas=[PAYMENT_RESOURCE_NAME])

        query = build(self.checkout_com_handle)

        self.assertQueryContainsFields(query.query, CUSTOMER_SCHEMA)
        self.assertBuiltQueryStructure(
            query,
            str(self.checkout_com_handle.source.id),  # type: ignore
            f"checkoutcom.{self.external_data_source.prefix}",
            expected_test_comments="no_schema",
        )

    def test_build_with_customers_schema_but_no_table_returns_empty_view(self):
        self.setup_checkout_com_external_data_source(
            schemas=[CUSTOMER_RESOURCE_NAME],
            schemas_without_tables=[CUSTOMER_RESOURCE_NAME],
        )

        query = build(self.checkout_com_handle)

        self.assertQueryContainsFields(query.query, CUSTOMER_SCHEMA)
        self.assertBuiltQueryStructure(
            query,
            str(self.checkout_com_handle.source.id),  # type: ignore
            f"checkoutcom.{self.external_data_source.prefix}",
            expected_test_comments="no_table",
        )

    def test_build_with_no_source(self):
        handle = self.create_checkout_com_handle_without_source()

        with self.assertRaises(ValueError):
            build(handle)
