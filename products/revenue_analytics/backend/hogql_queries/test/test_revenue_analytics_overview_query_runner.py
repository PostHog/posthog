from decimal import Decimal
from pathlib import Path

from freezegun import freeze_time
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    snapshot_clickhouse_queries,
)

from posthog.schema import (
    CurrencyCode,
    DateRange,
    HogQLQueryModifiers,
    PropertyOperator,
    RevenueAnalyticsOverviewItem,
    RevenueAnalyticsOverviewItemKey,
    RevenueAnalyticsOverviewQuery,
    RevenueAnalyticsOverviewQueryResponse,
    RevenueAnalyticsPropertyFilter,
)

from posthog.models.utils import uuid7
from posthog.temporal.data_imports.sources.stripe.constants import (
    CHARGE_RESOURCE_NAME as STRIPE_CHARGE_RESOURCE_NAME,
    CUSTOMER_RESOURCE_NAME as STRIPE_CUSTOMER_RESOURCE_NAME,
    INVOICE_RESOURCE_NAME as STRIPE_INVOICE_RESOURCE_NAME,
    PRODUCT_RESOURCE_NAME as STRIPE_PRODUCT_RESOURCE_NAME,
)

from products.data_warehouse.backend.models import ExternalDataSchema
from products.data_warehouse.backend.test.utils import create_data_warehouse_table_from_csv
from products.revenue_analytics.backend.hogql_queries.revenue_analytics_overview_query_runner import (
    RevenueAnalyticsOverviewQueryRunner,
)
from products.revenue_analytics.backend.hogql_queries.test.data.structure import (
    REVENUE_ANALYTICS_CONFIG_SAMPLE_EVENT,
    STRIPE_CHARGE_COLUMNS,
    STRIPE_CUSTOMER_COLUMNS,
    STRIPE_INVOICE_COLUMNS,
    STRIPE_PRODUCT_COLUMNS,
)

INVOICE_TEST_BUCKET = "test_storage_bucket-posthog.revenue_analytics.overview_query_runner.stripe_invoices"
PRODUCT_TEST_BUCKET = "test_storage_bucket-posthog.revenue_analytics.overview_query_runner.stripe_products"
CHARGES_TEST_BUCKET = "test_storage_bucket-posthog.revenue_analytics.overview_query_runner.stripe_charges"
CUSTOMERS_TEST_BUCKET = "test_storage_bucket-posthog.revenue_analytics.overview_query_runner.stripe_customers"


@snapshot_clickhouse_queries
class TestRevenueAnalyticsOverviewQueryRunner(ClickhouseTestMixin, APIBaseTest):
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

        self.charges_csv_path = Path(__file__).parent / "data" / "stripe_charges.csv"
        self.charges_table, _, _, self.charges_csv_df, self.charges_cleanup_filesystem = (
            create_data_warehouse_table_from_csv(
                self.charges_csv_path,
                "stripe_charge",
                STRIPE_CHARGE_COLUMNS,
                CHARGES_TEST_BUCKET,
                self.team,
                source=self.source,
                credential=self.credential,
            )
        )

        self.customers_csv_path = Path(__file__).parent / "data" / "stripe_customers.csv"
        self.customers_table, _, _, self.customers_csv_df, self.customers_cleanup_filesystem = (
            create_data_warehouse_table_from_csv(
                self.customers_csv_path,
                "stripe_customer",
                STRIPE_CUSTOMER_COLUMNS,
                CUSTOMERS_TEST_BUCKET,
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

        self.team.base_currency = CurrencyCode.GBP.value
        self.team.revenue_analytics_config.events = [REVENUE_ANALYTICS_CONFIG_SAMPLE_EVENT]
        self.team.revenue_analytics_config.save()
        self.team.save()

    def tearDown(self):
        self.invoices_cleanup_filesystem()
        self.products_cleanup_filesystem()
        self.charges_cleanup_filesystem()
        self.customers_cleanup_filesystem()
        super().tearDown()

    def _run_revenue_analytics_overview_query(
        self,
        date_range: DateRange | None = None,
        properties: list[RevenueAnalyticsPropertyFilter] | None = None,
    ):
        if date_range is None:
            date_range = DateRange(date_from="-30d")
        if properties is None:
            properties = []

        with freeze_time(self.QUERY_TIMESTAMP):
            query = RevenueAnalyticsOverviewQuery(
                dateRange=date_range,
                properties=properties,
                modifiers=HogQLQueryModifiers(formatCsvAllowDoubleQuotes=True),
            )
            runner = RevenueAnalyticsOverviewQueryRunner(
                team=self.team,
                query=query,
            )

            response = runner.calculate()
            RevenueAnalyticsOverviewQueryResponse.model_validate(response)

            return response

    def test_no_crash_when_no_data(self):
        self.invoices_table.delete()
        self.products_table.delete()
        self.charges_table.delete()
        self.customers_table.delete()
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
                    key=RevenueAnalyticsOverviewItemKey.REVENUE, value=Decimal("1621.0866070701")
                ),
                RevenueAnalyticsOverviewItem(key=RevenueAnalyticsOverviewItemKey.PAYING_CUSTOMER_COUNT, value=3),
                RevenueAnalyticsOverviewItem(
                    key=RevenueAnalyticsOverviewItemKey.AVG_REVENUE_PER_CUSTOMER, value=Decimal("540.3622023567")
                ),
            ],
        )

    def test_with_data_and_empty_interval(self):
        results = self._run_revenue_analytics_overview_query(
            date_range=DateRange(date_from="2025-01-01", date_to="2025-01-02")
        ).results

        self.assertEqual(
            results,
            [
                RevenueAnalyticsOverviewItem(key=RevenueAnalyticsOverviewItemKey.REVENUE, value=0),
                RevenueAnalyticsOverviewItem(key=RevenueAnalyticsOverviewItemKey.PAYING_CUSTOMER_COUNT, value=0),
                RevenueAnalyticsOverviewItem(key=RevenueAnalyticsOverviewItemKey.AVG_REVENUE_PER_CUSTOMER, value=0),
            ],
        )

    def test_with_full_discount(self):
        # Filtering by that product only because it includes the 0-charge in stripe_invoices.csv
        results = self._run_revenue_analytics_overview_query(
            properties=[
                RevenueAnalyticsPropertyFilter(
                    key="revenue_analytics_product.name",
                    operator=PropertyOperator.EXACT,
                    value=["Product C"],  # Equivalent to `prod_c` but we're querying by name
                )
            ]
        ).results

        self.assertEqual(
            results,
            [
                RevenueAnalyticsOverviewItem(key=RevenueAnalyticsOverviewItemKey.REVENUE, value=Decimal("0")),
                # There's a user for this one, but it's not paying anything, so consider it as non-paying
                RevenueAnalyticsOverviewItem(key=RevenueAnalyticsOverviewItemKey.PAYING_CUSTOMER_COUNT, value=0),
                RevenueAnalyticsOverviewItem(
                    key=RevenueAnalyticsOverviewItemKey.AVG_REVENUE_PER_CUSTOMER, value=Decimal("0")
                ),
            ],
        )

    def test_with_property_filter(self):
        # Product join, usually simple
        results = self._run_revenue_analytics_overview_query(
            properties=[
                RevenueAnalyticsPropertyFilter(
                    key="revenue_analytics_product.name",
                    operator=PropertyOperator.EXACT,
                    value=["Product D"],  # Equivalent to `prod_d` but we're querying by name
                )
            ]
        ).results

        self.assertEqual(
            results,
            [
                RevenueAnalyticsOverviewItem(key=RevenueAnalyticsOverviewItemKey.REVENUE, value=Decimal("386.90365")),
                RevenueAnalyticsOverviewItem(key=RevenueAnalyticsOverviewItemKey.PAYING_CUSTOMER_COUNT, value=1),
                RevenueAnalyticsOverviewItem(
                    key=RevenueAnalyticsOverviewItemKey.AVG_REVENUE_PER_CUSTOMER, value=Decimal("386.90365")
                ),
            ],
        )

        # Customer join, more complicated because it shares fields such as `timestamp`
        results = self._run_revenue_analytics_overview_query(
            properties=[
                RevenueAnalyticsPropertyFilter(
                    key="revenue_analytics_customer.country",
                    operator=PropertyOperator.EXACT,
                    value=["US"],
                )
            ]
        ).results

        self.assertEqual(
            results,
            [
                RevenueAnalyticsOverviewItem(
                    key=RevenueAnalyticsOverviewItemKey.REVENUE, value=Decimal("74.4921670701")
                ),
                RevenueAnalyticsOverviewItem(key=RevenueAnalyticsOverviewItemKey.PAYING_CUSTOMER_COUNT, value=2),
                RevenueAnalyticsOverviewItem(
                    key=RevenueAnalyticsOverviewItemKey.AVG_REVENUE_PER_CUSTOMER, value=Decimal("37.246083535")
                ),
            ],
        )

    def test_with_property_filter_multiple_values(self):
        results = self._run_revenue_analytics_overview_query(
            properties=[
                RevenueAnalyticsPropertyFilter(
                    key="revenue_analytics_product.name",
                    operator=PropertyOperator.EXACT,
                    value=["Product A", "Product D"],
                )
            ]
        ).results

        self.assertEqual(
            results,
            [
                RevenueAnalyticsOverviewItem(
                    key=RevenueAnalyticsOverviewItemKey.REVENUE, value=Decimal("409.8667947238")
                ),
                RevenueAnalyticsOverviewItem(key=RevenueAnalyticsOverviewItemKey.PAYING_CUSTOMER_COUNT, value=2),
                RevenueAnalyticsOverviewItem(
                    key=RevenueAnalyticsOverviewItemKey.AVG_REVENUE_PER_CUSTOMER, value=Decimal("204.9333973619")
                ),
            ],
        )

    def test_with_events_data(self):
        s1 = str(uuid7("2023-12-02"))
        s2 = str(uuid7("2024-01-03"))
        s3 = str(uuid7("2024-02-04"))
        self._create_purchase_events(
            [
                ("p1", [("2023-12-02", s1, 42, "USD"), ("2023-12-02", s1, 35456, "ARS")]),
                ("p2", [("2024-01-01", s2, 43, "BRL"), ("2024-01-02", s3, 87, "BRL")]),  # 2 events, 1 customer
            ]
        )

        # Ignore events in ARS because they're considered tests
        self.team.test_account_filters = [
            {
                "key": "currency",
                "operator": "not_icontains",
                "value": "ARS",
                "type": "event",
            }
        ]
        self.team.save()

        # Make sure Revenue Analytics is configured to filter test accounts out
        self.team.revenue_analytics_config.filter_test_accounts = True
        self.team.revenue_analytics_config.save()

        results = self._run_revenue_analytics_overview_query(
            date_range=DateRange(date_from="2023-11-01", date_to="2024-01-31"),
            properties=[
                RevenueAnalyticsPropertyFilter(
                    key="source_label",
                    operator=PropertyOperator.EXACT,
                    value=["revenue_analytics.events.purchase"],
                )
            ],
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

    def test_with_events_data_and_currency_aware_divider(self):
        self.team.revenue_analytics_config.events = [
            REVENUE_ANALYTICS_CONFIG_SAMPLE_EVENT.model_copy(update={"currencyAwareDecimal": True})
        ]

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
            properties=[
                RevenueAnalyticsPropertyFilter(
                    key="source_label",
                    operator=PropertyOperator.EXACT,
                    value=["revenue_analytics.events.purchase"],
                )
            ],
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

    def test_convertToProjectTimezone_date_range_sql_snapshot(self):
        self.team.timezone = "America/Los_Angeles"
        self.team.save()

        query = RevenueAnalyticsOverviewQuery(
            dateRange=DateRange(date_from="2023-11-01", date_to="2023-11-30"),
            properties=[],
            modifiers=HogQLQueryModifiers(formatCsvAllowDoubleQuotes=True),
        )

        # Test with convertToProjectTimezone=True (should use team timezone for date range)
        modifiers_with_tz = HogQLQueryModifiers(formatCsvAllowDoubleQuotes=True, convertToProjectTimezone=True)
        runner_with_tz = RevenueAnalyticsOverviewQueryRunner(team=self.team, query=query, modifiers=modifiers_with_tz)

        # Test with convertToProjectTimezone=False (should use UTC for date range)
        modifiers_utc = HogQLQueryModifiers(formatCsvAllowDoubleQuotes=True, convertToProjectTimezone=False)
        runner_utc = RevenueAnalyticsOverviewQueryRunner(team=self.team, query=query, modifiers=modifiers_utc)

        # Generate SQL to capture in snapshots - the date boundaries should be different
        runner_with_tz.calculate()
        runner_utc.calculate()

        # Verify timezone info is used correctly in date range calculation
        tz_date_range = runner_with_tz.query_date_range
        utc_date_range = runner_utc.query_date_range

        # Team timezone should be used when convertToProjectTimezone=True
        assert tz_date_range.date_from().tzinfo.key == "America/Los_Angeles"

        # UTC should be used when convertToProjectTimezone=False
        assert utc_date_range.date_from().tzinfo.key == "UTC"
