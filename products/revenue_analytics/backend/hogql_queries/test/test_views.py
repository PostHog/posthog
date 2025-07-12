from posthog.schema import CurrencyCode
from posthog.warehouse.models import ExternalDataSource, ExternalDataSchema, DataWarehouseTable, DataWarehouseCredential
from posthog.test.base import BaseTest

from products.revenue_analytics.backend.views.revenue_analytics_base_view import RevenueAnalyticsBaseView
from products.revenue_analytics.backend.views.revenue_analytics_charge_view import (
    RevenueAnalyticsChargeView,
    STRIPE_CHARGE_RESOURCE_NAME,
)
from products.revenue_analytics.backend.views.currency_helpers import ZERO_DECIMAL_CURRENCIES_IN_STRIPE
from products.revenue_analytics.backend.views import (
    RevenueAnalyticsCustomerView,
    RevenueAnalyticsInvoiceItemView,
    RevenueAnalyticsProductView,
    RevenueAnalyticsSubscriptionView,
)
from posthog.hogql.timings import HogQLTimings


class TestRevenueAnalyticsViews(BaseTest):
    def setUp(self):
        super().setUp()

        self.timings = HogQLTimings()

        self.source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="source_id",
            connection_id="connection_id",
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSource.Type.STRIPE,
        )
        self.credentials = DataWarehouseCredential.objects.create(
            access_key="blah", access_secret="blah", team=self.team
        )

        self.table = DataWarehouseTable.objects.create(
            name="charge",
            format="Parquet",
            team=self.team,
            external_data_source=self.source,
            external_data_source_id=self.source.id,
            credential=self.credentials,
            url_pattern="https://bucket.s3/data/*",
            columns={"id": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)", "schema_valid": True}},
        )
        self.schema = ExternalDataSchema.objects.create(
            team=self.team,
            name=STRIPE_CHARGE_RESOURCE_NAME,
            source=self.source,
            table=self.table,
            should_sync=True,
            last_synced_at="2024-01-01",
        )

    def test_zero_decimal_currencies(self):
        """Test that zero decimal currencies are correctly defined"""
        self.assertIn(CurrencyCode.JPY, ZERO_DECIMAL_CURRENCIES_IN_STRIPE)
        self.assertIn(CurrencyCode.KRW, ZERO_DECIMAL_CURRENCIES_IN_STRIPE)
        self.assertNotIn(CurrencyCode.USD, ZERO_DECIMAL_CURRENCIES_IN_STRIPE)

    def test_schema_source_views(self):
        views = RevenueAnalyticsBaseView.for_schema_source(self.source)
        self.assertEqual(len(views), 1)
        self.assertEqual(views[0].name, "stripe.charge_revenue_view")

        charge_views = RevenueAnalyticsChargeView.for_schema_source(self.source)
        self.assertEqual(len(charge_views), 1)
        self.assertEqual(charge_views[0].name, "stripe.charge_revenue_view")

        customer_views = RevenueAnalyticsCustomerView.for_schema_source(self.source)
        self.assertEqual(len(customer_views), 0)

        subscription_views = RevenueAnalyticsSubscriptionView.for_schema_source(self.source)
        self.assertEqual(len(subscription_views), 0)

    def test_revenue_view_non_stripe_source(self):
        """Test that RevenueAnalyticsBaseView returns None for non-Stripe sources"""
        self.source.source_type = "Salesforce"
        self.source.save()

        views = RevenueAnalyticsBaseView.for_schema_source(self.source)
        self.assertEqual(len(views), 0)

    def test_revenue_view_missing_schema(self):
        """Test that RevenueAnalyticsBaseView handles missing schema gracefully"""
        self.schema.delete()

        views = RevenueAnalyticsBaseView.for_schema_source(self.source)
        self.assertEqual(len(views), 0)

    def test_revenue_view_prefix(self):
        """Test that RevenueAnalyticsBaseView handles prefix correctly"""
        self.source.prefix = "prefix"
        self.source.save()

        views = RevenueAnalyticsBaseView.for_schema_source(self.source)
        self.assertEqual(len(views), 1)
        self.assertEqual(views[0].name, "stripe.prefix.charge_revenue_view")

    def test_revenue_view_no_prefix(self):
        """Test that RevenueAnalyticsBaseView handles no prefix correctly"""
        self.source.prefix = None
        self.source.save()

        views = RevenueAnalyticsBaseView.for_schema_source(self.source)
        self.assertEqual(len(views), 1)
        self.assertEqual(views[0].name, "stripe.charge_revenue_view")

    def test_revenue_view_prefix_with_underscores(self):
        """Test that RevenueAnalyticsBaseView handles prefix with underscores correctly"""
        self.source.prefix = "prefix_with_underscores_"
        self.source.save()

        views = RevenueAnalyticsBaseView.for_schema_source(self.source)
        self.assertEqual(len(views), 1)
        self.assertEqual(views[0].name, "stripe.prefix_with_underscores.charge_revenue_view")

    def test_revenue_view_prefix_with_empty_string(self):
        """Test that RevenueAnalyticsBaseView handles empty prefix"""
        self.source.prefix = ""
        self.source.save()

        views = RevenueAnalyticsBaseView.for_schema_source(self.source)
        self.assertEqual(len(views), 1)
        self.assertEqual(views[0].name, "stripe.charge_revenue_view")

    def test_revenue_all_views(self):
        """Test that RevenueAnalyticsBaseView creates both charge and customer views"""
        customer_table = DataWarehouseTable.objects.create(
            name="customer",
            format="Parquet",
            team=self.team,
            external_data_source=self.source,
            external_data_source_id=self.source.id,
            credential=self.credentials,
            url_pattern="https://bucket.s3/data/*",
            columns={"id": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)", "schema_valid": True}},
        )
        _customer_schema = ExternalDataSchema.objects.create(
            team=self.team,
            name="Customer",
            source=self.source,
            table=customer_table,
            should_sync=True,
            last_synced_at="2024-01-01",
        )

        product_table = DataWarehouseTable.objects.create(
            name="product",
            format="Parquet",
            team=self.team,
            external_data_source=self.source,
            external_data_source_id=self.source.id,
            credential=self.credentials,
            url_pattern="https://bucket.s3/data/*",
            columns={"id": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)", "schema_valid": True}},
        )
        _product_schema = ExternalDataSchema.objects.create(
            team=self.team,
            name="Product",
            source=self.source,
            table=product_table,
            should_sync=True,
            last_synced_at="2024-01-01",
        )

        invoice_table = DataWarehouseTable.objects.create(
            name="invoice",
            format="Parquet",
            team=self.team,
            external_data_source=self.source,
            external_data_source_id=self.source.id,
            credential=self.credentials,
            url_pattern="https://bucket.s3/data/*",
            columns={"id": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)", "schema_valid": True}},
        )
        _invoice_schema = ExternalDataSchema.objects.create(
            team=self.team,
            name="Invoice",
            source=self.source,
            table=invoice_table,
            should_sync=True,
            last_synced_at="2024-01-01",
        )

        subscription_table = DataWarehouseTable.objects.create(
            name="subscription",
            format="Parquet",
            team=self.team,
            external_data_source=self.source,
            external_data_source_id=self.source.id,
            credential=self.credentials,
            url_pattern="https://bucket.s3/data/*",
            columns={"id": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)", "schema_valid": True}},
        )
        _subscription_schema = ExternalDataSchema.objects.create(
            team=self.team,
            name="Subscription",
            source=self.source,
            table=subscription_table,
            should_sync=True,
            last_synced_at="2024-01-01",
        )

        views = RevenueAnalyticsBaseView.for_team(self.team, self.timings)
        self.assertEqual(len(views), 5)
        self.assertIn("./for_events", self.timings.to_dict().keys())
        self.assertIn("./for_schema_source", self.timings.to_dict().keys())

        views = RevenueAnalyticsBaseView.for_schema_source(self.source)
        self.assertEqual(len(views), 5)

        names = [view.name for view in views]
        self.assertIn("stripe.charge_revenue_view", names)
        self.assertIn("stripe.customer_revenue_view", names)
        self.assertIn("stripe.product_revenue_view", names)
        self.assertIn("stripe.invoice_item_revenue_view", names)
        self.assertIn("stripe.subscription_revenue_view", names)

        # Test individual views
        charge_views = RevenueAnalyticsChargeView.for_schema_source(self.source)
        self.assertEqual(len(charge_views), 1)
        self.assertEqual(charge_views[0].name, "stripe.charge_revenue_view")

        customer_views = RevenueAnalyticsCustomerView.for_schema_source(self.source)
        self.assertEqual(len(customer_views), 1)
        self.assertEqual(customer_views[0].name, "stripe.customer_revenue_view")

        product_views = RevenueAnalyticsProductView.for_schema_source(self.source)
        self.assertEqual(len(product_views), 1)
        self.assertEqual(product_views[0].name, "stripe.product_revenue_view")

        invoice_item_views = RevenueAnalyticsInvoiceItemView.for_schema_source(self.source)
        self.assertEqual(len(invoice_item_views), 1)
        self.assertEqual(invoice_item_views[0].name, "stripe.invoice_item_revenue_view")

        subscription_views = RevenueAnalyticsSubscriptionView.for_schema_source(self.source)
        self.assertEqual(len(subscription_views), 1)
        self.assertEqual(subscription_views[0].name, "stripe.subscription_revenue_view")
