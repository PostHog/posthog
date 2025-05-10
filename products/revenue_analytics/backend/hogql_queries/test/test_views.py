from posthog.schema import CurrencyCode
from posthog.warehouse.models import ExternalDataSource, ExternalDataSchema, DataWarehouseTable, DataWarehouseCredential
from posthog.test.base import BaseTest

from products.revenue_analytics.backend.views.revenue_analytics_base_view import RevenueAnalyticsBaseView
from products.revenue_analytics.backend.views.revenue_analytics_charge_view import (
    RevenueAnalyticsChargeView,
    STRIPE_CHARGE_RESOURCE_NAME,
    ZERO_DECIMAL_CURRENCIES_IN_STRIPE,
)
from products.revenue_analytics.backend.views.revenue_analytics_customer_view import RevenueAnalyticsCustomerView


class TestRevenueAnalyticsViews(BaseTest):
    def setUp(self):
        super().setUp()
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

    def test_revenue_charge_and_customer_views(self):
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
        _schema = ExternalDataSchema.objects.create(
            team=self.team,
            name="Customer",
            source=self.source,
            table=customer_table,
            should_sync=True,
            last_synced_at="2024-01-01",
        )

        views = RevenueAnalyticsBaseView.for_schema_source(self.source)
        self.assertEqual(len(views), 2)

        names = [view.name for view in views]
        self.assertIn("stripe.charge_revenue_view", names)
        self.assertIn("stripe.customer_revenue_view", names)

        # Test individual views
        charge_views = RevenueAnalyticsChargeView.for_schema_source(self.source)
        self.assertEqual(len(charge_views), 1)
        self.assertEqual(charge_views[0].name, "stripe.charge_revenue_view")

        customer_views = RevenueAnalyticsCustomerView.for_schema_source(self.source)
        self.assertEqual(len(customer_views), 1)
        self.assertEqual(customer_views[0].name, "stripe.customer_revenue_view")
