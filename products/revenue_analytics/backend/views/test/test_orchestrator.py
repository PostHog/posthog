from posthog.test.base import BaseTest

from posthog.schema import CurrencyCode

from posthog.hogql.timings import HogQLTimings

from posthog.temporal.data_imports.sources.stripe.constants import INVOICE_RESOURCE_NAME as STRIPE_INVOICE_RESOURCE_NAME
from posthog.warehouse.models import DataWarehouseCredential, DataWarehouseTable, ExternalDataSchema, ExternalDataSource
from posthog.warehouse.types import ExternalDataSourceType

from products.revenue_analytics.backend.views import (
    RevenueAnalyticsChargeView,
    RevenueAnalyticsCustomerView,
    RevenueAnalyticsProductView,
    RevenueAnalyticsRevenueItemView,
    RevenueAnalyticsSubscriptionView,
)
from products.revenue_analytics.backend.views.orchestrator import build_all_revenue_analytics_views
from products.revenue_analytics.backend.views.sources.helpers import ZERO_DECIMAL_CURRENCIES_IN_STRIPE


class TestRevenueAnalyticsViews(BaseTest):
    def setUp(self):
        super().setUp()

        self.timings = HogQLTimings()

        self.source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="source_id",
            connection_id="connection_id",
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSourceType.STRIPE,
        )
        self.credentials = DataWarehouseCredential.objects.create(
            access_key="blah", access_secret="blah", team=self.team
        )

        self.table = DataWarehouseTable.objects.create(
            name="invoice",
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
            name=STRIPE_INVOICE_RESOURCE_NAME,
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
        views = build_all_revenue_analytics_views(self.team, self.timings)
        source_views = [v for v in views if v.source_id == str(self.source.id)]
        self.assertEqual(len(source_views), 5)
        self.assertIn("stripe.revenue_item_revenue_view", [s.name for s in source_views])

        # Per-view class filtering
        revenue_item_views = [v for v in source_views if isinstance(v, RevenueAnalyticsRevenueItemView)]
        self.assertEqual(len(revenue_item_views), 1)
        self.assertEqual(revenue_item_views[0].name, "stripe.revenue_item_revenue_view")

        customer_views = [v for v in source_views if isinstance(v, RevenueAnalyticsCustomerView)]
        self.assertEqual(len(customer_views), 1)
        self.assertEqual(customer_views[0].name, "stripe.customer_revenue_view")

        product_views = [v for v in source_views if isinstance(v, RevenueAnalyticsProductView)]
        self.assertEqual(len(product_views), 1)
        self.assertEqual(product_views[0].name, "stripe.product_revenue_view")

        subscription_views = [v for v in source_views if isinstance(v, RevenueAnalyticsSubscriptionView)]
        self.assertEqual(len(subscription_views), 1)
        self.assertEqual(subscription_views[0].name, "stripe.subscription_revenue_view")

        charge_views = [v for v in source_views if isinstance(v, RevenueAnalyticsChargeView)]
        self.assertEqual(len(charge_views), 1)
        self.assertEqual(charge_views[0].name, "stripe.charge_revenue_view")

    def test_revenue_view_with_disabled_source(self):
        """Test that the orchestrator returns None for disabled sources"""
        self.source.revenue_analytics_config.enabled = False
        self.source.revenue_analytics_config.save()

        views = build_all_revenue_analytics_views(self.team, self.timings)
        source_views = [v for v in views if v.source_id == str(self.source.id)]
        self.assertEqual(len(source_views), 0)

    def test_revenue_view_non_stripe_source(self):
        """Test that the orchestrator returns None for non-Stripe sources"""
        self.source.source_type = "Salesforce"
        self.source.save()

        views = build_all_revenue_analytics_views(self.team, self.timings)
        source_views = [v for v in views if v.source_id == str(self.source.id)]
        self.assertEqual(len(source_views), 0)

    def test_revenue_view_missing_schema(self):
        """Test that the orchestrator handles missing schema gracefully"""
        self.schema.delete()

        views = build_all_revenue_analytics_views(self.team, self.timings)
        source_views = [v for v in views if v.source_id == str(self.source.id)]
        self.assertEqual(len(source_views), 5)

    def test_revenue_view_prefix(self):
        """Test that the orchestrator handles prefix correctly"""
        self.source.prefix = "prefix"
        self.source.save()

        views = build_all_revenue_analytics_views(self.team, self.timings)
        source_views = [v for v in views if v.source_id == str(self.source.id)]
        self.assertEqual(len(source_views), 5)
        self.assertIn("stripe.prefix.revenue_item_revenue_view", [s.name for s in source_views])

    def test_revenue_view_no_prefix(self):
        """Test that the orchestrator handles no prefix correctly"""
        self.source.prefix = None
        self.source.save()

        views = build_all_revenue_analytics_views(self.team, self.timings)
        source_views = [v for v in views if v.source_id == str(self.source.id)]
        self.assertEqual(len(source_views), 5)
        self.assertIn("stripe.revenue_item_revenue_view", [s.name for s in source_views])

    def test_revenue_view_prefix_with_underscores(self):
        """Test that the orchestrator handles prefix with underscores correctly"""
        self.source.prefix = "prefix_with_underscores_"
        self.source.save()

        views = build_all_revenue_analytics_views(self.team, self.timings)
        source_views = [v for v in views if v.source_id == str(self.source.id)]
        self.assertEqual(len(source_views), 5)
        self.assertIn("stripe.prefix_with_underscores.revenue_item_revenue_view", [s.name for s in source_views])

    def test_revenue_view_prefix_with_empty_string(self):
        """Test that the orchestrator handles empty prefix"""
        self.source.prefix = ""
        self.source.save()

        views = build_all_revenue_analytics_views(self.team, self.timings)
        source_views = [v for v in views if v.source_id == str(self.source.id)]
        self.assertEqual(len(source_views), 5)
        self.assertIn("stripe.revenue_item_revenue_view", [s.name for s in source_views])

    def test_revenue_all_views(self):
        """Test that the orchestrator creates both charge and customer views"""
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

        charge_table = DataWarehouseTable.objects.create(
            name="charge",
            format="Parquet",
            team=self.team,
            external_data_source=self.source,
            external_data_source_id=self.source.id,
            credential=self.credentials,
            url_pattern="https://bucket.s3/data/*",
            columns={"id": {"hogql": "StringDatabaseField", "clickhouse": "Nullable(String)", "schema_valid": True}},
        )
        _charge_schema = ExternalDataSchema.objects.create(
            team=self.team,
            name="Charge",
            source=self.source,
            table=charge_table,
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

        views = build_all_revenue_analytics_views(self.team, self.timings)
        # Expect 5 stripe-backed views for this source
        source_views = [v for v in views if v.source_id == str(self.source.id)]
        self.assertEqual(len(source_views), 5)
        timings_keys = self.timings.to_dict().keys()
        self.assertIn("./for_events", timings_keys)
        self.assertIn("./for_schema_sources", timings_keys)

        names = [view.name for view in source_views]
        self.assertIn("stripe.charge_revenue_view", names)
        self.assertIn("stripe.customer_revenue_view", names)
        self.assertIn("stripe.product_revenue_view", names)
        self.assertIn("stripe.revenue_item_revenue_view", names)  # Already exists from the setup
        self.assertIn("stripe.subscription_revenue_view", names)

        # Test individual views
        charge_views = [v for v in source_views if isinstance(v, RevenueAnalyticsChargeView)]
        self.assertEqual(len(charge_views), 1)
        self.assertEqual(charge_views[0].name, "stripe.charge_revenue_view")

        customer_views = [v for v in source_views if isinstance(v, RevenueAnalyticsCustomerView)]
        self.assertEqual(len(customer_views), 1)
        self.assertEqual(customer_views[0].name, "stripe.customer_revenue_view")

        product_views = [v for v in source_views if isinstance(v, RevenueAnalyticsProductView)]
        self.assertEqual(len(product_views), 1)
        self.assertEqual(product_views[0].name, "stripe.product_revenue_view")

        revenue_item_views = [v for v in source_views if isinstance(v, RevenueAnalyticsRevenueItemView)]
        self.assertEqual(len(revenue_item_views), 1)
        self.assertEqual(revenue_item_views[0].name, "stripe.revenue_item_revenue_view")

        subscription_views = [v for v in source_views if isinstance(v, RevenueAnalyticsSubscriptionView)]
        self.assertEqual(len(subscription_views), 1)
        self.assertEqual(subscription_views[0].name, "stripe.subscription_revenue_view")
