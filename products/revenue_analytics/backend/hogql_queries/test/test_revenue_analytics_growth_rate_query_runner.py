from freezegun import freeze_time
from pathlib import Path
from datetime import date
from decimal import Decimal

from products.revenue_analytics.backend.hogql_queries.revenue_analytics_growth_rate_query_runner import (
    RevenueAnalyticsGrowthRateQueryRunner,
)
from products.revenue_analytics.backend.models import STRIPE_DATA_WAREHOUSE_CHARGE_IDENTIFIER
from posthog.schema import (
    DateRange,
    RevenueAnalyticsGrowthRateQuery,
    RevenueAnalyticsGrowthRateQueryResponse,
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
)

TEST_BUCKET = "test_storage_bucket-posthog.revenue_analytics.growth_rate_query_runner.stripe_charges"


@snapshot_clickhouse_queries
class TestRevenueAnalyticsGrowthRateQueryRunner(ClickhouseTestMixin, APIBaseTest):
    QUERY_TIMESTAMP = "2025-02-15"

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

    def _run_revenue_analytics_growth_rate_query(self):
        with freeze_time(self.QUERY_TIMESTAMP):
            query = RevenueAnalyticsGrowthRateQuery(dateRange=DateRange(date_from="-30d"))
            runner = RevenueAnalyticsGrowthRateQueryRunner(
                team=self.team,
                query=query,
            )

            response = runner.calculate()
            RevenueAnalyticsGrowthRateQueryResponse.model_validate(response)

            return response

    def test_no_crash_when_no_data(self):
        self.table.delete()
        results = self._run_revenue_analytics_growth_rate_query().results

        self.assertEqual(results, [])

    def test_with_data(self):
        results = self._run_revenue_analytics_growth_rate_query().results

        # Month, MRR, Previous MRR, Growth Rate
        self.assertEqual(
            results,
            [
                (date(2025, 4, 1), Decimal("723.3846543563"), Decimal("674.7379876897"), Decimal("0.0720971215")),
                (date(2025, 3, 1), Decimal("674.7379876897"), Decimal("674.6747652889"), Decimal("0.0000937080")),
                (date(2025, 2, 1), Decimal("674.6747652889"), Decimal("253.9594324913"), Decimal("1.6566241650")),
            ],
        )
