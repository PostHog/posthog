from unittest.mock import patch

from posthog.hogql import ast
from posthog.schema import CurrencyCode
from posthog.warehouse.models import ExternalDataSource, ExternalDataSchema, DataWarehouseTable, DataWarehouseCredential
from posthog.test.base import BaseTest

from products.revenue_analytics.backend.models import (
    RevenueAnalyticsRevenueView,
    ZERO_DECIMAL_CURRENCIES_IN_STRIPE,
    BASE_FIELDS,
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
            name="table_1",
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

    @patch("posthoganalytics.feature_enabled")
    def test_revenue_view_creation_with_currency_conversion(self, mock_feature_enabled):
        """Test creating RevenueAnalyticsRevenueView with currency conversion enabled"""
        mock_feature_enabled.return_value = True

        view = RevenueAnalyticsRevenueView.for_schema_source(self.source)
        self.assertIsNotNone(view)
        self.assertEqual(view.data_warehouse_table, self.table)

        # Verify fields
        fields = view.fields
        self.assertIn("currency", fields)
        self.assertIn("amount", fields)
        self.assertTrue(isinstance(fields["amount"], ast.ExpressionField))

    @patch("posthoganalytics.feature_enabled")
    def test_revenue_view_creation_without_currency_conversion(self, mock_feature_enabled):
        """Test creating RevenueAnalyticsRevenueView without currency conversion"""
        mock_feature_enabled.return_value = False

        view = RevenueAnalyticsRevenueView.for_schema_source(self.source)
        self.assertIsNotNone(view)
        self.assertEqual(view.data_warehouse_table, self.table)

        # Verify fields use original values
        fields = view.fields
        self.assertEqual(fields["currency"], BASE_FIELDS["original_currency"])
        self.assertEqual(fields["amount"], BASE_FIELDS["adjusted_original_amount"])

    def test_revenue_view_non_stripe_source(self):
        """Test that RevenueAnalyticsRevenueView returns None for non-Stripe sources"""
        self.source.source_type = "Salesforce"
        self.source.save()

        view = RevenueAnalyticsRevenueView.for_schema_source(self.source)
        self.assertIsNone(view)

    def test_revenue_view_missing_schema(self):
        """Test that RevenueAnalyticsRevenueView handles missing schema gracefully"""
        self.schema.delete()

        view = RevenueAnalyticsRevenueView.for_schema_source(self.source)
        self.assertIsNone(view)

    def test_to_printed_clickhouse(self):
        """Test the to_printed_clickhouse method"""
        view = RevenueAnalyticsRevenueView.for_schema_source(self.source)
        self.assertEqual(view.to_printed_clickhouse(None), self.table.name)

    def test_to_printed_hogql(self):
        """Test the to_printed_hogql method"""
        view = RevenueAnalyticsRevenueView.for_schema_source(self.source)
        self.assertEqual(view.to_printed_hogql(), self.table.name)
