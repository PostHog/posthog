from parameterized import parameterized

from products.revenue_analytics.backend.views.schemas.charge import SCHEMA as CHARGE_SCHEMA
from products.revenue_analytics.backend.views.sources.checkout_com.charge import build
from products.revenue_analytics.backend.views.sources.checkout_com.helpers import (
    PAYMENT_ACTION_RESOURCE_NAME,
    PAYMENT_RESOURCE_NAME,
)
from products.revenue_analytics.backend.views.sources.test.checkout_com.base import CheckoutComSourceBaseTest


class TestChargeCheckoutComBuilder(CheckoutComSourceBaseTest):
    def test_build_charge_query_with_payments_and_actions_schemas(self):
        self.setup_checkout_com_external_data_source(schemas=[PAYMENT_RESOURCE_NAME, PAYMENT_ACTION_RESOURCE_NAME])

        query = build(self.checkout_com_handle)
        actions_table = self.get_checkout_com_table_by_schema_name(PAYMENT_ACTION_RESOURCE_NAME)

        self.assertQueryContainsFields(query.query, CHARGE_SCHEMA)
        self.assertBuiltQueryStructure(query, str(actions_table.id), f"checkoutcom.{self.external_data_source.prefix}")

        query_sql = query.query.to_hogql()
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

        self.assertQueryContainsFields(query.query, CHARGE_SCHEMA)
        self.assertBuiltQueryStructure(
            query,
            str(self.checkout_com_handle.source.id),  # type: ignore
            f"checkoutcom.{self.external_data_source.prefix}",
            expected_test_comments="no_schema",
        )

    @parameterized.expand([(PAYMENT_RESOURCE_NAME,), (PAYMENT_ACTION_RESOURCE_NAME,)])
    def test_build_with_schema_but_no_table_returns_empty_view(self, schema_without_table):
        self.setup_checkout_com_external_data_source(schemas=[PAYMENT_RESOURCE_NAME, PAYMENT_ACTION_RESOURCE_NAME])
        schema = self.get_checkout_com_schema_by_name(schema_without_table)
        schema.table = None

        query = build(self.checkout_com_handle)

        self.assertQueryContainsFields(query.query, CHARGE_SCHEMA)
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

    def test_charge_query_uses_checkout_com_minor_unit_rules(self):
        # Guards against reusing Stripe's zero-decimal list: Checkout.com treats ISK as
        # full-value and CLP as two-decimal, and has a three-decimal group divided by 1000
        self.set_team_base_currency("EUR")
        self.setup_checkout_com_external_data_source(schemas=[PAYMENT_RESOURCE_NAME, PAYMENT_ACTION_RESOURCE_NAME])

        query = build(self.checkout_com_handle)
        query_sql = query.query.to_hogql()

        self.assertIn("EUR", query_sql)
        # Full-value list per Checkout.com docs: includes ISK, excludes CLP (both differ from Stripe)
        self.assertIn("ISK", query_sql)
        self.assertNotIn("CLP", query_sql)
        # Three-decimal currencies are divided by 1000
        self.assertIn("BHD", query_sql)
        self.assertIn("1000", query_sql)

        self.assertQueryMatchesSnapshot(query_sql, replace_all_numbers=True)
