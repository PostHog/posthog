from decimal import Decimal
from pathlib import Path
from unittest.mock import ANY

from freezegun import freeze_time

from posthog.models.utils import uuid7
from posthog.schema import (
    CurrencyCode,
    DateRange,
    HogQLQueryModifiers,
    IntervalType,
    PropertyOperator,
    RevenueAnalyticsGroupBy,
    RevenueAnalyticsPropertyFilter,
    RevenueAnalyticsRevenueQuery,
    RevenueAnalyticsRevenueQueryResponse,
    RevenueAnalyticsRevenueQueryResult,
)
from posthog.temporal.data_imports.sources.stripe.constants import (
    CHARGE_RESOURCE_NAME as STRIPE_CHARGE_RESOURCE_NAME,
    CUSTOMER_RESOURCE_NAME as STRIPE_CUSTOMER_RESOURCE_NAME,
    INVOICE_RESOURCE_NAME as STRIPE_INVOICE_RESOURCE_NAME,
    PRODUCT_RESOURCE_NAME as STRIPE_PRODUCT_RESOURCE_NAME,
    SUBSCRIPTION_RESOURCE_NAME as STRIPE_SUBSCRIPTION_RESOURCE_NAME,
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
from products.revenue_analytics.backend.hogql_queries.revenue_analytics_revenue_query_runner import (
    RevenueAnalyticsRevenueQueryRunner,
)
from products.revenue_analytics.backend.hogql_queries.test.data.structure import (
    REVENUE_ANALYTICS_CONFIG_SAMPLE_EVENT,
    STRIPE_CHARGE_COLUMNS,
    STRIPE_CUSTOMER_COLUMNS,
    STRIPE_INVOICE_COLUMNS,
    STRIPE_PRODUCT_COLUMNS,
    STRIPE_SUBSCRIPTION_COLUMNS,
)

CHARGES_TEST_BUCKET = "test_storage_bucket-posthog.revenue_analytics.insights_query_runner.stripe_charges"
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
    "Feb 2026",
    "Mar 2026",
    "Apr 2026",
    "May 2026",
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
    "2026-02-01",
    "2026-03-01",
    "2026-04-01",
    "2026-05-01",
]
ALL_MONTHS_FAKEDATETIMES = [ANY] * 19

LAST_6_MONTHS_LABELS = ALL_MONTHS_LABELS[:7].copy()
LAST_6_MONTHS_DAYS = ALL_MONTHS_DAYS[:7].copy()
LAST_6_MONTHS_FAKEDATETIMES = ALL_MONTHS_FAKEDATETIMES[:7].copy()


@snapshot_clickhouse_queries
class TestRevenueAnalyticsRevenueQueryRunner(ClickhouseTestMixin, APIBaseTest):
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
            for timestamp, session_id, revenue, currency, product, coupon, subscription_id in timestamps:
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
                            "product": product,
                            "coupon": coupon,
                            "subscription": subscription_id,
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

        self.charges_schema = ExternalDataSchema.objects.create(
            team=self.team,
            name=STRIPE_CHARGE_RESOURCE_NAME,
            source=self.source,
            table=self.charges_table,
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
        self.charges_cleanup_filesystem()
        self.subscriptions_cleanup_filesystem()
        super().tearDown()

    def _build_query(
        self,
        date_range: DateRange | None = None,
        interval: IntervalType | None = None,
        group_by: list[RevenueAnalyticsGroupBy] | None = None,
        properties: list[RevenueAnalyticsPropertyFilter] | None = None,
    ):
        if date_range is None:
            date_range = DateRange(date_from="-6m")
        if interval is None:
            interval = IntervalType.MONTH
        if group_by is None:
            group_by = []
        if properties is None:
            properties = []

        return RevenueAnalyticsRevenueQuery(
            dateRange=date_range,
            interval=interval,
            groupBy=group_by,
            properties=properties,
            modifiers=HogQLQueryModifiers(formatCsvAllowDoubleQuotes=True),
        )

    def _run_revenue_analytics_revenue_query(
        self,
        date_range: DateRange | None = None,
        interval: IntervalType | None = None,
        group_by: list[RevenueAnalyticsGroupBy] | None = None,
        properties: list[RevenueAnalyticsPropertyFilter] | None = None,
    ):
        with freeze_time(self.QUERY_TIMESTAMP):
            query = self._build_query(date_range, interval, group_by, properties)
            runner = RevenueAnalyticsRevenueQueryRunner(
                team=self.team,
                query=query,
            )

            response = runner.calculate()

            RevenueAnalyticsRevenueQueryResponse.model_validate(response)
            return response

    def test_no_crash_when_no_data(self):
        self.invoices_table.delete()
        self.products_table.delete()
        self.customers_table.delete()
        self.charges_table.delete()
        self.subscriptions_table.delete()
        results = self._run_revenue_analytics_revenue_query().results

        self.assertEqual(results, RevenueAnalyticsRevenueQueryResult(gross=[], mrr=[]))

    def test_no_crash_when_no_source_is_selected(self):
        results = self._run_revenue_analytics_revenue_query(
            properties=[
                RevenueAnalyticsPropertyFilter(
                    key="source",
                    operator=PropertyOperator.EXACT,
                    value=["non-existent-source"],
                )
            ],
        ).results

        self.assertEqual(results, RevenueAnalyticsRevenueQueryResult(gross=[], mrr=[]))

    def test_with_data(self):
        # Use huge date range to collect all data
        results = self._run_revenue_analytics_revenue_query(
            date_range=DateRange(date_from="2024-11-01", date_to="2026-05-01")
        ).results

        self.assertEqual(len(results.gross), 1)
        self.assertEqual(len(results.mrr), 1)

        gross = results.gross[0]
        mrr = results.mrr[0]

        self.assertEqual(
            gross,
            {
                "label": "stripe.posthog_test",
                "days": ALL_MONTHS_DAYS,
                "labels": ALL_MONTHS_LABELS,
                "data": [
                    0,
                    0,
                    Decimal("4399.7680983332"),
                    Decimal("9969.4591383332"),
                    Decimal("9492.7415583332"),
                    Decimal("13638.7017241465"),
                    Decimal("8900.0246133332"),
                    Decimal("34.2125533332"),
                    Decimal("34.2125533332"),
                    Decimal("34.2125533332"),
                    Decimal("34.2125533332"),
                    Decimal("34.2125533332"),
                    Decimal("34.2125533332"),
                    Decimal("34.2125533332"),
                    0,
                    0,
                    0,
                    0,
                    0,
                ],
                "action": {
                    "days": ALL_MONTHS_FAKEDATETIMES,
                    "id": "stripe.posthog_test",
                    "name": "stripe.posthog_test",
                },
            },
        )

        self.assertEqual(
            mrr.total,
            {
                "label": "stripe.posthog_test",
                "days": ALL_MONTHS_DAYS,
                "labels": ALL_MONTHS_LABELS,
                "data": [
                    0,
                    0,
                    0,
                    Decimal("4390.0632949999"),
                    Decimal("9127.5030249999"),
                    Decimal("9410.7488549999"),
                    Decimal("13268.2208849999"),
                    Decimal("8889.3394999999"),
                    Decimal("24.5077499999"),
                    Decimal("24.5077499999"),
                    Decimal("24.5077499999"),
                    Decimal("24.5077499999"),
                    Decimal("24.5077499999"),
                    Decimal("24.5077499999"),
                    Decimal("24.5077499999"),
                    0,
                    0,
                    0,
                    0,
                ],
                "action": {
                    "days": ALL_MONTHS_FAKEDATETIMES,
                    "id": "stripe.posthog_test",
                    "name": "stripe.posthog_test",
                },
            },
        )

        self.assertEqual(
            mrr.new,
            {
                "label": "stripe.posthog_test",
                "days": ALL_MONTHS_DAYS,
                "labels": ALL_MONTHS_LABELS,
                "data": [
                    0,
                    0,
                    0,
                    Decimal("4390.0632949999"),
                    Decimal("4737.4397300000"),
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                ],
                "action": {
                    "days": ALL_MONTHS_FAKEDATETIMES,
                    "id": "stripe.posthog_test",
                    "name": "stripe.posthog_test",
                },
            },
        )

        self.assertEqual(
            mrr.expansion,
            {
                "label": "stripe.posthog_test",
                "days": ALL_MONTHS_DAYS,
                "labels": ALL_MONTHS_LABELS,
                "data": [
                    0,
                    0,
                    0,
                    0,
                    0,
                    Decimal("287.6373"),
                    Decimal("4341.29885"),
                    Decimal("4503.667675"),
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                ],
                "action": {
                    "days": ALL_MONTHS_FAKEDATETIMES,
                    "id": "stripe.posthog_test",
                    "name": "stripe.posthog_test",
                },
            },
        )

        self.assertEqual(
            mrr.contraction,
            {
                "label": "stripe.posthog_test",
                "days": ALL_MONTHS_DAYS,
                "labels": ALL_MONTHS_LABELS,
                "data": [
                    0,
                    0,
                    0,
                    0,
                    0,
                    Decimal("4.39147"),
                    Decimal("483.82682"),
                    0,
                    Decimal("135.49000"),
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                ],
                "action": {
                    "days": ALL_MONTHS_FAKEDATETIMES,
                    "id": "stripe.posthog_test",
                    "name": "stripe.posthog_test",
                },
            },
        )

        self.assertEqual(
            mrr.churn,
            {
                "label": "stripe.posthog_test",
                "days": ALL_MONTHS_DAYS,
                "labels": ALL_MONTHS_LABELS,
                "data": [
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    Decimal("8882.54906"),
                    Decimal("8729.34175"),
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    Decimal("24.5077499999"),
                    0,
                    0,
                    0,
                ],
                "action": {
                    "days": ALL_MONTHS_FAKEDATETIMES,
                    "id": "stripe.posthog_test",
                    "name": "stripe.posthog_test",
                },
            },
        )

        # Iterate over the values and check that the new/expansion/contraction/churn values
        # properly add up to the change between the previous period and the current period
        previous = Decimal(0)
        for i in range(len(mrr.total["data"])):
            change_to_previous = mrr.total["data"][i] - previous
            change = mrr.new["data"][i] + mrr.expansion["data"][i] - mrr.contraction["data"][i] - mrr.churn["data"][i]
            self.assertEqual(change_to_previous, change, f"MRR change at index {i} is incorrect")
            previous = mrr.total["data"][i]

    def test_with_data_and_date_range(self):
        results = self._run_revenue_analytics_revenue_query(
            date_range=DateRange(date_from="2025-02-01", date_to="2025-05-01")
        ).results

        self.assertEqual(len(results.gross), 1)
        self.assertEqual(len(results.mrr), 1)

        gross = results.gross[0]
        mrr = results.mrr[0]

        # Restricted to the date range
        self.assertEqual(
            gross,
            {
                "label": "stripe.posthog_test",
                "days": ["2025-02-01", "2025-03-01", "2025-04-01", "2025-05-01"],
                "labels": ["Feb 2025", "Mar 2025", "Apr 2025", "May 2025"],
                "data": [
                    Decimal("9969.4591383332"),
                    Decimal("9492.7415583332"),
                    Decimal("13638.7017241465"),
                    Decimal("0"),
                ],
                "action": {"days": [ANY] * 4, "id": "stripe.posthog_test", "name": "stripe.posthog_test"},
            },
        )

        self.assertEqual(
            mrr.total,
            {
                "label": "stripe.posthog_test",
                "days": ["2025-02-01", "2025-03-01", "2025-04-01", "2025-05-01"],
                "labels": ["Feb 2025", "Mar 2025", "Apr 2025", "May 2025"],
                # This is an important test, see how MRR is included for the first month, because there's previous data from January 30 days prior to February 1st
                "data": [
                    Decimal("4390.0632949999"),
                    Decimal("9127.5030249999"),
                    Decimal("9410.7488549999"),
                    Decimal("13268.2208849999"),
                ],
                "action": {"days": [ANY] * 4, "id": "stripe.posthog_test", "name": "stripe.posthog_test"},
            },
        )

    def test_with_empty_date_range(self):
        results = self._run_revenue_analytics_revenue_query(
            date_range=DateRange(date_from="2024-12-01", date_to="2024-12-31")
        ).results

        self.assertEqual(results, RevenueAnalyticsRevenueQueryResult(gross=[], mrr=[]))

    def test_with_data_and_product_grouping(self):
        results = self._run_revenue_analytics_revenue_query(group_by=[RevenueAnalyticsGroupBy.PRODUCT]).results

        self.assertEqual(len(results.gross), 7)
        self.assertEqual(len(results.mrr), 7)

        expected_products = [
            "stripe.posthog_test - Product F",
            "stripe.posthog_test - Product D",
            "stripe.posthog_test - Product B",
            "stripe.posthog_test - Product A",
            "stripe.posthog_test - Product C",
            "stripe.posthog_test - Product E",
            "stripe.posthog_test - <none>",
        ]
        self.assertEqual([result["label"] for result in results.gross], expected_products)
        self.assertEqual([result.total["label"] for result in results.mrr], expected_products)

        self.assertEqual(
            [result["data"] for result in results.gross],
            [
                [
                    0,
                    0,
                    Decimal("4166.17404"),
                    Decimal("8332.34808"),
                    Decimal("8332.34808"),
                    Decimal("12498.52212"),
                    Decimal("8332.34808"),
                ],
                [
                    0,
                    0,
                    Decimal("193.451825"),
                    Decimal("386.90365"),
                    Decimal("386.90365"),
                    Decimal("580.355475"),
                    Decimal("386.90365"),
                ],
                [
                    0,
                    0,
                    Decimal("26.0100949999"),
                    Decimal("1131.8316549999"),
                    Decimal("444.1561449999"),
                    Decimal("176.5394849999"),
                    Decimal("46.5169049999"),
                ],
                [
                    0,
                    0,
                    Decimal("8.2024583333"),
                    Decimal("93.6807083333"),
                    Decimal("309.0301083333"),
                    Decimal("91.3694083333"),
                    Decimal("124.1659583333"),
                ],
                [
                    0,
                    0,
                    Decimal("5.758325"),
                    Decimal("24.352335"),
                    Decimal("19.960865"),
                    Decimal("1.462495"),
                    Decimal("9.74731"),
                ],
                [
                    0,
                    0,
                    Decimal("0.171355"),
                    Decimal("0.34271"),
                    Decimal("0.34271"),
                    Decimal("0.514065"),
                    Decimal("0.34271"),
                ],
                [0, 0, 0, 0, 0, Decimal("289.9386758133"), 0],
            ],
        )

        self.assertEqual(
            [result.total["data"] for result in results.mrr],
            [
                [0, 0, 0, Decimal("4166.17404"), Decimal("8332.34808"), Decimal("8332.34808"), Decimal("12498.52212")],
                [0, 0, 0, Decimal("193.451825"), Decimal("386.903650"), Decimal("386.903650"), Decimal("580.355475")],
                [
                    0,
                    0,
                    0,
                    Decimal("16.3052916666"),
                    Decimal("289.8755416666"),
                    Decimal("362.1634416666"),
                    Decimal("95.9973216666"),
                ],
                [
                    0,
                    0,
                    0,
                    Decimal("8.2024583333"),
                    Decimal("93.6807083333"),
                    Decimal("309.0301083333"),
                    Decimal("91.3694083333"),
                ],
                [0, 0, 0, Decimal("5.758325"), Decimal("24.352335"), Decimal("19.960865"), Decimal("1.462495")],
                [0, 0, 0, Decimal("0.171355"), Decimal("0.342710"), Decimal("0.342710"), Decimal("0.514065")],
                [0, 0, 0, 0, 0, 0, 0],
            ],
        )

    def test_with_data_and_double_grouping(self):
        results = self._run_revenue_analytics_revenue_query(
            group_by=[RevenueAnalyticsGroupBy.COHORT, RevenueAnalyticsGroupBy.PRODUCT]
        ).results

        # 12 comes from the 6 products * 2 cohorts, plus 1 for the one-off charge invoiceless charge
        self.assertEqual(len(results.gross), 13)
        self.assertEqual(len(results.mrr), 13)

        expected_breakdowns = [
            "stripe.posthog_test - 2025-01 - Product F",
            "stripe.posthog_test - 2025-01 - Product D",
            "stripe.posthog_test - 2025-01 - Product B",
            "stripe.posthog_test - 2025-01 - Product A",
            "stripe.posthog_test - 2025-01 - Product C",
            "stripe.posthog_test - 2025-01 - Product E",
            "stripe.posthog_test - 2025-02 - Product F",
            "stripe.posthog_test - 2025-02 - Product B",
            "stripe.posthog_test - 2025-02 - Product D",
            "stripe.posthog_test - 2025-02 - Product A",
            "stripe.posthog_test - 2025-02 - Product C",
            "stripe.posthog_test - 2025-02 - Product E",
            "stripe.posthog_test - 2025-01 - <none>",
        ]
        self.assertEqual([result["label"] for result in results.gross], expected_breakdowns)
        self.assertEqual([result.total["label"] for result in results.mrr], expected_breakdowns)

        # Very long, but gross first, and then MRR
        self.assertEqual(
            [result["data"] for result in results.gross],
            [
                [
                    0,
                    0,
                    Decimal("4166.17404"),
                    Decimal("4166.17404"),
                    Decimal("4166.17404"),
                    Decimal("4166.17404"),
                    Decimal("8332.34808"),
                ],
                [
                    0,
                    0,
                    Decimal("193.451825"),
                    Decimal("193.451825"),
                    Decimal("193.451825"),
                    Decimal("193.451825"),
                    Decimal("386.90365"),
                ],
                [
                    0,
                    0,
                    Decimal("26.0100949999"),
                    Decimal("26.0100949999"),
                    Decimal("170.5858949999"),
                    Decimal("26.0100949999"),
                    Decimal("46.5169049999"),
                ],
                [
                    0,
                    0,
                    Decimal("8.2024583333"),
                    Decimal("8.2024583333"),
                    Decimal("223.5518583333"),
                    Decimal("8.2024583333"),
                    Decimal("124.1659583333"),
                ],
                [
                    0,
                    0,
                    Decimal("5.758325"),
                    Decimal("5.758325"),
                    Decimal("1.366855"),
                    Decimal("1.366855"),
                    Decimal("9.74731"),
                ],
                [
                    0,
                    0,
                    Decimal("0.171355"),
                    Decimal("0.171355"),
                    Decimal("0.171355"),
                    Decimal("0.171355"),
                    Decimal("0.34271"),
                ],
                [0, 0, 0, Decimal("4166.17404"), Decimal("4166.17404"), Decimal("8332.34808"), 0],
                [0, 0, 0, Decimal("1105.82156"), Decimal("273.57025"), Decimal("150.52939"), 0],
                [0, 0, 0, Decimal("193.451825"), Decimal("193.451825"), Decimal("386.90365"), 0],
                [0, 0, 0, Decimal("85.47825"), Decimal("85.47825"), Decimal("83.16695"), 0],
                [0, 0, 0, Decimal("18.59401"), Decimal("18.59401"), Decimal("0.09564"), 0],
                [0, 0, 0, Decimal("0.171355"), Decimal("0.171355"), Decimal("0.34271"), 0],
                [0, 0, 0, 0, 0, Decimal("289.9386758133"), 0],
            ],
        )

        self.assertEqual(
            [result.total["data"] for result in results.mrr],
            [
                [0, 0, 0, Decimal("4166.17404"), Decimal("4166.17404"), Decimal("4166.17404"), Decimal("4166.17404")],
                [0, 0, 0, Decimal("193.451825"), Decimal("193.451825"), Decimal("193.451825"), Decimal("193.451825")],
                [
                    0,
                    0,
                    0,
                    Decimal("16.3052916666"),
                    Decimal("16.3052916666"),
                    Decimal("88.5931916666"),
                    Decimal("16.3052916666"),
                ],
                [
                    0,
                    0,
                    0,
                    Decimal("8.2024583333"),
                    Decimal("8.2024583333"),
                    Decimal("223.5518583333"),
                    Decimal("8.2024583333"),
                ],
                [0, 0, 0, Decimal("5.758325"), Decimal("5.758325"), Decimal("1.366855"), Decimal("1.366855")],
                [0, 0, 0, Decimal("0.171355"), Decimal("0.171355"), Decimal("0.171355"), Decimal("0.171355")],
                [0, 0, 0, 0, Decimal("4166.17404"), Decimal("4166.17404"), Decimal("8332.34808")],
                [0, 0, 0, 0, Decimal("273.57025"), Decimal("273.57025"), Decimal("79.69203")],
                [0, 0, 0, 0, Decimal("193.451825"), Decimal("193.451825"), Decimal("386.903650")],
                [0, 0, 0, 0, Decimal("85.47825"), Decimal("85.47825"), Decimal("83.16695")],
                [0, 0, 0, 0, Decimal("18.59401"), Decimal("18.59401"), Decimal("0.09564")],
                [0, 0, 0, 0, Decimal("0.171355"), Decimal("0.171355"), Decimal("0.342710")],
                [0, 0, 0, 0, 0, 0, 0],
            ],
        )

    def test_with_product_filter(self):
        expected_data = [
            [
                0,
                0,
                Decimal("5.758325"),
                Decimal("24.352335"),
                Decimal("19.960865"),
                Decimal("1.462495"),
                Decimal("9.74731"),
            ]
        ]

        results = self._run_revenue_analytics_revenue_query(
            properties=[
                RevenueAnalyticsPropertyFilter(
                    key="product",
                    operator=PropertyOperator.EXACT,
                    value=["Product C"],  # Equivalent to `prod_c` but we're querying by name
                )
            ]
        ).results

        self.assertEqual(len(results.gross), 1)
        self.assertEqual(len(results.mrr), 1)
        self.assertEqual([result["label"] for result in results.gross], ["stripe.posthog_test"])
        self.assertEqual([result.total["label"] for result in results.mrr], ["stripe.posthog_test"])
        self.assertEqual([result["data"] for result in results.gross], expected_data)
        self.assertEqual([result.total["data"] for result in results.mrr], [[0, *expected_data[0][:-1]]])

        # When grouping results should be exactly the same, just the label changes
        results = self._run_revenue_analytics_revenue_query(
            group_by=[RevenueAnalyticsGroupBy.PRODUCT],
            properties=[
                RevenueAnalyticsPropertyFilter(
                    key="product",
                    operator=PropertyOperator.EXACT,
                    value=["Product C"],  # Equivalent to `prod_c` but we're querying by name
                )
            ],
        ).results

        self.assertEqual(len(results.gross), 1)
        self.assertEqual(len(results.mrr), 1)
        self.assertEqual([result["label"] for result in results.gross], ["stripe.posthog_test - Product C"])
        self.assertEqual([result.total["label"] for result in results.mrr], ["stripe.posthog_test - Product C"])
        self.assertEqual([result["data"] for result in results.gross], expected_data)
        self.assertEqual([result.total["data"] for result in results.mrr], [[0, *expected_data[0][:-1]]])

    def test_with_country_filter(self):
        results = self._run_revenue_analytics_revenue_query(
            properties=[
                RevenueAnalyticsPropertyFilter(
                    key="country",
                    operator=PropertyOperator.EXACT,
                    value=["US"],
                )
            ]
        ).results

        self.assertEqual(len(results.gross), 1)
        self.assertEqual(len(results.mrr), 1)
        self.assertEqual([result["label"] for result in results.gross], ["stripe.posthog_test"])
        self.assertEqual([result.total["label"] for result in results.mrr], ["stripe.posthog_test"])
        self.assertEqual(
            [result["data"] for result in results.gross],
            [
                [
                    0,
                    0,
                    Decimal("34.2125533332"),
                    Decimal("34.2125533332"),
                    Decimal("394.1377533332"),
                    Decimal("324.1512291465"),
                    Decimal("170.6828633332"),
                ],
            ],
        )
        self.assertEqual(
            [result.total["data"] for result in results.mrr],
            [
                [
                    0,
                    0,
                    0,
                    Decimal("24.5077499999"),
                    Decimal("24.5077499999"),
                    Decimal("312.1450499999"),
                    Decimal("24.5077499999"),
                ]
            ],
        )

    def test_with_events_data(self):
        self.team.revenue_analytics_config.events = [
            REVENUE_ANALYTICS_CONFIG_SAMPLE_EVENT.model_copy(
                update={
                    "subscriptionDropoffMode": "after_dropoff_period",  # More reasonable default for tests
                }
            )
        ]
        self.team.revenue_analytics_config.save()

        s1 = str(uuid7("2025-01-25"))
        s2 = str(uuid7("2025-02-03"))
        s3 = str(uuid7("2025-02-05"))
        s4 = str(uuid7("2025-02-08"))
        self._create_purchase_events(
            [
                (
                    "p1",
                    [
                        ("2025-01-25", s1, 55, "USD", "", "", None),  # Subscriptionless event
                        ("2025-01-25", s1, 42, "USD", "Prod A", "coupon_x", "sub_1"),
                        ("2025-02-03", s2, 25, "USD", "Prod A", "", "sub_1"),  # Contraction
                    ],
                ),
                (
                    "p2",
                    [
                        ("2025-02-05", s3, 43, "BRL", "Prod B", "coupon_y", "sub_2"),
                        ("2025-03-08", s4, 286, "BRL", "Prod B", "", "sub_2"),  # Expansion
                    ],
                ),
            ]
        )

        results = self._run_revenue_analytics_revenue_query(
            properties=[
                RevenueAnalyticsPropertyFilter(
                    key="source",
                    operator=PropertyOperator.EXACT,
                    value=["revenue_analytics.events.purchase"],
                )
            ],
        ).results

        self.assertEqual(len(results.gross), 1)
        self.assertEqual(len(results.mrr), 1)

        gross = results.gross[0]
        mrr = results.mrr[0]

        self.assertEqual(
            gross,
            {
                "label": "revenue_analytics.events.purchase",
                "days": LAST_6_MONTHS_DAYS,
                "labels": LAST_6_MONTHS_LABELS,
                "data": [0, 0, Decimal("77.309"), Decimal("25.4879321819"), Decimal("36.9999675355"), 0, 0],
                "action": {
                    "days": LAST_6_MONTHS_FAKEDATETIMES,
                    "id": "revenue_analytics.events.purchase",
                    "name": "revenue_analytics.events.purchase",
                },
            },
        )

        self.assertEqual(
            mrr.total,
            {
                "label": "revenue_analytics.events.purchase",
                "days": LAST_6_MONTHS_DAYS,
                "labels": LAST_6_MONTHS_LABELS,
                "data": [
                    0,
                    0,
                    0,
                    Decimal("33.474"),
                    Decimal("25.4879321819"),
                    Decimal("36.9999675355"),
                    0,
                ],
                "action": {
                    "days": LAST_6_MONTHS_FAKEDATETIMES,
                    "id": "revenue_analytics.events.purchase",
                    "name": "revenue_analytics.events.purchase",
                },
            },
        )

        self.assertEqual(
            mrr.new,
            {
                "label": "revenue_analytics.events.purchase",
                "days": LAST_6_MONTHS_DAYS,
                "labels": LAST_6_MONTHS_LABELS,
                "data": [
                    0,
                    0,
                    0,
                    Decimal("33.474"),
                    Decimal("5.5629321819"),
                    0,
                    0,
                ],
                "action": {
                    "days": LAST_6_MONTHS_FAKEDATETIMES,
                    "id": "revenue_analytics.events.purchase",
                    "name": "revenue_analytics.events.purchase",
                },
            },
        )

        self.assertEqual(
            mrr.expansion,
            {
                "label": "revenue_analytics.events.purchase",
                "days": LAST_6_MONTHS_DAYS,
                "labels": LAST_6_MONTHS_LABELS,
                "data": [
                    0,
                    0,
                    0,
                    0,
                    0,
                    Decimal("31.4370353536"),
                    0,
                ],
                "action": {
                    "days": LAST_6_MONTHS_FAKEDATETIMES,
                    "id": "revenue_analytics.events.purchase",
                    "name": "revenue_analytics.events.purchase",
                },
            },
        )

        self.assertEqual(
            mrr.contraction,
            {
                "label": "revenue_analytics.events.purchase",
                "days": LAST_6_MONTHS_DAYS,
                "labels": LAST_6_MONTHS_LABELS,
                "data": [
                    0,
                    0,
                    0,
                    0,
                    Decimal("13.549"),
                    0,
                    0,
                ],
                "action": {
                    "days": LAST_6_MONTHS_FAKEDATETIMES,
                    "id": "revenue_analytics.events.purchase",
                    "name": "revenue_analytics.events.purchase",
                },
            },
        )

        self.assertEqual(
            mrr.churn,
            {
                "label": "revenue_analytics.events.purchase",
                "days": LAST_6_MONTHS_DAYS,
                "labels": LAST_6_MONTHS_LABELS,
                "data": [
                    0,
                    0,
                    0,
                    0,
                    0,
                    Decimal("19.925"),
                    Decimal("36.9999675355"),
                ],
                "action": {
                    "days": LAST_6_MONTHS_FAKEDATETIMES,
                    "id": "revenue_analytics.events.purchase",
                    "name": "revenue_analytics.events.purchase",
                },
            },
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
                ("p1", [("2024-12-25", s1, 42, "USD", "Prod A", "coupon_x", None)]),
                ("p2", [("2025-01-03", s2, 43, "BRL", "Prod B", "coupon_y", None)]),
            ]
        )

        results = self._run_revenue_analytics_revenue_query(
            properties=[
                RevenueAnalyticsPropertyFilter(
                    key="source",
                    operator=PropertyOperator.EXACT,
                    value=["revenue_analytics.events.purchase"],
                )
            ],
        ).results

        self.assertEqual(len(results.gross), 1)
        self.assertEqual(len(results.mrr), 1)

        gross = results.gross[0]
        mrr = results.mrr[0]

        self.assertEqual(
            gross,
            {
                "label": "revenue_analytics.events.purchase",
                "days": LAST_6_MONTHS_DAYS,
                "labels": LAST_6_MONTHS_LABELS,
                "data": [0, Decimal("0.33474"), Decimal("0.0556293217"), 0, 0, 0, 0],
                "action": {
                    "days": LAST_6_MONTHS_FAKEDATETIMES,
                    "id": "revenue_analytics.events.purchase",
                    "name": "revenue_analytics.events.purchase",
                },
            },
        )
        self.assertEqual(
            mrr.total,
            {
                "label": "revenue_analytics.events.purchase",
                "days": LAST_6_MONTHS_DAYS,
                "labels": LAST_6_MONTHS_LABELS,
                "data": [0, 0, 0, 0, 0, 0, 0],  # No MRR data because events aren"t recurring
                "action": {
                    "days": LAST_6_MONTHS_FAKEDATETIMES,
                    "id": "revenue_analytics.events.purchase",
                    "name": "revenue_analytics.events.purchase",
                },
            },
        )

    def test_with_events_data_and_grouping(self):
        s1 = str(uuid7("2024-12-25"))
        s2 = str(uuid7("2025-01-02"))
        s3 = str(uuid7("2025-01-03"))
        self._create_purchase_events(
            [
                ("p1", [("2024-12-25", s1, 42, "USD", "Prod A", "coupon_x", None)]),
                ("p2", [("2025-01-02", s2, 43, "BRL", "Prod B", "coupon_y", None)]),
                (
                    "p3",
                    [
                        ("2025-01-03", s3, 75, "GBP", None, "coupon_z", None),
                        ("2025-01-03", s3, 85, "GBP", "Prod C", None, None),
                        ("2025-01-03", s3, 95, "GBP", None, None, None),
                    ],
                ),
            ]
        )

        results = self._run_revenue_analytics_revenue_query(
            properties=[
                RevenueAnalyticsPropertyFilter(
                    key="source",
                    operator=PropertyOperator.EXACT,
                    value=["revenue_analytics.events.purchase"],
                )
            ],
            group_by=[
                RevenueAnalyticsGroupBy.PRODUCT,
                RevenueAnalyticsGroupBy.COUPON,
            ],
        ).results

        self.assertEqual(
            results.gross,
            [
                {
                    "label": "revenue_analytics.events.purchase - Prod A - coupon_x",
                    "days": LAST_6_MONTHS_DAYS,
                    "labels": LAST_6_MONTHS_LABELS,
                    "data": [0, Decimal("33.474"), 0, 0, 0, 0, 0],
                    "action": {
                        "days": LAST_6_MONTHS_FAKEDATETIMES,
                        "id": "revenue_analytics.events.purchase - Prod A - coupon_x",
                        "name": "revenue_analytics.events.purchase - Prod A - coupon_x",
                    },
                },
                {
                    "label": "revenue_analytics.events.purchase - Prod A - <none>",
                    "days": LAST_6_MONTHS_DAYS,
                    "labels": LAST_6_MONTHS_LABELS,
                    "data": [0, 0, 0, 0, 0, 0, 0],
                    "action": {
                        "days": LAST_6_MONTHS_FAKEDATETIMES,
                        "id": "revenue_analytics.events.purchase - Prod A - <none>",
                        "name": "revenue_analytics.events.purchase - Prod A - <none>",
                    },
                },
                {
                    "label": "revenue_analytics.events.purchase - Prod B - coupon_y",
                    "days": LAST_6_MONTHS_DAYS,
                    "labels": LAST_6_MONTHS_LABELS,
                    "data": [0, 0, Decimal("5.5629321819"), 0, 0, 0, 0],
                    "action": {
                        "days": LAST_6_MONTHS_FAKEDATETIMES,
                        "id": "revenue_analytics.events.purchase - Prod B - coupon_y",
                        "name": "revenue_analytics.events.purchase - Prod B - coupon_y",
                    },
                },
                {
                    "label": "revenue_analytics.events.purchase - Prod B - <none>",
                    "days": LAST_6_MONTHS_DAYS,
                    "labels": LAST_6_MONTHS_LABELS,
                    "data": [0, 0, 0, 0, 0, 0, 0],
                    "action": {
                        "days": LAST_6_MONTHS_FAKEDATETIMES,
                        "id": "revenue_analytics.events.purchase - Prod B - <none>",
                        "name": "revenue_analytics.events.purchase - Prod B - <none>",
                    },
                },
                {
                    "label": "revenue_analytics.events.purchase - <none> - <none>",
                    "days": LAST_6_MONTHS_DAYS,
                    "labels": LAST_6_MONTHS_LABELS,
                    "data": [0, 0, Decimal("95"), 0, 0, 0, 0],
                    "action": {
                        "days": LAST_6_MONTHS_FAKEDATETIMES,
                        "id": "revenue_analytics.events.purchase - <none> - <none>",
                        "name": "revenue_analytics.events.purchase - <none> - <none>",
                    },
                },
                {
                    "label": "revenue_analytics.events.purchase - Prod C - <none>",
                    "days": LAST_6_MONTHS_DAYS,
                    "labels": LAST_6_MONTHS_LABELS,
                    "data": [0, 0, Decimal("85"), 0, 0, 0, 0],
                    "action": {
                        "days": LAST_6_MONTHS_FAKEDATETIMES,
                        "id": "revenue_analytics.events.purchase - Prod C - <none>",
                        "name": "revenue_analytics.events.purchase - Prod C - <none>",
                    },
                },
                {
                    "label": "revenue_analytics.events.purchase - <none> - coupon_z",
                    "days": LAST_6_MONTHS_DAYS,
                    "labels": LAST_6_MONTHS_LABELS,
                    "data": [0, 0, Decimal("75"), 0, 0, 0, 0],
                    "action": {
                        "days": LAST_6_MONTHS_FAKEDATETIMES,
                        "id": "revenue_analytics.events.purchase - <none> - coupon_z",
                        "name": "revenue_analytics.events.purchase - <none> - coupon_z",
                    },
                },
            ],
        )

        # No MRR data because events have no subscription
        assert all(entry == 0 for mrr in results.mrr for entry in mrr.total["data"])
