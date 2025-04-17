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
    QUERY_TIMESTAMP = "2025-04-21"

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

    def _run_revenue_analytics_growth_rate_query(self, date_range: DateRange | None = None):
        if date_range is None:
            date_range: DateRange = DateRange(date_from="all")

        with freeze_time(self.QUERY_TIMESTAMP):
            query = RevenueAnalyticsGrowthRateQuery(dateRange=date_range)
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

        # Month, MRR, Previous MRR, Growth Rate, 3M Growth Rate, 6M Growth Rate
        self.assertEqual(
            results,
            [
                (
                    date(2025, 1, 1),
                    Decimal("253.9594324913"),
                    None,
                    None,
                    None,
                    None,
                ),
                (
                    date(2025, 2, 1),
                    Decimal("1095.3900980864"),
                    Decimal("253.9594324913"),
                    Decimal("3.31324833"),
                    Decimal("3.31324833"),
                    Decimal("3.31324833"),
                ),
                (
                    date(2025, 3, 1),
                    Decimal("674.8644324913"),
                    Decimal("1095.3900980864"),
                    Decimal("-0.383904936"),
                    Decimal("1.464671697"),
                    Decimal("1.464671697"),
                ),
                (
                    date(2025, 4, 1),
                    Decimal("399.8994324913"),
                    Decimal("674.8644324913"),
                    Decimal("-0.4074373855"),
                    Decimal("0.8406353362"),
                    Decimal("0.8406353362"),
                ),
            ],
        )

    def test_with_data_and_date_range(self):
        results = self._run_revenue_analytics_growth_rate_query(
            date_range=DateRange(date_from="2025-02-03", date_to="2025-03-04")
        ).results

        self.assertEqual(
            results,
            [
                (
                    date(2025, 2, 1),
                    Decimal("935.9900980864"),
                    None,
                    None,
                    None,
                    None,
                ),
                (
                    date(2025, 3, 1),
                    Decimal("494.8644324913"),
                    Decimal("935.9900980864"),
                    Decimal("-0.47129309"),
                    Decimal("-0.47129309"),
                    Decimal("-0.47129309"),
                ),
            ],
        )
