from freezegun import freeze_time
from pathlib import Path
from decimal import Decimal
from unittest.mock import ANY

from posthog.models.utils import uuid7
from products.revenue_analytics.backend.hogql_queries.revenue_analytics_insights_query_runner import (
    RevenueAnalyticsInsightsQueryRunner,
)
from posthog.schema import (
    CurrencyCode,
    DateRange,
    PropertyOperator,
    RevenueSources,
    RevenueAnalyticsInsightsQuery,
    RevenueAnalyticsInsightsQueryResponse,
    RevenueAnalyticsInsightsQueryGroupBy,
    IntervalType,
    HogQLQueryModifiers,
    RevenueAnalyticsPropertyFilter,
)
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    snapshot_clickhouse_queries,
)
from posthog.warehouse.models import ExternalDataSchema

from posthog.temporal.data_imports.pipelines.stripe.constants import (
    INVOICE_RESOURCE_NAME as STRIPE_INVOICE_RESOURCE_NAME,
    PRODUCT_RESOURCE_NAME as STRIPE_PRODUCT_RESOURCE_NAME,
)
from posthog.warehouse.test.utils import create_data_warehouse_table_from_csv
from products.revenue_analytics.backend.hogql_queries.test.data.structure import (
    REVENUE_ANALYTICS_CONFIG_SAMPLE_EVENT,
    STRIPE_INVOICE_COLUMNS,
    STRIPE_PRODUCT_COLUMNS,
)

INVOICES_TEST_BUCKET = "test_storage_bucket-posthog.revenue_analytics.insights_query_runner.stripe_invoices"
PRODUCTS_TEST_BUCKET = "test_storage_bucket-posthog.revenue_analytics.insights_query_runner.stripe_products"

LAST_6_MONTHS_LABELS = ["Nov 2024", "Dec 2024", "Jan 2025", "Feb 2025", "Mar 2025", "Apr 2025", "May 2025"]
LAST_6_MONTHS_DAYS = ["2024-11-01", "2024-12-01", "2025-01-01", "2025-02-01", "2025-03-01", "2025-04-01", "2025-05-01"]
LAST_6_MONTHS_FAKEDATETIMES = [ANY] * 7


@snapshot_clickhouse_queries
class TestRevenueAnalyticsInsightsQueryRunner(ClickhouseTestMixin, APIBaseTest):
    QUERY_TIMESTAMP = "2025-05-30"

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

        self.invoices_csv_path = Path(__file__).parent / "data" / "stripe_invoices.csv"
        self.invoices_table, self.source, self.credential, self.invoices_csv_df, self.invoices_cleanup_filesystem = (
            create_data_warehouse_table_from_csv(
                self.invoices_csv_path,
                "stripe_invoice",
                STRIPE_INVOICE_COLUMNS,
                INVOICES_TEST_BUCKET,
                self.team,
            )
        )

        self.products_csv_path = Path(__file__).parent / "data" / "stripe_products.csv"
        self.products_table, _, _, self.products_csv_df, self.products_cleanup_filesystem = (
            create_data_warehouse_table_from_csv(
                self.products_csv_path,
                "stripe_product",
                STRIPE_PRODUCT_COLUMNS,
                PRODUCTS_TEST_BUCKET,
                self.team,
                source=self.source,
                credential=self.credential,
            )
        )

        # Besides the default creations above, also create the external data schema
        # because this is required by the `RevenueAnalyticsBaseView` to find the right tables
        self.products_schema = ExternalDataSchema.objects.create(
            team=self.team,
            name=STRIPE_PRODUCT_RESOURCE_NAME,
            source=self.source,
            table=self.products_table,
            should_sync=True,
            last_synced_at="2024-01-01",
        )

        self.invoices_schema = ExternalDataSchema.objects.create(
            team=self.team,
            name=STRIPE_INVOICE_RESOURCE_NAME,
            source=self.source,
            table=self.invoices_table,
            should_sync=True,
            last_synced_at="2024-01-01",
        )

        self.team.revenue_analytics_config.base_currency = CurrencyCode.GBP.value
        self.team.revenue_analytics_config.events = [REVENUE_ANALYTICS_CONFIG_SAMPLE_EVENT]
        self.team.revenue_analytics_config.save()

    def tearDown(self):
        self.invoices_cleanup_filesystem()
        self.products_cleanup_filesystem()
        super().tearDown()

    def _run_revenue_analytics_insights_query(
        self,
        date_range: DateRange | None = None,
        revenue_sources: RevenueSources | None = None,
        interval: IntervalType | None = None,
        group_by: RevenueAnalyticsInsightsQueryGroupBy | None = None,
        properties: list[RevenueAnalyticsPropertyFilter] | None = None,
    ):
        if date_range is None:
            date_range: DateRange = DateRange(date_from="-6m")
        if revenue_sources is None:
            revenue_sources = RevenueSources(events=[], dataWarehouseSources=[str(self.source.id)])
        if interval is None:
            interval = IntervalType.MONTH
        if group_by is None:
            group_by = RevenueAnalyticsInsightsQueryGroupBy.ALL
        if properties is None:
            properties = []

        with freeze_time(self.QUERY_TIMESTAMP):
            query = RevenueAnalyticsInsightsQuery(
                dateRange=date_range,
                revenueSources=revenue_sources,
                interval=interval,
                groupBy=group_by,
                properties=properties,
                modifiers=HogQLQueryModifiers(formatCsvAllowDoubleQuotes=True),
            )

            runner = RevenueAnalyticsInsightsQueryRunner(
                team=self.team,
                query=query,
            )
            response = runner.calculate()

            RevenueAnalyticsInsightsQueryResponse.model_validate(response)
            return response

    def test_no_crash_when_no_data(self):
        self.invoices_table.delete()
        self.products_table.delete()
        results = self._run_revenue_analytics_insights_query().results

        self.assertEqual(results, [])

    def test_no_crash_when_no_source_is_selected(self):
        results = self._run_revenue_analytics_insights_query(
            revenue_sources=RevenueSources(events=[], dataWarehouseSources=[]),
        ).results

        self.assertEqual(results, [])

    def test_with_data(self):
        results = self._run_revenue_analytics_insights_query().results

        self.assertEqual(
            results,
            [
                {
                    "label": "stripe.posthog_test",
                    "days": LAST_6_MONTHS_DAYS,
                    "labels": LAST_6_MONTHS_LABELS,
                    "data": [
                        0,
                        0,
                        Decimal("11323.97"),
                        Decimal("11888.18"),
                        Decimal("11304.85"),
                        Decimal("11144.98"),
                        Decimal("11122.75"),
                    ],
                    "action": {
                        "days": LAST_6_MONTHS_FAKEDATETIMES,
                        "id": "stripe.posthog_test",
                        "name": "stripe.posthog_test",
                    },
                }
            ],
        )

    def test_with_data_and_date_range(self):
        results = self._run_revenue_analytics_insights_query(
            date_range=DateRange(date_from="2025-02-01", date_to="2025-05-01")
        ).results

        # Restricted to the date range
        self.assertEqual(
            results,
            [
                {
                    "label": "stripe.posthog_test",
                    "days": ["2025-02-01", "2025-03-01", "2025-04-01", "2025-05-01"],
                    "labels": ["Feb 2025", "Mar 2025", "Apr 2025", "May 2025"],
                    "data": [Decimal("11888.18"), Decimal("11304.85"), Decimal("11144.98"), 0],
                    "action": {"days": [ANY] * 4, "id": "stripe.posthog_test", "name": "stripe.posthog_test"},
                }
            ],
        )

    def test_with_empty_data_range(self):
        results = self._run_revenue_analytics_insights_query(
            date_range=DateRange(date_from="2024-12-01", date_to="2024-12-31")
        ).results

        self.assertEqual(results, [])

    def test_with_data_for_product_grouping(self):
        results = self._run_revenue_analytics_insights_query(
            group_by=RevenueAnalyticsInsightsQueryGroupBy.PRODUCT
        ).results

        self.assertEqual(len(results), 6)
        self.assertEqual(
            [result["label"] for result in results],
            [
                "stripe.posthog_test - Product F",
                "stripe.posthog_test - Product D",
                "stripe.posthog_test - Product A",
                "stripe.posthog_test - Product B",
                "stripe.posthog_test - Product C",
                "stripe.posthog_test - Product E",
            ],
        )
        self.assertEqual(
            [result["data"] for result in results],
            [
                [
                    0,
                    0,
                    Decimal("10454.64"),
                    Decimal("10454.64"),
                    Decimal("10454.64"),
                    Decimal("10454.64"),
                    Decimal("10454.64"),
                ],
                [0, 0, Decimal("485.45"), Decimal("485.45"), Decimal("485.45"), Decimal("485.45"), Decimal("485.45")],
                [0, 0, Decimal("123.5"), Decimal("214.5"), Decimal("270.2"), Decimal("104.35"), Decimal("145.5")],
                [0, 0, Decimal("245.5"), Decimal("686.5"), Decimal("90.7"), Decimal("99.99"), Decimal("24.5")],
                [0, 0, Decimal("14.45"), Decimal("46.66"), Decimal("3.43"), Decimal("0.12"), Decimal("12.23")],
                [0, 0, Decimal("0.43"), Decimal("0.43"), Decimal("0.43"), Decimal("0.43"), Decimal("0.43")],
            ],
        )

    def test_with_data_filter(self):
        expected_data = [[0, 0, Decimal("14.45"), Decimal("46.66"), Decimal("3.43"), Decimal("0.12"), Decimal("12.23")]]

        results = self._run_revenue_analytics_insights_query(
            properties=[
                RevenueAnalyticsPropertyFilter(
                    key="product",
                    operator=PropertyOperator.EXACT,
                    value=["Product C"],  # Equivalent to `prod_c` but we're querying by name
                )
            ]
        ).results

        self.assertEqual(len(results), 1)
        self.assertEqual([result["label"] for result in results], ["stripe.posthog_test"])
        self.assertEqual([result["data"] for result in results], expected_data)

        # When grouping results should be exactly the same, just the label changes
        results = self._run_revenue_analytics_insights_query(
            group_by=RevenueAnalyticsInsightsQueryGroupBy.PRODUCT,
            properties=[
                RevenueAnalyticsPropertyFilter(
                    key="product",
                    operator=PropertyOperator.EXACT,
                    value=["Product C"],  # Equivalent to `prod_c` but we're querying by name
                )
            ],
        ).results

        self.assertEqual(len(results), 1)
        self.assertEqual([result["label"] for result in results], ["stripe.posthog_test - Product C"])
        self.assertEqual([result["data"] for result in results], expected_data)

    def test_with_events_data(self):
        s1 = str(uuid7("2024-12-25"))
        s2 = str(uuid7("2025-01-03"))
        self._create_purchase_events(
            [
                ("p1", [("2024-12-25", s1, 42, "USD")]),
                ("p2", [("2025-01-03", s2, 43, "BRL")]),
            ]
        )

        results = self._run_revenue_analytics_insights_query(
            revenue_sources=RevenueSources(events=["purchase"], dataWarehouseSources=[]),
        ).results

        self.assertEqual(
            results,
            [
                {
                    "label": "revenue_analytics.purchase",
                    "days": LAST_6_MONTHS_DAYS,
                    "labels": LAST_6_MONTHS_LABELS,
                    "data": [0, Decimal("33.474"), Decimal("5.5629321819"), 0, 0, 0, 0],
                    "action": {
                        "days": LAST_6_MONTHS_FAKEDATETIMES,
                        "id": "revenue_analytics.purchase",
                        "name": "revenue_analytics.purchase",
                    },
                }
            ],
        )

    def test_with_events_data_and_currency_aware_divider(self):
        self.team.revenue_analytics_config.events = [
            REVENUE_ANALYTICS_CONFIG_SAMPLE_EVENT.model_copy(update={"currencyAwareDecimal": True})
        ]
        self.team.revenue_analytics_config.save()

        s1 = str(uuid7("2024-12-25"))
        s2 = str(uuid7("2025-01-03"))
        self._create_purchase_events(
            [
                ("p1", [("2024-12-25", s1, 42, "USD")]),
                ("p2", [("2025-01-03", s2, 43, "BRL")]),
            ]
        )

        results = self._run_revenue_analytics_insights_query(
            revenue_sources=RevenueSources(events=["purchase"], dataWarehouseSources=[]),
        ).results

        self.assertEqual(
            results,
            [
                {
                    "label": "revenue_analytics.purchase",
                    "days": LAST_6_MONTHS_DAYS,
                    "labels": LAST_6_MONTHS_LABELS,
                    "data": [0, Decimal("0.33474"), Decimal("0.0556293217"), 0, 0, 0, 0],
                    "action": {
                        "days": LAST_6_MONTHS_FAKEDATETIMES,
                        "id": "revenue_analytics.purchase",
                        "name": "revenue_analytics.purchase",
                    },
                }
            ],
        )
