from freezegun import freeze_time
from pathlib import Path
from decimal import Decimal

from posthog.models.utils import uuid7
from products.revenue_analytics.backend.hogql_queries.revenue_analytics_overview_query_runner import (
    RevenueAnalyticsOverviewQueryRunner,
)
from products.revenue_analytics.backend.models import STRIPE_DATA_WAREHOUSE_CHARGE_IDENTIFIER
from posthog.schema import (
    CurrencyCode,
    DateRange,
    RevenueSources,
    RevenueAnalyticsOverviewQuery,
    RevenueAnalyticsOverviewQueryResponse,
    RevenueAnalyticsOverviewItemKey,
    RevenueAnalyticsOverviewItem,
)
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    snapshot_clickhouse_queries,
)
from posthog.warehouse.models import ExternalDataSchema

from posthog.warehouse.test.utils import create_data_warehouse_table_from_csv
from products.revenue_analytics.backend.hogql_queries.test.data.structure import (
    REVENUE_ANALYTICS_CONFIG_SAMPLE_EVENT,
    STRIPE_CHARGE_COLUMNS,
)

TEST_BUCKET = "test_storage_bucket-posthog.revenue_analytics.overview_query_runner.stripe_charges"


@snapshot_clickhouse_queries
class TestRevenueAnalyticsOverviewQueryRunner(ClickhouseTestMixin, APIBaseTest):
    QUERY_TIMESTAMP = "2025-02-15"

    def _create_purchase_events(self, data):
        person_result = []
        for distinct_id, timestamps in data:
            with freeze_time(timestamps[0][0]):
                person = _create_person(
                    team_id=self.team.pk,
                    distinct_ids=[distinct_id],
                    properties={
                        "name": distinct_id,
                        **({"email": "test@posthog.com"} if distinct_id == "test" else {}),
                    },
                )
            event_ids: list[str] = []
            for timestamp, session_id, revenue, currency in timestamps:
                event_ids.append(
                    _create_event(
                        team=self.team,
                        event="purchase",
                        distinct_id=distinct_id,
                        timestamp=timestamp,
                        properties={
                            "$session_id": session_id,
                            "revenue": revenue,
                            "currency": currency,
                        },
                    )
                )
            person_result.append((person, event_ids))
        return person_result

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

        self.team.revenue_analytics_config.base_currency = CurrencyCode.GBP.value
        self.team.revenue_analytics_config.events = [REVENUE_ANALYTICS_CONFIG_SAMPLE_EVENT]
        self.team.revenue_analytics_config.save()

    def tearDown(self):
        self.cleanUpFilesystem()
        super().tearDown()

    def _run_revenue_analytics_overview_query(
        self,
        date_range: DateRange | None = None,
        revenue_sources: RevenueSources | None = None,
    ):
        if date_range is None:
            date_range = DateRange(date_from="-30d")
        if revenue_sources is None:
            revenue_sources = RevenueSources(events=[], dataWarehouseSources=[str(self.source.id)])

        with freeze_time(self.QUERY_TIMESTAMP):
            query = RevenueAnalyticsOverviewQuery(dateRange=date_range, revenueSources=revenue_sources)
            runner = RevenueAnalyticsOverviewQueryRunner(
                team=self.team,
                query=query,
            )

            response = runner.calculate()
            RevenueAnalyticsOverviewQueryResponse.model_validate(response)

            return response

    def test_no_crash_when_no_data(self):
        self.table.delete()
        results = self._run_revenue_analytics_overview_query().results

        self.assertEqual(
            results,
            [
                RevenueAnalyticsOverviewItem(key=RevenueAnalyticsOverviewItemKey.REVENUE, value=0.0),
                RevenueAnalyticsOverviewItem(key=RevenueAnalyticsOverviewItemKey.PAYING_CUSTOMER_COUNT, value=0.0),
                RevenueAnalyticsOverviewItem(key=RevenueAnalyticsOverviewItemKey.AVG_REVENUE_PER_CUSTOMER, value=0.0),
            ],
        )

    def test_with_data(self):
        results = self._run_revenue_analytics_overview_query().results

        self.assertEqual(
            results,
            [
                RevenueAnalyticsOverviewItem(
                    key=RevenueAnalyticsOverviewItemKey.REVENUE, value=Decimal("1349.3495305777")
                ),
                RevenueAnalyticsOverviewItem(key=RevenueAnalyticsOverviewItemKey.PAYING_CUSTOMER_COUNT, value=5),
                RevenueAnalyticsOverviewItem(
                    key=RevenueAnalyticsOverviewItemKey.AVG_REVENUE_PER_CUSTOMER, value=Decimal("269.8699061155")
                ),
            ],
        )

    def test_with_events_data(self):
        s1 = str(uuid7("2023-12-02"))
        s2 = str(uuid7("2024-01-03"))
        s3 = str(uuid7("2024-02-04"))
        self._create_purchase_events(
            [
                ("p1", [("2023-12-02", s1, 4200, "USD")]),
                ("p2", [("2024-01-01", s2, 4300, "BRL"), ("2024-01-02", s3, 8700, "BRL")]),  # 2 events, 1 customer
            ]
        )

        results = self._run_revenue_analytics_overview_query(
            date_range=DateRange(date_from="2023-11-01", date_to="2024-01-31"),
            revenue_sources=RevenueSources(events=["purchase"], dataWarehouseSources=[]),
        ).results

        self.assertEqual(
            results,
            [
                RevenueAnalyticsOverviewItem(
                    key=RevenueAnalyticsOverviewItemKey.REVENUE, value=Decimal("54.2331251204")
                ),
                RevenueAnalyticsOverviewItem(key=RevenueAnalyticsOverviewItemKey.PAYING_CUSTOMER_COUNT, value=2),
                RevenueAnalyticsOverviewItem(
                    key=RevenueAnalyticsOverviewItemKey.AVG_REVENUE_PER_CUSTOMER, value=Decimal("27.1165625602")
                ),
            ],
        )
