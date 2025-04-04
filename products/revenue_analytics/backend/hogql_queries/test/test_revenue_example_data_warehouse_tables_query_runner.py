from freezegun import freeze_time
from unittest.case import skip
from unittest.mock import patch

from products.revenue_analytics.backend.hogql_queries.revenue_example_data_warehouse_tables_query_runner import (
    RevenueExampleDataWarehouseTablesQueryRunner,
)
from products.revenue_analytics.backend.models import STRIPE_DATA_WAREHOUSE_CHARGE_IDENTIFIER

from posthog.schema import (
    RevenueExampleDataWarehouseTablesQuery,
    RevenueTrackingConfig,
    RevenueExampleDataWarehouseTablesQueryResponse,
    CurrencyCode,
)
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    snapshot_clickhouse_queries,
)
from posthog.warehouse.models import (
    DataWarehouseTable,
    DataWarehouseCredential,
    ExternalDataSource,
    ExternalDataSchema,
)

REVENUE_TRACKING_CONFIG = RevenueTrackingConfig(baseCurrency=CurrencyCode.GBP, events=[])


@snapshot_clickhouse_queries
class TestRevenueExampleDataWarehouseTablesQueryRunner(ClickhouseTestMixin, APIBaseTest):
    QUERY_TIMESTAMP = "2025-01-29"

    def setUp(self):
        super().setUp()

        self.source = ExternalDataSource.objects.create(
            team=self.team,
            source_id="source_id",
            connection_id="connection_id",
            status=ExternalDataSource.Status.COMPLETED,
            source_type=ExternalDataSource.Type.STRIPE,
        )

        self.credential = DataWarehouseCredential.objects.create(
            team=self.team,
            access_key="test",
            access_secret="test",
        )

        self.table = DataWarehouseTable.objects.create(
            name="stripe_charge",
            format=DataWarehouseTable.TableFormat.Parquet,
            team=self.team,
            credential=self.credential,
            url_pattern="test://localhost",
            columns={
                "id": {"hogql": "StringDatabaseField", "clickhouse": "String", "schema_valid": True},
                "revenue": {"hogql": "FloatDatabaseField", "clickhouse": "Float64", "schema_valid": True},
                "timestamp": {"hogql": "DateTimeDatabaseField", "clickhouse": "DateTime", "schema_valid": True},
            },
        )

        self.schema = ExternalDataSchema.objects.create(
            team=self.team,
            name=STRIPE_DATA_WAREHOUSE_CHARGE_IDENTIFIER,
            source=self.source,
            table=self.table,
            should_sync=True,
            last_synced_at="2024-01-01",
        )

    def _run_revenue_example_external_tables_query(self):
        with freeze_time(self.QUERY_TIMESTAMP):
            query = RevenueExampleDataWarehouseTablesQuery(revenueTrackingConfig=REVENUE_TRACKING_CONFIG)
            runner = RevenueExampleDataWarehouseTablesQueryRunner(team=self.team, query=query)

            response = runner.calculate()
            RevenueExampleDataWarehouseTablesQueryResponse.model_validate(response)

            return response

    def test_no_crash_when_no_data(self):
        self.table.delete()
        results = self._run_revenue_example_external_tables_query().results

        assert len(results) == 0

    # TODO: These fail because it'll complain the table doesn't exist
    # posthog.errors.CHQueryErrorUnknownTable: Code: 60.
    # DB::Exception: Unknown table expression identifier 'stripe_charge'
    @skip("Skipping because it's not implemented in tests")
    @patch("posthoganalytics.feature_enabled", return_value=False)
    def test_database_query(self, feature_enabled_mock):
        response = self._run_revenue_example_external_tables_query()
        results = response.results

        assert len(results) == 3

    # TODO: These fail because it'll complain the table doesn't exist
    # posthog.errors.CHQueryErrorUnknownTable: Code: 60.
    # DB::Exception: Unknown table expression identifier 'stripe_charge'
    @skip("Skipping because it's not implemented in tests")
    @patch("posthoganalytics.feature_enabled", return_value=True)
    def test_database_query_with_currency_conversion(self, feature_enabled_mock):
        response = self._run_revenue_example_external_tables_query()
        results = response.results

        assert len(results) == 3
