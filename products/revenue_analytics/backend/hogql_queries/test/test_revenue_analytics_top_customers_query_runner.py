from freezegun import freeze_time
from pathlib import Path
from decimal import Decimal
import datetime

from posthog.models.utils import uuid7
from products.revenue_analytics.backend.hogql_queries.revenue_analytics_top_customers_query_runner import (
    RevenueAnalyticsTopCustomersQueryRunner,
)
from products.revenue_analytics.backend.views.revenue_analytics_charge_view import (
    STRIPE_CHARGE_RESOURCE_NAME,
)
from products.revenue_analytics.backend.views.revenue_analytics_customer_view import (
    STRIPE_CUSTOMER_RESOURCE_NAME,
)
from posthog.schema import (
    CurrencyCode,
    DateRange,
    RevenueSources,
    RevenueAnalyticsTopCustomersQuery,
    RevenueAnalyticsTopCustomersQueryResponse,
    RevenueAnalyticsTopCustomersGroupBy,
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
    STRIPE_CUSTOMER_COLUMNS,
)

TEST_BUCKET = "test_storage_bucket-posthog.revenue_analytics.top_customers_query_runner.stripe_charges"


@snapshot_clickhouse_queries
class TestRevenueAnalyticsTopCustomersQueryRunner(ClickhouseTestMixin, APIBaseTest):
    QUERY_TIMESTAMP = "2025-04-21"

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
        # because this is required by the `RevenueAnalyticsBaseView` to find the right tables
        self.charges_schema = ExternalDataSchema.objects.create(
            team=self.team,
            name=STRIPE_CHARGE_RESOURCE_NAME,
            source=self.source,
            table=self.charges_table,
            should_sync=True,
            last_synced_at="2024-01-01",
        )

        self.customers_schema = ExternalDataSchema.objects.create(
            team=self.team,
            name=STRIPE_CUSTOMER_RESOURCE_NAME,
            source=self.source,
            table=self.customers_table,
            should_sync=True,
            last_synced_at="2024-01-01",
        )

        self.team.revenue_analytics_config.base_currency = CurrencyCode.GBP.value
        self.team.revenue_analytics_config.events = [REVENUE_ANALYTICS_CONFIG_SAMPLE_EVENT]
        self.team.revenue_analytics_config.save()

    def tearDown(self):
        self.cleanUpChargesFilesystem()
        self.cleanUpCustomersFilesystem()
        super().tearDown()

    def _run_revenue_analytics_top_customers_query(
        self,
        *,
        date_range: DateRange | None = None,
        group_by: RevenueAnalyticsTopCustomersGroupBy | None = None,
        revenue_sources: RevenueSources | None = None,
    ):
        if date_range is None:
            date_range: DateRange = DateRange(date_from="all")

        if group_by is None:
            group_by: RevenueAnalyticsTopCustomersGroupBy = "month"

        if revenue_sources is None:
            revenue_sources = RevenueSources(events=[], dataWarehouseSources=[str(self.source.id)])

        with freeze_time(self.QUERY_TIMESTAMP):
            query = RevenueAnalyticsTopCustomersQuery(
                dateRange=date_range,
                groupBy=group_by,
                revenueSources=revenue_sources,
            )
            runner = RevenueAnalyticsTopCustomersQueryRunner(team=self.team, query=query)

            response = runner.calculate()
            RevenueAnalyticsTopCustomersQueryResponse.model_validate(response)

            return response

    def test_no_crash_when_no_charges_data(self):
        self.charges_table.delete()
        results = self._run_revenue_analytics_top_customers_query().results

        self.assertEqual(results, [])

    def test_no_crash_when_no_source_is_selected(self):
        results = self._run_revenue_analytics_top_customers_query(
            revenue_sources=RevenueSources(events=[], dataWarehouseSources=[]),
        ).results

        self.assertEqual(results, [])

    def test_without_customers_data(self):
        self.customers_table.delete()
        results = self._run_revenue_analytics_top_customers_query().results

        # Mostly interested in the number of results
        # but also the query snapshot is more important than the results
        self.assertEqual(len(results), 16)

    def test_with_data(self):
        results = self._run_revenue_analytics_top_customers_query().results

        # Mostly interested in the number of results
        # but also the query snapshot is more important than the results
        self.assertEqual(len(results), 16)

    def test_with_data_and_limited_date_range(self):
        results = self._run_revenue_analytics_top_customers_query(
            date_range=DateRange(date_from="2025-02-03", date_to="2025-03-04"),
        ).results

        self.assertEqual(len(results), 9)

    def test_with_data_group_by_all(self):
        results = self._run_revenue_analytics_top_customers_query(group_by="all").results

        # Only one entry for each customer, sorted by ID
        results = sorted(results, key=lambda x: x[1])
        self.assertEqual(
            results,
            [
                ("John Doe", "cus_1", Decimal("480.34"), "all"),
                ("Jane Doe", "cus_2", Decimal("725.6066001453"), "all"),
                ("John Smith", "cus_3", Decimal("247.8088762801"), "all"),
                ("Jane Smith", "cus_4", Decimal("570.4584866436"), "all"),
                ("John Doe Jr", "cus_5", Decimal("399.8994324913"), "all"),
            ],
        )

    def test_with_events_data(self):
        s1 = str(uuid7("2023-12-02"))
        s2 = str(uuid7("2024-01-03"))
        s3 = str(uuid7("2024-02-04"))
        self._create_purchase_events(
            [
                ("p1", [("2023-12-02", s1, 42, "USD")]),
                ("p2", [("2024-01-01", s2, 43, "BRL"), ("2024-01-02", s3, 87, "BRL")]),  # 2 events, 1 customer
            ]
        )

        results = self._run_revenue_analytics_top_customers_query(
            date_range=DateRange(date_from="2023-11-01", date_to="2024-01-31"),
            revenue_sources=RevenueSources(events=["purchase"], dataWarehouseSources=[]),
        ).results

        self.assertEqual(
            results,
            [
                ("", "p1", Decimal("33.2094"), datetime.date(2023, 12, 1)),
                ("", "p2", Decimal("21.0237251204"), datetime.date(2024, 1, 1)),
            ],
        )

    def test_with_events_data_and_currency_aware_divider(self):
        self.team.revenue_analytics_config.events = [
            REVENUE_ANALYTICS_CONFIG_SAMPLE_EVENT.model_copy(update={"currencyAwareDecimal": True})
        ]
        self.team.revenue_analytics_config.save()

        s1 = str(uuid7("2023-12-02"))
        s2 = str(uuid7("2024-01-03"))
        s3 = str(uuid7("2024-02-04"))
        self._create_purchase_events(
            [
                ("p1", [("2023-12-02", s1, 4200, "USD")]),
                ("p2", [("2024-01-01", s2, 4300, "BRL"), ("2024-01-02", s3, 8700, "BRL")]),  # 2 events, 1 customer
            ]
        )

        results = self._run_revenue_analytics_top_customers_query(
            date_range=DateRange(date_from="2023-11-01", date_to="2024-01-31"),
            revenue_sources=RevenueSources(events=["purchase"], dataWarehouseSources=[]),
        ).results

        self.assertEqual(
            results,
            [
                ("", "p1", Decimal("33.2094"), datetime.date(2023, 12, 1)),
                ("", "p2", Decimal("21.0237251204"), datetime.date(2024, 1, 1)),
            ],
        )
