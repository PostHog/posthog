from parameterized import parameterized

from products.revenue_analytics.backend.views.schemas.revenue_item import SCHEMA as REVENUE_ITEM_SCHEMA
from products.revenue_analytics.backend.views.sources.checkout_com.helpers import (
    PAYMENT_ACTION_RESOURCE_NAME,
    PAYMENT_RESOURCE_NAME,
)
from products.revenue_analytics.backend.views.sources.checkout_com.revenue_item import build
from products.revenue_analytics.backend.views.sources.test.checkout_com.base import CheckoutComSourceBaseTest


class TestRevenueItemCheckoutComBuilder(CheckoutComSourceBaseTest):
    def test_build_revenue_item_query_with_payments_and_actions_schemas(self):
        self.setup_checkout_com_external_data_source(schemas=[PAYMENT_RESOURCE_NAME, PAYMENT_ACTION_RESOURCE_NAME])

        query = build(self.checkout_com_handle)
        payments_table = self.get_checkout_com_table_by_schema_name(PAYMENT_RESOURCE_NAME)

        self.assertQueryContainsFields(query.query, REVENUE_ITEM_SCHEMA)
        self.assertBuiltQueryStructure(query, str(payments_table.id), f"checkoutcom.{self.external_data_source.prefix}")

        # Recurring revenue is derived from the payment's own payment_type
        query_sql = query.query.to_hogql()
        self.assertIn("payment_type", query_sql)
        self.assertIn("recurring", query_sql)

        self.assertQueryMatchesSnapshot(query_sql, replace_all_numbers=True)

    @parameterized.expand(
        [
            ("no_schemas_at_all", []),
            ("only_payments", [PAYMENT_RESOURCE_NAME]),
            ("only_payment_actions", [PAYMENT_ACTION_RESOURCE_NAME]),
        ]
    )
    def test_build_with_missing_schema_returns_empty_view(self, _name, schemas):
        self.setup_checkout_com_external_data_source(schemas=schemas)

        query = build(self.checkout_com_handle)

        self.assertQueryContainsFields(query.query, REVENUE_ITEM_SCHEMA)
        self.assertBuiltQueryStructure(
            query,
            str(self.checkout_com_handle.source.id),  # type: ignore
            f"checkoutcom.{self.external_data_source.prefix}",
            expected_test_comments="no_schema",
        )

    @parameterized.expand([(PAYMENT_RESOURCE_NAME,), (PAYMENT_ACTION_RESOURCE_NAME,)])
    def test_build_with_schema_but_no_table_returns_empty_view(self, schema_without_table):
        self.setup_checkout_com_external_data_source(
            schemas=[PAYMENT_RESOURCE_NAME, PAYMENT_ACTION_RESOURCE_NAME],
            schemas_without_tables=[schema_without_table],
        )

        query = build(self.checkout_com_handle)

        self.assertQueryContainsFields(query.query, REVENUE_ITEM_SCHEMA)
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
