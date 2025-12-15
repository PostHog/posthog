from decimal import Decimal
from pathlib import Path

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, snapshot_clickhouse_queries
from unittest.mock import patch

from posthog.schema import (
    CurrencyCode,
    HogQLQueryModifiers,
    RevenueExampleDataWarehouseTablesQuery,
    RevenueExampleDataWarehouseTablesQueryResponse,
)

from posthog.temporal.data_imports.sources.stripe.constants import INVOICE_RESOURCE_NAME as STRIPE_INVOICE_RESOURCE_NAME

from products.data_warehouse.backend.models import ExternalDataSchema
from products.data_warehouse.backend.models.datawarehouse_managed_viewset import DataWarehouseManagedViewSet
from products.data_warehouse.backend.test.utils import create_data_warehouse_table_from_csv
from products.data_warehouse.backend.types import DataWarehouseManagedViewSetKind
from products.revenue_analytics.backend.hogql_queries.revenue_example_data_warehouse_tables_query_runner import (
    RevenueExampleDataWarehouseTablesQueryRunner,
)
from products.revenue_analytics.backend.hogql_queries.test.data.structure import (
    REVENUE_ANALYTICS_CONFIG_SAMPLE_EVENT,
    STRIPE_INVOICE_COLUMNS,
)

TEST_BUCKET = "test_storage_bucket-posthog.revenue.stripe_invoices"


@snapshot_clickhouse_queries
class TestRevenueExampleDataWarehouseTablesQueryRunner(ClickhouseTestMixin, APIBaseTest):
    QUERY_TIMESTAMP = "2025-04-21"

    def _create_managed_viewsets(self):
        self.viewset, _ = DataWarehouseManagedViewSet.objects.get_or_create(
            team=self.team, kind=DataWarehouseManagedViewSetKind.REVENUE_ANALYTICS
        )
        self.viewset.sync_views()

    def setUp(self):
        super().setUp()

        self.csv_path = Path(__file__).parent / "data" / "stripe_invoices.csv"
        self.table, self.source, self.credential, self.csv_df, self.cleanUpFilesystem = (
            create_data_warehouse_table_from_csv(
                self.csv_path,
                "stripe_invoice",
                STRIPE_INVOICE_COLUMNS,
                TEST_BUCKET,
                self.team,
            )
        )

        # Besides the default creations above, also create the external data schema
        # because this is required by the `RevenueAnalyticsBaseView` to find the right tables
        self.schema = ExternalDataSchema.objects.create(
            team=self.team,
            name=STRIPE_INVOICE_RESOURCE_NAME,
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
            query = RevenueExampleDataWarehouseTablesQuery(
                modifiers=HogQLQueryModifiers(formatCsvAllowDoubleQuotes=True),
            )
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

        # Sort results by the original amount just to guarantee order
        results.sort(key=lambda x: x[2])

        # We only care about 4 of the columns (amount, currency, converted_amount, converted_currency)
        results = [row[2:-1] for row in results]

        assert results == [
            # This is an important case, it's got a value in the DB but discounts bring it to 0
            (Decimal("0"), "USD", Decimal("0"), "GBP"),
            (Decimal("0.12"), "USD", Decimal("0.09564"), "GBP"),
            (Decimal("0.43"), "USD", Decimal("0.34271"), "GBP"),
            (Decimal("0.43"), "USD", Decimal("0.171355"), "GBP"),
            (Decimal("0.43"), "USD", Decimal("0.34271"), "GBP"),
            (Decimal("0.43"), "USD", Decimal("0.171355"), "GBP"),
            (Decimal("0.43"), "USD", Decimal("0.171355"), "GBP"),
            (Decimal("0.43"), "USD", Decimal("0.171355"), "GBP"),
            (Decimal("0.43"), "USD", Decimal("0.171355"), "GBP"),
            (Decimal("0.43"), "USD", Decimal("0.171355"), "GBP"),
            (Decimal("1.23"), "EUR", Decimal("1.0189273464"), "GBP"),
            (Decimal("3.43"), "USD", Decimal("1.366855"), "GBP"),
            (Decimal("3.43"), "USD", Decimal("1.366855"), "GBP"),
            (Decimal("14.45"), "USD", Decimal("5.758325"), "GBP"),
            (Decimal("14.45"), "USD", Decimal("5.758325"), "GBP"),
            (Decimal("24.5"), "GBP", Decimal("24.5"), "GBP"),
            (Decimal("46.66"), "USD", Decimal("18.59401"), "GBP"),
            (Decimal("46.66"), "USD", Decimal("18.59401"), "GBP"),
            (Decimal("54.99"), "USD", Decimal("43.82703"), "GBP"),
            (Decimal("88.88"), "USD", Decimal("70.83736"), "GBP"),
            (Decimal("90.7"), "USD", Decimal("72.2879"), "GBP"),
            (Decimal("90.7"), "USD", Decimal("72.2879"), "GBP"),
            (Decimal("104.35"), "USD", Decimal("83.16695"), "GBP"),
            (Decimal("145.5"), "BRL", Decimal("18.8234100573"), "GBP"),
            (Decimal("146.12"), "USD", Decimal("9.7048033333"), "GBP"),
            (Decimal("146.12"), "USD", Decimal("9.7048033333"), "GBP"),
            (Decimal("146.12"), "USD", Decimal("9.7048033333"), "GBP"),
            (Decimal("146.12"), "USD", Decimal("9.7048033333"), "GBP"),
            (Decimal("146.12"), "USD", Decimal("9.7048033333"), "GBP"),
            (Decimal("146.12"), "USD", Decimal("9.7048033333"), "GBP"),
            (Decimal("146.12"), "USD", Decimal("9.7048033333"), "GBP"),
            (Decimal("146.12"), "USD", Decimal("9.7048033333"), "GBP"),
            (Decimal("146.12"), "USD", Decimal("9.7048033333"), "GBP"),
            (Decimal("146.12"), "USD", Decimal("9.7048033333"), "GBP"),
            (Decimal("146.12"), "USD", Decimal("9.7048033333"), "GBP"),
            (Decimal("146.12"), "USD", Decimal("9.7048033333"), "GBP"),
            (Decimal("214.5"), "USD", Decimal("85.47825"), "GBP"),
            (Decimal("214.5"), "USD", Decimal("85.47825"), "GBP"),
            (Decimal("245.5"), "USD", Decimal("16.3052916666"), "GBP"),
            (Decimal("245.5"), "USD", Decimal("16.3052916666"), "GBP"),
            (Decimal("245.5"), "USD", Decimal("16.3052916666"), "GBP"),
            (Decimal("245.5"), "USD", Decimal("16.3052916666"), "GBP"),
            (Decimal("245.5"), "USD", Decimal("16.3052916666"), "GBP"),
            (Decimal("245.5"), "USD", Decimal("16.3052916666"), "GBP"),
            (Decimal("245.5"), "USD", Decimal("16.3052916666"), "GBP"),
            (Decimal("245.5"), "USD", Decimal("16.3052916666"), "GBP"),
            (Decimal("245.5"), "USD", Decimal("16.3052916666"), "GBP"),
            (Decimal("245.5"), "USD", Decimal("16.3052916666"), "GBP"),
            (Decimal("245.5"), "USD", Decimal("16.3052916666"), "GBP"),
            (Decimal("245.5"), "USD", Decimal("16.3052916666"), "GBP"),
            (Decimal("270.2"), "USD", Decimal("215.3494"), "GBP"),
            (Decimal("485.45"), "USD", Decimal("386.90365"), "GBP"),
            (Decimal("485.45"), "USD", Decimal("193.451825"), "GBP"),
            (Decimal("485.45"), "USD", Decimal("386.90365"), "GBP"),
            (Decimal("485.45"), "USD", Decimal("193.451825"), "GBP"),
            (Decimal("485.45"), "USD", Decimal("193.451825"), "GBP"),
            (Decimal("485.45"), "USD", Decimal("193.451825"), "GBP"),
            (Decimal("485.45"), "USD", Decimal("193.451825"), "GBP"),
            (Decimal("485.45"), "USD", Decimal("193.451825"), "GBP"),
            (Decimal("686.5"), "USD", Decimal("273.57025"), "GBP"),
            (Decimal("686.5"), "USD", Decimal("273.57025"), "GBP"),
            (Decimal("1044.23"), "USD", Decimal("832.25131"), "GBP"),
            (Decimal("1045.46"), "USD", Decimal("416.61581"), "GBP"),
            (Decimal("1045.46"), "USD", Decimal("416.61581"), "GBP"),
            (Decimal("1145.44"), "USD", Decimal("456.45784"), "GBP"),
            (Decimal("1145.44"), "USD", Decimal("456.45784"), "GBP"),
            (Decimal("1245.64"), "USD", Decimal("496.38754"), "GBP"),
            (Decimal("1245.64"), "USD", Decimal("496.38754"), "GBP"),
            (Decimal("1344.64"), "USD", Decimal("1071.67808"), "GBP"),
            (Decimal("1454.64"), "USD", Decimal("1159.34808"), "GBP"),
            # This is an important case to test since JPY's lowest denomination is 1 yen
            # and this verifies we're handling this as 9764 yen instead of 97.64 yen
            # NOTE: This is 12350 yen in the file but there's a discount that brings it to 9764 yen
            (Decimal("9764"), "JPY", Decimal("4.1397346665"), "GBP"),
            (Decimal("9764"), "JPY", Decimal("4.1397346665"), "GBP"),
            (Decimal("9764"), "JPY", Decimal("4.1397346665"), "GBP"),
            (Decimal("9764"), "JPY", Decimal("4.1397346665"), "GBP"),
            (Decimal("9764"), "JPY", Decimal("4.1397346665"), "GBP"),
            (Decimal("9764"), "JPY", Decimal("4.1397346665"), "GBP"),
            (Decimal("9764"), "JPY", Decimal("4.1397346665"), "GBP"),
            (Decimal("9764"), "JPY", Decimal("4.1397346665"), "GBP"),
            (Decimal("9764"), "JPY", Decimal("4.1397346665"), "GBP"),
            (Decimal("9764"), "JPY", Decimal("4.1397346665"), "GBP"),
            (Decimal("9764"), "JPY", Decimal("4.1397346665"), "GBP"),
            (Decimal("9764"), "JPY", Decimal("4.1397346665"), "GBP"),
        ]

    def test_database_query_with_managed_viewsets_ff(self):
        with patch("posthoganalytics.feature_enabled", return_value=True):
            self._create_managed_viewsets()

            response = self._run_revenue_example_external_tables_query()
            results = response.results

            # Sort results by the original amount just to guarantee order
            results.sort(key=lambda x: x[2])

            # We only care about 4 of the columns (amount, currency, converted_amount, converted_currency)
            results = [row[2:-1] for row in results]

            assert results == [
                # This is an important case, it's got a value in the DB but discounts bring it to 0
                (Decimal("0"), "USD", Decimal("0"), "GBP"),
                (Decimal("0.12"), "USD", Decimal("0.09564"), "GBP"),
                (Decimal("0.43"), "USD", Decimal("0.34271"), "GBP"),
                (Decimal("0.43"), "USD", Decimal("0.171355"), "GBP"),
                (Decimal("0.43"), "USD", Decimal("0.34271"), "GBP"),
                (Decimal("0.43"), "USD", Decimal("0.171355"), "GBP"),
                (Decimal("0.43"), "USD", Decimal("0.171355"), "GBP"),
                (Decimal("0.43"), "USD", Decimal("0.171355"), "GBP"),
                (Decimal("0.43"), "USD", Decimal("0.171355"), "GBP"),
                (Decimal("0.43"), "USD", Decimal("0.171355"), "GBP"),
                (Decimal("1.23"), "EUR", Decimal("1.0189273464"), "GBP"),
                (Decimal("3.43"), "USD", Decimal("1.366855"), "GBP"),
                (Decimal("3.43"), "USD", Decimal("1.366855"), "GBP"),
                (Decimal("14.45"), "USD", Decimal("5.758325"), "GBP"),
                (Decimal("14.45"), "USD", Decimal("5.758325"), "GBP"),
                (Decimal("24.5"), "GBP", Decimal("24.5"), "GBP"),
                (Decimal("46.66"), "USD", Decimal("18.59401"), "GBP"),
                (Decimal("46.66"), "USD", Decimal("18.59401"), "GBP"),
                (Decimal("54.99"), "USD", Decimal("43.82703"), "GBP"),
                (Decimal("88.88"), "USD", Decimal("70.83736"), "GBP"),
                (Decimal("90.7"), "USD", Decimal("72.2879"), "GBP"),
                (Decimal("90.7"), "USD", Decimal("72.2879"), "GBP"),
                (Decimal("104.35"), "USD", Decimal("83.16695"), "GBP"),
                (Decimal("145.5"), "BRL", Decimal("18.8234100573"), "GBP"),
                (Decimal("146.12"), "USD", Decimal("9.7048033333"), "GBP"),
                (Decimal("146.12"), "USD", Decimal("9.7048033333"), "GBP"),
                (Decimal("146.12"), "USD", Decimal("9.7048033333"), "GBP"),
                (Decimal("146.12"), "USD", Decimal("9.7048033333"), "GBP"),
                (Decimal("146.12"), "USD", Decimal("9.7048033333"), "GBP"),
                (Decimal("146.12"), "USD", Decimal("9.7048033333"), "GBP"),
                (Decimal("146.12"), "USD", Decimal("9.7048033333"), "GBP"),
                (Decimal("146.12"), "USD", Decimal("9.7048033333"), "GBP"),
                (Decimal("146.12"), "USD", Decimal("9.7048033333"), "GBP"),
                (Decimal("146.12"), "USD", Decimal("9.7048033333"), "GBP"),
                (Decimal("146.12"), "USD", Decimal("9.7048033333"), "GBP"),
                (Decimal("146.12"), "USD", Decimal("9.7048033333"), "GBP"),
                (Decimal("214.5"), "USD", Decimal("85.47825"), "GBP"),
                (Decimal("214.5"), "USD", Decimal("85.47825"), "GBP"),
                (Decimal("245.5"), "USD", Decimal("16.3052916666"), "GBP"),
                (Decimal("245.5"), "USD", Decimal("16.3052916666"), "GBP"),
                (Decimal("245.5"), "USD", Decimal("16.3052916666"), "GBP"),
                (Decimal("245.5"), "USD", Decimal("16.3052916666"), "GBP"),
                (Decimal("245.5"), "USD", Decimal("16.3052916666"), "GBP"),
                (Decimal("245.5"), "USD", Decimal("16.3052916666"), "GBP"),
                (Decimal("245.5"), "USD", Decimal("16.3052916666"), "GBP"),
                (Decimal("245.5"), "USD", Decimal("16.3052916666"), "GBP"),
                (Decimal("245.5"), "USD", Decimal("16.3052916666"), "GBP"),
                (Decimal("245.5"), "USD", Decimal("16.3052916666"), "GBP"),
                (Decimal("245.5"), "USD", Decimal("16.3052916666"), "GBP"),
                (Decimal("245.5"), "USD", Decimal("16.3052916666"), "GBP"),
                (Decimal("270.2"), "USD", Decimal("215.3494"), "GBP"),
                (Decimal("485.45"), "USD", Decimal("386.90365"), "GBP"),
                (Decimal("485.45"), "USD", Decimal("193.451825"), "GBP"),
                (Decimal("485.45"), "USD", Decimal("386.90365"), "GBP"),
                (Decimal("485.45"), "USD", Decimal("193.451825"), "GBP"),
                (Decimal("485.45"), "USD", Decimal("193.451825"), "GBP"),
                (Decimal("485.45"), "USD", Decimal("193.451825"), "GBP"),
                (Decimal("485.45"), "USD", Decimal("193.451825"), "GBP"),
                (Decimal("485.45"), "USD", Decimal("193.451825"), "GBP"),
                (Decimal("686.5"), "USD", Decimal("273.57025"), "GBP"),
                (Decimal("686.5"), "USD", Decimal("273.57025"), "GBP"),
                (Decimal("1044.23"), "USD", Decimal("832.25131"), "GBP"),
                (Decimal("1045.46"), "USD", Decimal("416.61581"), "GBP"),
                (Decimal("1045.46"), "USD", Decimal("416.61581"), "GBP"),
                (Decimal("1145.44"), "USD", Decimal("456.45784"), "GBP"),
                (Decimal("1145.44"), "USD", Decimal("456.45784"), "GBP"),
                (Decimal("1245.64"), "USD", Decimal("496.38754"), "GBP"),
                (Decimal("1245.64"), "USD", Decimal("496.38754"), "GBP"),
                (Decimal("1344.64"), "USD", Decimal("1071.67808"), "GBP"),
                (Decimal("1454.64"), "USD", Decimal("1159.34808"), "GBP"),
                # This is an important case to test since JPY's lowest denomination is 1 yen
                # and this verifies we're handling this as 9764 yen instead of 97.64 yen
                # NOTE: This is 12350 yen in the file but there's a discount that brings it to 9764 yen
                (Decimal("9764"), "JPY", Decimal("4.1397346665"), "GBP"),
                (Decimal("9764"), "JPY", Decimal("4.1397346665"), "GBP"),
                (Decimal("9764"), "JPY", Decimal("4.1397346665"), "GBP"),
                (Decimal("9764"), "JPY", Decimal("4.1397346665"), "GBP"),
                (Decimal("9764"), "JPY", Decimal("4.1397346665"), "GBP"),
                (Decimal("9764"), "JPY", Decimal("4.1397346665"), "GBP"),
                (Decimal("9764"), "JPY", Decimal("4.1397346665"), "GBP"),
                (Decimal("9764"), "JPY", Decimal("4.1397346665"), "GBP"),
                (Decimal("9764"), "JPY", Decimal("4.1397346665"), "GBP"),
                (Decimal("9764"), "JPY", Decimal("4.1397346665"), "GBP"),
                (Decimal("9764"), "JPY", Decimal("4.1397346665"), "GBP"),
                (Decimal("9764"), "JPY", Decimal("4.1397346665"), "GBP"),
            ]
