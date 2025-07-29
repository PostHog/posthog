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
    HogQLQueryModifiers,
    PropertyOperator,
    RevenueAnalyticsGrowthRateQuery,
    RevenueAnalyticsGrowthRateQueryResponse,
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

from posthog.warehouse.test.utils import create_data_warehouse_table_from_csv
from products.revenue_analytics.backend.hogql_queries.test.data.structure import (
    REVENUE_ANALYTICS_CONFIG_SAMPLE_EVENT,
    STRIPE_INVOICE_COLUMNS,
    STRIPE_PRODUCT_COLUMNS,
)
from products.revenue_analytics.backend.views.revenue_analytics_invoice_item_view import (
    STRIPE_INVOICE_RESOURCE_NAME,
)
from products.revenue_analytics.backend.views.revenue_analytics_product_view import (
    STRIPE_PRODUCT_RESOURCE_NAME,
)

INVOICE_TEST_BUCKET = "test_storage_bucket-posthog.revenue_analytics.growth_rate_query_runner.stripe_invoices"
PRODUCT_TEST_BUCKET = "test_storage_bucket-posthog.revenue_analytics.growth_rate_query_runner.stripe_products"


@snapshot_clickhouse_queries
class TestRevenueAnalyticsGrowthRateQueryRunner(ClickhouseTestMixin, APIBaseTest):
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
                INVOICE_TEST_BUCKET,
                self.team,
            )
        )

        self.products_csv_path = Path(__file__).parent / "data" / "stripe_products.csv"
        self.products_table, _, _, self.products_csv_df, self.products_cleanup_filesystem = (
            create_data_warehouse_table_from_csv(
                self.products_csv_path,
                "stripe_product",
                STRIPE_PRODUCT_COLUMNS,
                PRODUCT_TEST_BUCKET,
                self.team,
                source=self.source,
                credential=self.credential,
            )
        )

        # Besides the default creations above, also create the external data schemas
        # because this is required by the `RevenueAnalyticsBaseView` to find the right tables
        self.invoices_schema = ExternalDataSchema.objects.create(
            team=self.team,
            name=STRIPE_INVOICE_RESOURCE_NAME,
            source=self.source,
            table=self.invoices_table,
            should_sync=True,
            last_synced_at="2024-01-01",
        )

        self.products_schema = ExternalDataSchema.objects.create(
            team=self.team,
            name=STRIPE_PRODUCT_RESOURCE_NAME,
            source=self.source,
            table=self.products_table,
            should_sync=True,
            last_synced_at="2024-01-01",
        )

        self.team.base_currency = CurrencyCode.GBP.value
        self.team.revenue_analytics_config.events = [REVENUE_ANALYTICS_CONFIG_SAMPLE_EVENT]
        self.team.revenue_analytics_config.save()
        self.team.save()

    def tearDown(self):
        self.invoices_cleanup_filesystem()
        self.products_cleanup_filesystem()
        super().tearDown()

    def _run_revenue_analytics_growth_rate_query(
        self,
        date_range: DateRange | None = None,
        properties: list[RevenueAnalyticsPropertyFilter] | None = None,
    ):
        if date_range is None:
            date_range: DateRange = DateRange(date_from="all")
        if properties is None:
            properties = []

        with freeze_time(self.QUERY_TIMESTAMP):
            query = RevenueAnalyticsGrowthRateQuery(dateRange=date_range, properties=properties)
            runner = RevenueAnalyticsGrowthRateQueryRunner(
                team=self.team,
                query=query,
                modifiers=HogQLQueryModifiers(formatCsvAllowDoubleQuotes=True),
            )

            response = runner.calculate()
            RevenueAnalyticsGrowthRateQueryResponse.model_validate(response)

            return response

    def test_no_crash_when_no_data(self):
        self.invoices_table.delete()
        self.products_table.delete()
        results = self._run_revenue_analytics_growth_rate_query().results

        self.assertEqual(results, [])

    def test_no_crash_when_no_source_is_selected(self):
        results = self._run_revenue_analytics_growth_rate_query(
            properties=[
                RevenueAnalyticsPropertyFilter(
                    key="source",
                    operator=PropertyOperator.EXACT,
                    value=["non-existent-source"],
                )
            ],
        ).results

        self.assertEqual(results, [])

    def test_with_data(self):
        results = self._run_revenue_analytics_growth_rate_query().results

        # Month, MRR, Previous MRR, Growth Rate, 3M Growth Rate, 6M Growth Rate
        self.assertEqual(
            results,
            [
                (date(2025, 1, 1), Decimal("8765.3236433332"), None, None, None, None),
                (
                    date(2025, 2, 1),
                    Decimal("10341.3433233332"),
                    Decimal("8765.3236433332"),
                    Decimal("0.1798016529"),
                    Decimal("0.1798016529"),
                    Decimal("0.1798016529"),
                ),
                (
                    date(2025, 3, 1),
                    Decimal("9116.4659033332"),
                    Decimal("10341.3433233332"),
                    Decimal("-0.1184447108"),
                    Decimal("0.030678471"),
                    Decimal("0.030678471"),
                ),
                (
                    date(2025, 4, 1),
                    Decimal("8987.5989733332"),
                    Decimal("9116.4659033332"),
                    Decimal("-0.0141356235"),
                    Decimal("0.0157404395"),
                    Decimal("0.0157404395"),
                ),
                (
                    date(2025, 5, 1),
                    Decimal("8900.0246133332"),
                    Decimal("8987.5989733332"),
                    Decimal("-0.0097439104"),
                    Decimal("-0.0474414149"),
                    Decimal("0.009369352"),
                ),
            ],
        )

    def test_with_data_and_date_range(self):
        results = self._run_revenue_analytics_growth_rate_query(
            date_range=DateRange(date_from="2025-02-03", date_to="2025-04-04")
        ).results

        self.assertEqual(
            results,
            [
                (date(2025, 2, 1), Decimal("10341.3433233332"), None, None, None, None),
                (
                    date(2025, 3, 1),
                    Decimal("9116.4659033332"),
                    Decimal("10341.3433233332"),
                    Decimal("-0.1184447108"),
                    Decimal("-0.1184447108"),
                    Decimal("-0.1184447108"),
                ),
            ],
        )

    def test_with_data_and_empty_interval(self):
        results = self._run_revenue_analytics_growth_rate_query(
            date_range=DateRange(date_from="2025-01-01", date_to="2025-01-02")
        ).results

        self.assertEqual(results, [])

    def test_with_property_filter(self):
        results = self._run_revenue_analytics_growth_rate_query(
            properties=[
                RevenueAnalyticsPropertyFilter(
                    key="product",
                    operator=PropertyOperator.EXACT,
                    value=["Product C"],  # Equivalent to `prod_c` but we're querying by name
                )
            ]
        ).results

        self.assertEqual(
            results,
            [
                (date(2025, 1, 1), Decimal("11.51665"), None, None, None, None),
                (
                    date(2025, 2, 1),
                    Decimal("37.18802"),
                    Decimal("11.51665"),
                    Decimal("2.2290657439"),
                    Decimal("2.2290657439"),
                    Decimal("2.2290657439"),
                ),
                (
                    date(2025, 3, 1),
                    Decimal("2.73371"),
                    Decimal("37.18802"),
                    Decimal("-0.9264894984"),
                    Decimal("0.6512881228"),
                    Decimal("0.6512881228"),
                ),
                (
                    date(2025, 4, 1),
                    Decimal("0.09564"),
                    Decimal("2.73371"),
                    Decimal("-0.9650145772"),
                    Decimal("0.1125205561"),
                    Decimal("0.1125205561"),
                ),
                (
                    date(2025, 5, 1),
                    Decimal("9.74731"),
                    Decimal("0.09564"),
                    Decimal("100.9166666666"),
                    Decimal("33.0083875303"),
                    Decimal("25.3135570837"),
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
            properties=[
                RevenueAnalyticsPropertyFilter(
                    key="source",
                    operator=PropertyOperator.EXACT,
                    value=["revenue_analytics.purchase"],
                )
            ],
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
            properties=[
                RevenueAnalyticsPropertyFilter(
                    key="source",
                    operator=PropertyOperator.EXACT,
                    value=["revenue_analytics.purchase"],
                )
            ],
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
