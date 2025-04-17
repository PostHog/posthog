from freezegun import freeze_time
from pathlib import Path

from products.revenue_analytics.backend.hogql_queries.revenue_analytics_top_customers_query_runner import (
    RevenueAnalyticsTopCustomersQueryRunner,
)
from products.revenue_analytics.backend.models import (
    STRIPE_DATA_WAREHOUSE_CHARGE_IDENTIFIER,
    STRIPE_DATA_WAREHOUSE_CUSTOMER_IDENTIFIER,
)
from posthog.schema import (
    DateRange,
    RevenueAnalyticsTopCustomersQuery,
    RevenueAnalyticsTopCustomersQueryResponse,
)
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    snapshot_clickhouse_queries,
)
from posthog.warehouse.models import ExternalDataSchema

from posthog.warehouse.test.utils import create_data_warehouse_table_from_csv
from products.revenue_analytics.backend.hogql_queries.test.data.structure import (
    REVENUE_TRACKING_CONFIG,
    STRIPE_CHARGE_COLUMNS,
    STRIPE_CUSTOMER_COLUMNS,
)

TEST_BUCKET = "test_storage_bucket-posthog.revenue_analytics.top_customers_query_runner.stripe_charges"


@snapshot_clickhouse_queries
class TestRevenueAnalyticsTopCustomersQueryRunner(ClickhouseTestMixin, APIBaseTest):
    QUERY_TIMESTAMP = "2025-02-15"

    def setUp(self):
        super().setUp()

        self.charges_csv_path = Path(__file__).parent / "data" / "stripe_charges.csv"
        self.charges_table, self.source, self.credential, self.charges_csv_df, self.cleanUpChargesFilesystem = (
            create_data_warehouse_table_from_csv(
                self.charges_csv_path,
                "stripe_charge",
                STRIPE_CHARGE_COLUMNS,
                TEST_BUCKET,
                self.team,
            )
        )

        self.customers_csv_path = Path(__file__).parent / "data" / "stripe_customers.csv"
        self.customers_table, _, _, self.customers_csv_df, self.cleanUpCustomersFilesystem = (
            create_data_warehouse_table_from_csv(
                self.customers_csv_path,
                "stripe_customer",
                STRIPE_CUSTOMER_COLUMNS,
                TEST_BUCKET,
                self.team,
                credential=self.credential,
                source=self.source,
            )
        )

        # Besides the default creations above, also create the external data schemas
        # because this is required by the `RevenueAnalyticsRevenueView` to find the right tables
        self.charges_schema = ExternalDataSchema.objects.create(
            team=self.team,
            name=STRIPE_DATA_WAREHOUSE_CHARGE_IDENTIFIER,
            source=self.source,
            table=self.charges_table,
            should_sync=True,
            last_synced_at="2024-01-01",
        )

        self.customers_schema = ExternalDataSchema.objects.create(
            team=self.team,
            name=STRIPE_DATA_WAREHOUSE_CUSTOMER_IDENTIFIER,
            source=self.source,
            table=self.customers_table,
            should_sync=True,
            last_synced_at="2024-01-01",
        )

        self.team.revenue_tracking_config = REVENUE_TRACKING_CONFIG.model_dump()
        self.team.save()

    def tearDown(self):
        self.cleanUpChargesFilesystem()
        self.cleanUpCustomersFilesystem()
        super().tearDown()

    def _run_revenue_analytics_top_customers_query(self):
        with freeze_time(self.QUERY_TIMESTAMP):
            query = RevenueAnalyticsTopCustomersQuery(dateRange=DateRange(date_from="-30d"))
            runner = RevenueAnalyticsTopCustomersQueryRunner(
                team=self.team,
                query=query,
            )

            response = runner.calculate()
            RevenueAnalyticsTopCustomersQueryResponse.model_validate(response)

            return response

    def test_no_crash_when_no_charges_data(self):
        self.charges_table.delete()
        results = self._run_revenue_analytics_top_customers_query().results

        self.assertEqual(results, [])

    def test_no_crash_when_no_customers_data(self):
        self.customers_table.delete()
        results = self._run_revenue_analytics_top_customers_query().results

        self.assertEqual(results, [])

    def test_with_data(self):
        results = self._run_revenue_analytics_top_customers_query().results

        # Mostly interested in the number of results
        # but also the query snapshot is more important than the results
        self.assertEqual(len(results), 16)
