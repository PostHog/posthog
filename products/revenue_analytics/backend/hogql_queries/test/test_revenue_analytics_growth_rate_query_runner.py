from freezegun import freeze_time
from pathlib import Path
from datetime import date
from decimal import Decimal

from posthog.models.utils import uuid7
from products.revenue_analytics.backend.hogql_queries.revenue_analytics_growth_rate_query_runner import (
    RevenueAnalyticsGrowthRateQueryRunner,
)
from posthog.schema import (
    CurrencyCode,
    DateRange,
    RevenueSources,
    RevenueAnalyticsGrowthRateQuery,
    RevenueAnalyticsGrowthRateQueryResponse,
)
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    snapshot_clickhouse_queries,
)
from posthog.warehouse.models import ExternalDataSchema

from products.revenue_analytics.backend.views.revenue_analytics_charge_view import (
    STRIPE_CHARGE_RESOURCE_NAME,
)
from posthog.warehouse.test.utils import create_data_warehouse_table_from_csv
from products.revenue_analytics.backend.hogql_queries.test.data.structure import (
    REVENUE_ANALYTICS_CONFIG_SAMPLE_EVENT,
    STRIPE_CHARGE_COLUMNS,
)

TEST_BUCKET = "test_storage_bucket-posthog.revenue_analytics.growth_rate_query_runner.stripe_charges"


@snapshot_clickhouse_queries
class TestRevenueAnalyticsGrowthRateQueryRunner(ClickhouseTestMixin, APIBaseTest):
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

    def _run_revenue_analytics_growth_rate_query(
        self,
        date_range: DateRange | None = None,
        revenue_sources: RevenueSources | None = None,
    ):
        if date_range is None:
            date_range: DateRange = DateRange(date_from="all")
        if revenue_sources is None:
            revenue_sources = RevenueSources(events=[], dataWarehouseSources=[str(self.source.id)])

        with freeze_time(self.QUERY_TIMESTAMP):
            query = RevenueAnalyticsGrowthRateQuery(dateRange=date_range, revenueSources=revenue_sources)
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

    def test_no_crash_when_no_source_is_selected(self):
        results = self._run_revenue_analytics_growth_rate_query(
            revenue_sources=RevenueSources(events=[], dataWarehouseSources=[]),
        ).results

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

    def test_with_events_data(self):
        s1 = str(uuid7("2023-12-02"))
        s2 = str(uuid7("2024-01-03"))
        self._create_purchase_events(
            [
                ("p1", [("2023-12-02", s1, 42, "USD")]),
                ("p2", [("2024-01-03", s2, 43, "BRL")]),
            ]
        )

        results = self._run_revenue_analytics_growth_rate_query(
            revenue_sources=RevenueSources(events=["purchase"], dataWarehouseSources=[]),
        ).results

        self.assertEqual(
            results,
            [
                (date(2023, 12, 1), Decimal("33.2094"), None, None, None, None),
                (
                    date(2024, 1, 1),
                    Decimal("6.9202333048"),
                    Decimal("33.2094"),
                    Decimal("-0.7916182374"),
                    Decimal("-0.7916182374"),
                    Decimal("-0.7916182374"),
                ),
            ],
        )

    def test_with_events_data_and_currency_aware_divider(self):
        self.team.revenue_analytics_config.events = [
            REVENUE_ANALYTICS_CONFIG_SAMPLE_EVENT.model_copy(update={"currencyAwareDecimal": True})
        ]
        self.team.revenue_analytics_config.save()

        s1 = str(uuid7("2023-12-02"))
        s2 = str(uuid7("2024-01-03"))
        self._create_purchase_events(
            [
                ("p1", [("2023-12-02", s1, 4200, "USD")]),
                ("p2", [("2024-01-03", s2, 4300, "BRL")]),
            ]
        )

        results = self._run_revenue_analytics_growth_rate_query(
            revenue_sources=RevenueSources(events=["purchase"], dataWarehouseSources=[]),
        ).results

        self.assertEqual(
            results,
            [
                (date(2023, 12, 1), Decimal("33.2094"), None, None, None, None),
                (
                    date(2024, 1, 1),
                    Decimal("6.9202333048"),
                    Decimal("33.2094"),
                    Decimal("-0.7916182374"),
                    Decimal("-0.7916182374"),
                    Decimal("-0.7916182374"),
                ),
            ],
        )
