from freezegun import freeze_time
from pathlib import Path
from decimal import Decimal
from unittest.mock import ANY

from posthog.models.utils import uuid7
from products.revenue_analytics.backend.hogql_queries.revenue_analytics_arpu_query_runner import (
    RevenueAnalyticsArpuQueryRunner,
)
from posthog.schema import (
    CurrencyCode,
    DateRange,
    PropertyOperator,
    RevenueAnalyticsArpuQuery,
    RevenueAnalyticsArpuQueryResponse,
    RevenueAnalyticsGroupBy,
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
    CUSTOMER_RESOURCE_NAME as STRIPE_CUSTOMER_RESOURCE_NAME,
    SUBSCRIPTION_RESOURCE_NAME as STRIPE_SUBSCRIPTION_RESOURCE_NAME,
)
from posthog.warehouse.test.utils import create_data_warehouse_table_from_csv
from products.revenue_analytics.backend.hogql_queries.test.data.structure import (
    REVENUE_ANALYTICS_CONFIG_SAMPLE_EVENT,
    STRIPE_INVOICE_COLUMNS,
    STRIPE_PRODUCT_COLUMNS,
    STRIPE_CUSTOMER_COLUMNS,
    STRIPE_SUBSCRIPTION_COLUMNS,
)

INVOICES_TEST_BUCKET = "test_storage_bucket-posthog.revenue_analytics.insights_query_runner.stripe_invoices"
PRODUCTS_TEST_BUCKET = "test_storage_bucket-posthog.revenue_analytics.insights_query_runner.stripe_products"
CUSTOMERS_TEST_BUCKET = "test_storage_bucket-posthog.revenue_analytics.insights_query_runner.stripe_customers"
SUBSCRIPTIONS_TEST_BUCKET = "test_storage_bucket-posthog.revenue_analytics.insights_query_runner.stripe_subscriptions"

ALL_MONTHS_LABELS = [
    "Nov 2024",
    "Dec 2024",
    "Jan 2025",
    "Feb 2025",
    "Mar 2025",
    "Apr 2025",
    "May 2025",
    "Jun 2025",
    "Jul 2025",
    "Aug 2025",
    "Sep 2025",
    "Oct 2025",
    "Nov 2025",
    "Dec 2025",
    "Jan 2026",
]
ALL_MONTHS_DAYS = [
    "2024-11-01",
    "2024-12-01",
    "2025-01-01",
    "2025-02-01",
    "2025-03-01",
    "2025-04-01",
    "2025-05-01",
    "2025-06-01",
    "2025-07-01",
    "2025-08-01",
    "2025-09-01",
    "2025-10-01",
    "2025-11-01",
    "2025-12-01",
    "2026-01-01",
]
ALL_MONTHS_FAKEDATETIMES = [ANY] * 15

LAST_6_MONTHS_LABELS = ALL_MONTHS_LABELS[:7].copy()
LAST_6_MONTHS_DAYS = ALL_MONTHS_DAYS[:7].copy()
LAST_6_MONTHS_FAKEDATETIMES = ALL_MONTHS_FAKEDATETIMES[:7].copy()


@snapshot_clickhouse_queries
class TestRevenueAnalyticsArpuQueryRunner(ClickhouseTestMixin, APIBaseTest):
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

        self.subscriptions_csv_path = Path(__file__).parent / "data" / "stripe_subscriptions.csv"
        self.subscriptions_table, _, _, self.subscriptions_csv_df, self.subscriptions_cleanup_filesystem = (
            create_data_warehouse_table_from_csv(
                self.subscriptions_csv_path,
                "stripe_subscription",
                STRIPE_SUBSCRIPTION_COLUMNS,
                SUBSCRIPTIONS_TEST_BUCKET,
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

        self.customers_schema = ExternalDataSchema.objects.create(
            team=self.team,
            name=STRIPE_CUSTOMER_RESOURCE_NAME,
            source=self.source,
            table=self.customers_table,
            should_sync=True,
            last_synced_at="2024-01-01",
        )

        self.subscriptions_schema = ExternalDataSchema.objects.create(
            team=self.team,
            name=STRIPE_SUBSCRIPTION_RESOURCE_NAME,
            source=self.source,
            table=self.subscriptions_table,
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
        self.customers_cleanup_filesystem()
        self.subscriptions_cleanup_filesystem()
        super().tearDown()

    def _run_revenue_analytics_arpu_query(
        self,
        date_range: DateRange | None = None,
        interval: IntervalType | None = None,
        group_by: list[RevenueAnalyticsGroupBy] | None = None,
        properties: list[RevenueAnalyticsPropertyFilter] | None = None,
    ):
        if date_range is None:
            date_range: DateRange = DateRange(date_from="-6m")
        if interval is None:
            interval = IntervalType.MONTH
        if group_by is None:
            group_by = []
        if properties is None:
            properties = []

        with freeze_time(self.QUERY_TIMESTAMP):
            query = RevenueAnalyticsArpuQuery(
                dateRange=date_range,
                interval=interval,
                groupBy=group_by,
                properties=properties,
                modifiers=HogQLQueryModifiers(formatCsvAllowDoubleQuotes=True),
            )

            runner = RevenueAnalyticsArpuQueryRunner(
                team=self.team,
                query=query,
            )
            response = runner.calculate()

            RevenueAnalyticsArpuQueryResponse.model_validate(response)
            return response

    def test_no_crash_when_no_data(self):
        self.invoices_table.delete()
        self.products_table.delete()
        self.customers_table.delete()
        self.subscriptions_table.delete()
        results = self._run_revenue_analytics_arpu_query().results

        self.assertEqual(results, [])

    def test_no_crash_when_no_source_is_selected(self):
        results = self._run_revenue_analytics_arpu_query(
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
        # Use huge date range to collect all data
        results = self._run_revenue_analytics_arpu_query(
            date_range=DateRange(date_from="2024-11-01", date_to="2026-01-01")
        ).results

        self.assertEqual(
            results,
            [
                {
                    "label": "stripe.posthog_test",
                    "days": ALL_MONTHS_DAYS,
                    "labels": ALL_MONTHS_LABELS,
                    "data": [
                        0,
                        0,
                        Decimal("15450.0814433328"),
                        Decimal("9270.0488659996"),
                        Decimal("15450.0814433328"),
                        Decimal("9270.0488659996"),
                        Decimal("15450.0814433328"),
                        Decimal("23175.1221649992"),
                        Decimal("23175.1221649992"),
                        Decimal("23175.1221649992"),
                        Decimal("23175.1221649992"),
                        Decimal("23175.1221649992"),
                        Decimal("23175.1221649992"),
                        Decimal("23175.1221649992"),
                        0,
                    ],
                    "action": {
                        "days": ALL_MONTHS_FAKEDATETIMES,
                        "id": "stripe.posthog_test",
                        "name": "stripe.posthog_test",
                    },
                }
            ],
        )

    def test_with_data_and_date_range(self):
        results = self._run_revenue_analytics_arpu_query(
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
                    "data": [Decimal("5689.0816399999"), Decimal("9481.8027333332"), Decimal("5689.0816399999"), 0],
                    "action": {"days": [ANY] * 4, "id": "stripe.posthog_test", "name": "stripe.posthog_test"},
                }
            ],
        )

    def test_with_empty_date_range(self):
        results = self._run_revenue_analytics_arpu_query(
            date_range=DateRange(date_from="2024-12-01", date_to="2024-12-31")
        ).results

        self.assertEqual(results, [])

    def test_with_data_and_product_grouping(self):
        results = self._run_revenue_analytics_arpu_query(group_by=[RevenueAnalyticsGroupBy.PRODUCT]).results

        self.assertEqual(len(results), 6)

        self.assertEqual(
            [result["label"] for result in results],
            [
                "stripe.posthog_test - Product A",
                "stripe.posthog_test - Product B",
                "stripe.posthog_test - Product C",
                "stripe.posthog_test - Product D",
                "stripe.posthog_test - Product E",
                "stripe.posthog_test - Product F",
            ],
        )
        self.assertEqual(
            [result["data"] for result in results],
            [
                [
                    0,
                    0,
                    Decimal("626.4486416665"),
                    Decimal("313.2243208332"),
                    Decimal("626.4486416665"),
                    Decimal("313.2243208332"),
                    Decimal("626.4486416665"),
                ],
                [
                    0,
                    0,
                    Decimal("1825.0542849995"),
                    Decimal("912.5271424997"),
                    Decimal("1825.0542849995"),
                    Decimal("912.5271424997"),
                    Decimal("1825.0542849995"),
                ],
                [
                    0,
                    0,
                    Decimal("61.28133"),
                    Decimal("61.28133"),
                    Decimal("61.28133"),
                    Decimal("61.28133"),
                    Decimal("61.28133"),
                ],
                [
                    0,
                    0,
                    Decimal("1934.51825"),
                    Decimal("1934.51825"),
                    Decimal("1934.51825"),
                    Decimal("1934.51825"),
                    Decimal("1934.51825"),
                ],
                [
                    0,
                    0,
                    Decimal("1.71355"),
                    Decimal("1.71355"),
                    Decimal("1.71355"),
                    Decimal("1.71355"),
                    Decimal("1.71355"),
                ],
                [
                    0,
                    0,
                    Decimal("41661.7404"),
                    Decimal("41661.7404"),
                    Decimal("41661.7404"),
                    Decimal("41661.7404"),
                    Decimal("41661.7404"),
                ],
            ],
        )

    def test_with_data_and_double_grouping(self):
        results = self._run_revenue_analytics_arpu_query(
            group_by=[RevenueAnalyticsGroupBy.COHORT, RevenueAnalyticsGroupBy.PRODUCT]
        ).results

        # 12 comes from the 6 products and 2 cohorts
        self.assertEqual(len(results), 12)

        self.assertEqual(
            [result["label"] for result in results],
            [
                "stripe.posthog_test - 2025-01 - Product A",
                "stripe.posthog_test - 2025-01 - Product B",
                "stripe.posthog_test - 2025-01 - Product C",
                "stripe.posthog_test - 2025-01 - Product D",
                "stripe.posthog_test - 2025-01 - Product E",
                "stripe.posthog_test - 2025-01 - Product F",
                "stripe.posthog_test - 2025-02 - Product A",
                "stripe.posthog_test - 2025-02 - Product B",
                "stripe.posthog_test - 2025-02 - Product C",
                "stripe.posthog_test - 2025-02 - Product D",
                "stripe.posthog_test - 2025-02 - Product E",
                "stripe.posthog_test - 2025-02 - Product F",
            ],
        )

        self.assertEqual(
            [result["data"] for result in results],
            [
                [
                    0,
                    0,
                    Decimal("372.3251916665"),
                    Decimal("372.3251916665"),
                    Decimal("372.3251916665"),
                    Decimal("372.3251916665"),
                    Decimal("372.3251916665"),
                ],
                [
                    0,
                    0,
                    Decimal("295.1330849995"),
                    Decimal("295.1330849995"),
                    Decimal("295.1330849995"),
                    Decimal("295.1330849995"),
                    Decimal("295.1330849995"),
                ],
                [0, 0, Decimal("23.99767"), 0, Decimal("23.99767"), 0, Decimal("23.99767")],
                [0, 0, Decimal("1160.71095"), 0, Decimal("1160.71095"), 0, Decimal("1160.71095")],
                [0, 0, Decimal("1.02813"), 0, Decimal("1.02813"), 0, Decimal("1.02813")],
                [0, 0, Decimal("24997.04424"), 0, Decimal("24997.04424"), 0, Decimal("24997.04424")],
                [0, 0, 0, Decimal("254.12345"), 0, Decimal("254.12345"), 0],
                [0, 0, 0, Decimal("1529.9212"), 0, Decimal("1529.9212"), 0],
                [0, 0, 0, Decimal("37.28366"), 0, Decimal("37.28366"), 0],
                [0, 0, 0, Decimal("773.8073"), 0, Decimal("773.8073"), 0],
                [0, 0, 0, Decimal("0.68542"), 0, Decimal("0.68542"), 0],
                [0, 0, 0, Decimal("16664.69616"), 0, Decimal("16664.69616"), 0],
            ],
        )

    def test_with_product_filter(self):
        expected_data = [
            [
                0,
                0,
                Decimal("61.28133"),
                Decimal("61.28133"),
                Decimal("61.28133"),
                Decimal("61.28133"),
                Decimal("61.28133"),
            ]
        ]

        results = self._run_revenue_analytics_arpu_query(
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
        results = self._run_revenue_analytics_arpu_query(
            group_by=[RevenueAnalyticsGroupBy.PRODUCT],
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

    def test_with_country_filter(self):
        results = self._run_revenue_analytics_arpu_query(
            properties=[
                RevenueAnalyticsPropertyFilter(
                    key="country",
                    operator=PropertyOperator.EXACT,
                    value=["US"],
                )
            ]
        ).results

        self.assertEqual(len(results), 1)
        self.assertEqual([result["label"] for result in results], ["stripe.posthog_test"])
        self.assertEqual(
            [result["data"] for result in results],
            [
                [
                    0,
                    0,
                    Decimal("333.729138333"),
                    Decimal("333.729138333"),
                    Decimal("333.729138333"),
                    Decimal("333.729138333"),
                    Decimal("333.729138333"),
                ]
            ],
        )

    def test_with_events_data(self):
        s1 = str(uuid7("2024-12-25"))
        s2 = str(uuid7("2025-01-03"))
        self._create_purchase_events(
            [
                ("p1", [("2024-12-25", s1, 42, "USD")]),
                ("p2", [("2025-01-03", s2, 43, "BRL")]),
            ]
        )

        results = self._run_revenue_analytics_arpu_query(
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
                {
                    "label": "revenue_analytics.purchase",
                    "days": LAST_6_MONTHS_DAYS,
                    "labels": LAST_6_MONTHS_LABELS,
                    "data": [0, Decimal("39.0369321819"), Decimal("39.0369321819"), 0, 0, 0, 0],
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

        results = self._run_revenue_analytics_arpu_query(
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
                {
                    "label": "revenue_analytics.purchase",
                    "days": LAST_6_MONTHS_DAYS,
                    "labels": LAST_6_MONTHS_LABELS,
                    "data": [0, Decimal("0.3903693217"), Decimal("0.3903693217"), 0, 0, 0, 0],
                    "action": {
                        "days": LAST_6_MONTHS_FAKEDATETIMES,
                        "id": "revenue_analytics.purchase",
                        "name": "revenue_analytics.purchase",
                    },
                }
            ],
        )
