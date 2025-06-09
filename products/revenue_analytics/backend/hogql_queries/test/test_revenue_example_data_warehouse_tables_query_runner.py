from decimal import Decimal
from pathlib import Path

from freezegun import freeze_time

from posthog.schema import (
    CurrencyCode,
    RevenueExampleDataWarehouseTablesQuery,
    RevenueExampleDataWarehouseTablesQueryResponse,
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
from products.revenue_analytics.backend.views.revenue_analytics_charge_view import (
    STRIPE_CHARGE_RESOURCE_NAME,
)
from products.revenue_analytics.backend.hogql_queries.test.data.structure import (
    REVENUE_ANALYTICS_CONFIG_SAMPLE_EVENT,
    STRIPE_CHARGE_COLUMNS,
)


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
        # because this is required by the `RevenueAnalyticsBaseView` to find the right tables
        self.schema = ExternalDataSchema.objects.create(
            team=self.team,
            name=STRIPE_CHARGE_RESOURCE_NAME,
            source=self.source,
            table=self.table,
            should_sync=True,
            last_synced_at="2024-01-01",
        )

        self.team.base_currency = CurrencyCode.GBP.value
        self.team.revenue_analytics_config.events = [REVENUE_ANALYTICS_CONFIG_SAMPLE_EVENT]
        self.team.revenue_analytics_config.save()
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

        # Sort results by the original amount just to guarantee order
        results.sort(key=lambda x: x[2])

        # We only care about the last 4 columns (amount, currency, converted_amount, converted_currency)
        results = [row[2:] for row in results]

        assert results == [
            (Decimal("50"), "GBP", Decimal("50"), "GBP"),
            (Decimal("100"), "USD", Decimal("79.7"), "GBP"),
            (Decimal("100"), "USD", Decimal("79.7"), "GBP"),
            (Decimal("120"), "USD", Decimal("95.64"), "GBP"),
            (Decimal("120"), "USD", Decimal("95.64"), "GBP"),
            (Decimal("125"), "GBP", Decimal("125"), "GBP"),
            (Decimal("150"), "EUR", Decimal("124.2594324913"), "GBP"),
            (Decimal("150"), "EUR", Decimal("124.2594324913"), "GBP"),
            (Decimal("150"), "EUR", Decimal("124.2594324913"), "GBP"),
            (Decimal("180"), "GBP", Decimal("180"), "GBP"),
            (Decimal("180"), "GBP", Decimal("180"), "GBP"),
            (Decimal("180"), "GBP", Decimal("180"), "GBP"),
            (Decimal("200"), "USD", Decimal("159.4"), "GBP"),
            (Decimal("220"), "EUR", Decimal("182.247167654"), "GBP"),
            (Decimal("245"), "USD", Decimal("195.265"), "GBP"),
            (Decimal("250"), "EUR", Decimal("207.0990541523"), "GBP"),
            (Decimal("300"), "USD", Decimal("239.1"), "GBP"),
            # Important here how we treated the 500 in the CSV as 500 Yen rather than 5 Yen
            # like we do with other currencies (20000 -> 200 EUR)
            (Decimal("500"), "JPY", Decimal("2.5438762801"), "GBP"),
        ]
