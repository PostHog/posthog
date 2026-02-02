from posthog.test.base import BaseTest

from posthog.schema import CurrencyCode

from posthog.hogql.timings import HogQLTimings

from posthog.temporal.data_imports.sources.stripe.constants import INVOICE_RESOURCE_NAME as STRIPE_INVOICE_RESOURCE_NAME

from products.data_warehouse.backend.models import (
    DataWarehouseCredential,
    DataWarehouseTable,
    ExternalDataSchema,
    ExternalDataSource,
)
from products.data_warehouse.backend.types import ExternalDataSourceType
from products.revenue_analytics.backend.views import (
    CHARGE_ALIAS,
    CUSTOMER_ALIAS,
    MRR_ALIAS,
    PRODUCT_ALIAS,
    REVENUE_ITEM_ALIAS,
    SUBSCRIPTION_ALIAS,
)
from products.revenue_analytics.backend.views.orchestrator import build_all_revenue_analytics_views
from products.revenue_analytics.backend.views.schemas import SCHEMAS
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
        stripe_views = [v for v in views if v.name.startswith("stripe.")]
        self.assertEqual(len(stripe_views), 6)

        # Per-view type filtering by name suffix using schema definitions
        revenue_item_suffix = SCHEMAS[REVENUE_ITEM_ALIAS].source_suffix
        self.assertIn(f"stripe.{revenue_item_suffix}", [s.name for s in stripe_views])
        revenue_item_views = [v for v in stripe_views if v.name.endswith(revenue_item_suffix)]
        self.assertEqual(len(revenue_item_views), 1)
        self.assertEqual(revenue_item_views[0].name, f"stripe.{revenue_item_suffix}")

        customer_suffix = SCHEMAS[CUSTOMER_ALIAS].source_suffix
        customer_views = [v for v in stripe_views if v.name.endswith(customer_suffix)]
        self.assertEqual(len(customer_views), 1)
        self.assertEqual(customer_views[0].name, f"stripe.{customer_suffix}")

        product_suffix = SCHEMAS[PRODUCT_ALIAS].source_suffix
        product_views = [v for v in stripe_views if v.name.endswith(product_suffix)]
        self.assertEqual(len(product_views), 1)
        self.assertEqual(product_views[0].name, f"stripe.{product_suffix}")

        subscription_suffix = SCHEMAS[SUBSCRIPTION_ALIAS].source_suffix
        subscription_views = [v for v in stripe_views if v.name.endswith(subscription_suffix)]
        self.assertEqual(len(subscription_views), 1)
        self.assertEqual(subscription_views[0].name, f"stripe.{subscription_suffix}")

        charge_suffix = SCHEMAS[CHARGE_ALIAS].source_suffix
        charge_views = [v for v in stripe_views if v.name.endswith(charge_suffix)]
        self.assertEqual(len(charge_views), 1)
        self.assertEqual(charge_views[0].name, f"stripe.{charge_suffix}")

        mrr_suffix = SCHEMAS[MRR_ALIAS].source_suffix
        mrr_views = [v for v in stripe_views if v.name.endswith(mrr_suffix)]
        self.assertEqual(len(mrr_views), 1)
        self.assertEqual(mrr_views[0].name, f"stripe.{mrr_suffix}")

    def test_revenue_view_with_disabled_source(self):
        """Test that the orchestrator returns None for disabled sources"""
        self.source.revenue_analytics_config.enabled = False
        self.source.revenue_analytics_config.save()

        views = build_all_revenue_analytics_views(self.team, self.timings)
        stripe_views = [v for v in views if v.name.startswith("stripe.")]
        self.assertEqual(len(stripe_views), 0)

    def test_revenue_view_non_stripe_source(self):
        """Test that the orchestrator returns None for non-Stripe sources"""
        self.source.source_type = "Salesforce"
        self.source.save()

        views = build_all_revenue_analytics_views(self.team, self.timings)
        stripe_views = [v for v in views if v.name.startswith("stripe.")]
        self.assertEqual(len(stripe_views), 0)

    def test_revenue_view_missing_schema(self):
        """Test that the orchestrator handles missing schema gracefully"""
        self.schema.delete()

        views = build_all_revenue_analytics_views(self.team, self.timings)
        stripe_views = [v for v in views if v.name.startswith("stripe.")]
        self.assertEqual(len(stripe_views), 6)

    def test_revenue_view_prefix(self):
        """Test that the orchestrator handles prefix correctly"""
        self.source.prefix = "prefix"
        self.source.save()

        views = build_all_revenue_analytics_views(self.team, self.timings)
        stripe_prefix_views = [v for v in views if v.name.startswith("stripe.prefix.")]
        self.assertEqual(len(stripe_prefix_views), 6)
        revenue_item_suffix = SCHEMAS[REVENUE_ITEM_ALIAS].source_suffix
        self.assertIn(f"stripe.prefix.{revenue_item_suffix}", [s.name for s in stripe_prefix_views])

    def test_revenue_view_no_prefix(self):
        """Test that the orchestrator handles no prefix correctly"""
        self.source.prefix = None
        self.source.save()

        views = build_all_revenue_analytics_views(self.team, self.timings)
        stripe_views = [v for v in views if v.name.startswith("stripe.")]
        self.assertEqual(len(stripe_views), 6)
        revenue_item_suffix = SCHEMAS[REVENUE_ITEM_ALIAS].source_suffix
        self.assertIn(f"stripe.{revenue_item_suffix}", [s.name for s in stripe_views])

    def test_revenue_view_prefix_with_underscores(self):
        """Test that the orchestrator handles prefix with underscores correctly"""
        self.source.prefix = "prefix_with_underscores_"
        self.source.save()

        views = build_all_revenue_analytics_views(self.team, self.timings)
        stripe_prefix_views = [v for v in views if v.name.startswith("stripe.prefix_with_underscores.")]
        self.assertEqual(len(stripe_prefix_views), 6)
        revenue_item_suffix = SCHEMAS[REVENUE_ITEM_ALIAS].source_suffix
        self.assertIn(f"stripe.prefix_with_underscores.{revenue_item_suffix}", [s.name for s in stripe_prefix_views])

    def test_revenue_view_prefix_with_empty_string(self):
        """Test that the orchestrator handles empty prefix"""
        self.source.prefix = ""
        self.source.save()

        views = build_all_revenue_analytics_views(self.team, self.timings)
        stripe_views = [v for v in views if v.name.startswith("stripe.")]
        self.assertEqual(len(stripe_views), 6)
        revenue_item_suffix = SCHEMAS[REVENUE_ITEM_ALIAS].source_suffix
        self.assertIn(f"stripe.{revenue_item_suffix}", [s.name for s in stripe_views])

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
        # Expect 6 stripe-backed views for this source
        stripe_views = [v for v in views if v.name.startswith("stripe.")]
        self.assertEqual(len(stripe_views), 6)
        timings_keys = self.timings.to_dict().keys()
        self.assertIn("./for_events", timings_keys)
        self.assertIn("./for_schema_sources", timings_keys)

        names = [view.name for view in stripe_views]
        # Use schema definitions to verify view names
        self.assertIn(f"stripe.{SCHEMAS[CHARGE_ALIAS].source_suffix}", names)
        self.assertIn(f"stripe.{SCHEMAS[CUSTOMER_ALIAS].source_suffix}", names)
        self.assertIn(f"stripe.{SCHEMAS[MRR_ALIAS].source_suffix}", names)
        self.assertIn(f"stripe.{SCHEMAS[PRODUCT_ALIAS].source_suffix}", names)
        self.assertIn(f"stripe.{SCHEMAS[REVENUE_ITEM_ALIAS].source_suffix}", names)  # Already exists from the setup
        self.assertIn(f"stripe.{SCHEMAS[SUBSCRIPTION_ALIAS].source_suffix}", names)

        # Test individual views by name suffix using schema definitions
        charge_suffix = SCHEMAS[CHARGE_ALIAS].source_suffix
        charge_views = [v for v in stripe_views if v.name.endswith(charge_suffix)]
        self.assertEqual(len(charge_views), 1)
        self.assertEqual(charge_views[0].name, f"stripe.{charge_suffix}")

        customer_suffix = SCHEMAS[CUSTOMER_ALIAS].source_suffix
        customer_views = [v for v in stripe_views if v.name.endswith(customer_suffix)]
        self.assertEqual(len(customer_views), 1)
        self.assertEqual(customer_views[0].name, f"stripe.{customer_suffix}")

        mrr_suffix = SCHEMAS[MRR_ALIAS].source_suffix
        mrr_views = [v for v in stripe_views if v.name.endswith(mrr_suffix)]
        self.assertEqual(len(mrr_views), 1)
        self.assertEqual(mrr_views[0].name, f"stripe.{mrr_suffix}")

        product_suffix = SCHEMAS[PRODUCT_ALIAS].source_suffix
        product_views = [v for v in stripe_views if v.name.endswith(product_suffix)]
        self.assertEqual(len(product_views), 1)
        self.assertEqual(product_views[0].name, f"stripe.{product_suffix}")

        revenue_item_suffix = SCHEMAS[REVENUE_ITEM_ALIAS].source_suffix
        revenue_item_views = [v for v in stripe_views if v.name.endswith(revenue_item_suffix)]
        self.assertEqual(len(revenue_item_views), 1)
        self.assertEqual(revenue_item_views[0].name, f"stripe.{revenue_item_suffix}")

        subscription_suffix = SCHEMAS[SUBSCRIPTION_ALIAS].source_suffix
        subscription_views = [v for v in stripe_views if v.name.endswith(subscription_suffix)]
        self.assertEqual(len(subscription_views), 1)
        self.assertEqual(subscription_views[0].name, f"stripe.{subscription_suffix}")
