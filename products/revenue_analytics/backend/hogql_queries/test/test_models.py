from posthog.schema import CurrencyCode
from posthog.warehouse.models import ExternalDataSource, ExternalDataSchema, DataWarehouseTable, DataWarehouseCredential
from posthog.test.base import BaseTest

from products.revenue_analytics.backend.models import (
    RevenueAnalyticsRevenueView,
    ZERO_DECIMAL_CURRENCIES_IN_STRIPE,
)


class TestRevenueAnalyticsModels(BaseTest):
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
            name="Charge",
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

    def test_revenue_view_creation(self):
        views = RevenueAnalyticsRevenueView.for_schema_source(self.source)
        self.assertEqual(len(views), 1)
        self.assertEqual(views[0].name, "stripe.charge_revenue_view")

    def test_revenue_view_non_stripe_source(self):
        """Test that RevenueAnalyticsRevenueView returns None for non-Stripe sources"""
        self.source.source_type = "Salesforce"
        self.source.save()

        views = RevenueAnalyticsRevenueView.for_schema_source(self.source)
        self.assertEqual(len(views), 0)

    def test_revenue_view_missing_schema(self):
        """Test that RevenueAnalyticsRevenueView handles missing schema gracefully"""
        self.schema.delete()

        views = RevenueAnalyticsRevenueView.for_schema_source(self.source)
        self.assertEqual(len(views), 0)

    def test_revenue_view_prefix(self):
        """Test that RevenueAnalyticsRevenueView handles prefix correctly"""
        self.source.prefix = "prefix"
        self.source.save()

        views = RevenueAnalyticsRevenueView.for_schema_source(self.source)
        self.assertEqual(len(views), 1)
        self.assertEqual(views[0].name, "stripe.prefix.charge_revenue_view")

    def test_revenue_view_no_prefix(self):
        """Test that RevenueAnalyticsRevenueView handles no prefix correctly"""
        self.source.prefix = None
        self.source.save()

        views = RevenueAnalyticsRevenueView.for_schema_source(self.source)
        self.assertEqual(len(views), 1)
        self.assertEqual(views[0].name, "stripe.charge_revenue_view")

    def test_revenue_view_prefix_with_underscores(self):
        """Test that RevenueAnalyticsRevenueView handles prefix with underscores correctly"""
        self.source.prefix = "prefix_with_underscores_"
        self.source.save()

        views = RevenueAnalyticsRevenueView.for_schema_source(self.source)
        self.assertEqual(len(views), 1)
        self.assertEqual(views[0].name, "stripe.prefix_with_underscores.charge_revenue_view")

    def test_revenue_view_prefix_with_empty_string(self):
        """Test that RevenueAnalyticsRevenueView handles prefix with underscores and periods correctly"""
        self.source.prefix = ""
        self.source.save()

        views = RevenueAnalyticsRevenueView.for_schema_source(self.source)
        self.assertEqual(len(views), 1)
        self.assertEqual(views[0].name, "stripe.charge_revenue_view")

    def test_revenue_charge_and_customer_views(self):
        """Test that RevenueAnalyticsRevenueView creates both charge and customer views"""
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

        views = RevenueAnalyticsRevenueView.for_schema_source(self.source)
        self.assertEqual(len(views), 2)

        names = [view.name for view in views]
        self.assertIn("stripe.charge_revenue_view", names)
        self.assertIn("stripe.customer_revenue_view", names)
