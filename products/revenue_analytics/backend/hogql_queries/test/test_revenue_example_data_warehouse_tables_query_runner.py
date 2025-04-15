from decimal import Decimal
from pathlib import Path

from freezegun import freeze_time

from posthog.schema import (
    CurrencyCode,
    RevenueExampleDataWarehouseTablesQuery,
    RevenueExampleDataWarehouseTablesQueryResponse,
    RevenueTrackingConfig,
)
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    snapshot_clickhouse_queries,
)
from posthog.warehouse.models import ExternalDataSchema
from posthog.warehouse.test.utils import create_data_warehouse_table_from_csv
from products.revenue_analytics.backend.hogql_queries.revenue_example_data_warehouse_tables_query_runner import (
    RevenueExampleDataWarehouseTablesQueryRunner,
)
from products.revenue_analytics.backend.models import STRIPE_DATA_WAREHOUSE_CHARGE_IDENTIFIER

STRIPE_CHARGE_COLUMNS = {
    "id": "String",
    "paid": "Int8",
    "amount": "Int64",
    "object": "String",
    "status": "String",
    "created": "DateTime",
    "invoice": "String",
    "captured": "Int8",
    "currency": "String",
    "customer": "String",
    "disputed": "Int8",
    "livemode": "Int8",
    "metadata": "String",
    "refunded": "Int8",
    "description": "String",
    "receipt_url": "String",
    "failure_code": "String",
    "fraud_details": "String",
    "radar_options": "String",
    "receipt_email": "String",
    "payment_intent": "String",
    "payment_method": "String",
    "amount_captured": "Int64",
    "amount_refunded": "Int64",
    "billing_details": "String",
    "failure_message": "String",
    "balance_transaction": "String",
    "statement_descriptor": "String",
    "calculated_statement_descriptor": "String",
    "source": "String",
    "outcome": "String",
    "payment_method_details": "String",
}

REVENUE_TRACKING_CONFIG = RevenueTrackingConfig(baseCurrency=CurrencyCode.GBP, events=[])
TEST_BUCKET = "test_storage_bucket-posthog.revenue.stripe_charges"


@snapshot_clickhouse_queries
class TestRevenueExampleDataWarehouseTablesQueryRunner(ClickhouseTestMixin, APIBaseTest):
    QUERY_TIMESTAMP = "2025-01-29"

    def setUp(self):
        super().setUp()

        self.csv_path = Path(__file__).parent / "data" / "stripe_charges.csv"
        self.table, self.source, self.credential, self.csv_df, self.cleanUpFilesystem = (
            create_data_warehouse_table_from_csv(
                self.csv_path,
                "stripe_charge",
                STRIPE_CHARGE_COLUMNS,
                TEST_BUCKET,
                self.team,
            )
        )

        # Besides the default creations above, also create the external data schema
        # because this is required by the `RevenueAnalyticsRevenueView` to find the right tables
        self.schema = ExternalDataSchema.objects.create(
            team=self.team,
            name=STRIPE_DATA_WAREHOUSE_CHARGE_IDENTIFIER,
            source=self.source,
            table=self.table,
            should_sync=True,
            last_synced_at="2024-01-01",
        )

        self.team.revenue_tracking_config = REVENUE_TRACKING_CONFIG.model_dump()
        self.team.save()

    def tearDown(self):
        self.cleanUpFilesystem()
        super().tearDown()

    def _run_revenue_example_external_tables_query(self):
        with freeze_time(self.QUERY_TIMESTAMP):
            query = RevenueExampleDataWarehouseTablesQuery()
            runner = RevenueExampleDataWarehouseTablesQueryRunner(team=self.team, query=query)

            response = runner.calculate()
            RevenueExampleDataWarehouseTablesQueryResponse.model_validate(response)

            return response

    def test_no_crash_when_no_data(self):
        self.table.delete()
        results = self._run_revenue_example_external_tables_query().results

        assert len(results) == 0

    def test_database_query(self):
        response = self._run_revenue_example_external_tables_query()
        results = response.results

        # Not all rows in the CSV have a status of "succeeded", let's filter them out here
        assert len(results) == len(self.csv_df[self.csv_df["status"] == "succeeded"])

        # Proper conversions for some of the rows
        assert results[0][2:] == (Decimal("220"), "EUR", Decimal("182.247167654"), "GBP")
        assert results[1][2:] == (Decimal("180"), "GBP", Decimal("180"), "GBP")

        # Test JPY where there are no decimals, and an input of 500 implies 500 Yen
        # rather than the above where we had 22000 for 220 EUR (and etc.)
        assert results[3][2:] == (Decimal("500"), "JPY", Decimal("2.5438762801"), "GBP")
