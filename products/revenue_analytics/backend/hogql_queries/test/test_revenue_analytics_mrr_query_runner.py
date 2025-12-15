import hashlib
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
from unittest.mock import ANY, patch

from posthog.schema import (
    CurrencyCode,
    DateRange,
    HogQLQueryModifiers,
    PropertyOperator,
    RevenueAnalyticsBreakdown,
    RevenueAnalyticsMRRQuery,
    RevenueAnalyticsMRRQueryResponse,
    RevenueAnalyticsPropertyFilter,
    SimpleIntervalType,
)

from posthog.models.utils import uuid7
from posthog.temporal.data_imports.sources.stripe.constants import (
    CHARGE_RESOURCE_NAME as STRIPE_CHARGE_RESOURCE_NAME,
    CUSTOMER_RESOURCE_NAME as STRIPE_CUSTOMER_RESOURCE_NAME,
    INVOICE_RESOURCE_NAME as STRIPE_INVOICE_RESOURCE_NAME,
    PRODUCT_RESOURCE_NAME as STRIPE_PRODUCT_RESOURCE_NAME,
    SUBSCRIPTION_RESOURCE_NAME as STRIPE_SUBSCRIPTION_RESOURCE_NAME,
)

from products.data_warehouse.backend.models import ExternalDataSchema
from products.data_warehouse.backend.models.datawarehouse_managed_viewset import DataWarehouseManagedViewSet
from products.data_warehouse.backend.test.utils import create_data_warehouse_table_from_csv
from products.data_warehouse.backend.types import DataWarehouseManagedViewSetKind
from products.revenue_analytics.backend.hogql_queries.revenue_analytics_mrr_query_runner import (
    RevenueAnalyticsMRRQueryRunner,
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

ALL_MONTHS_DAYS = [
    "2024-11-30",
    "2024-12-31",
    "2025-01-31",
    "2025-02-28",
    "2025-03-31",
    "2025-04-30",
    "2025-05-31",
    "2025-06-30",
    "2025-07-31",
    "2025-08-31",
    "2025-09-30",
    "2025-10-31",
    "2025-11-30",
    "2025-12-31",
    "2026-01-31",
    "2026-02-28",
    "2026-03-31",
    "2026-04-30",
    "2026-05-01",  # Last day on the whole query doesn't need to be last day of the month
]
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
ALL_MONTHS_FAKEDATETIMES = [ANY] * 19

LAST_7_MONTHS_DAYS = ALL_MONTHS_DAYS[:7].copy()
LAST_7_MONTHS_LABELS = ALL_MONTHS_LABELS[:7].copy()
LAST_7_MONTHS_FAKEDATETIMES = ALL_MONTHS_FAKEDATETIMES[:7].copy()


@snapshot_clickhouse_queries
class TestRevenueAnalyticsMRRQueryRunner(ClickhouseTestMixin, APIBaseTest):
    QUERY_TIMESTAMP = "2025-05-31"

    def _create_managed_viewsets(self):
        self.viewset, _ = DataWarehouseManagedViewSet.objects.get_or_create(
            team=self.team, kind=DataWarehouseManagedViewSetKind.REVENUE_ANALYTICS
        )
        self.viewset.sync_views()

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
        interval: SimpleIntervalType | None = None,
        breakdown: list[RevenueAnalyticsBreakdown] | None = None,
        properties: list[RevenueAnalyticsPropertyFilter] | None = None,
    ):
        if date_range is None:
            date_range = DateRange(date_from="-6m")
        if interval is None:
            interval = SimpleIntervalType.MONTH
        if breakdown is None:
            breakdown = []
        if properties is None:
            properties = []

        return RevenueAnalyticsMRRQuery(
            dateRange=date_range,
            interval=interval,
            breakdown=breakdown,
            properties=properties,
            modifiers=HogQLQueryModifiers(formatCsvAllowDoubleQuotes=True),
        )

    def _run_revenue_analytics_mrr_query(
        self,
        date_range: DateRange | None = None,
        interval: SimpleIntervalType | None = None,
        breakdown: list[RevenueAnalyticsBreakdown] | None = None,
        properties: list[RevenueAnalyticsPropertyFilter] | None = None,
    ):
        with freeze_time(self.QUERY_TIMESTAMP):
            query = self._build_query(date_range, interval, breakdown, properties)
            runner = RevenueAnalyticsMRRQueryRunner(
                team=self.team,
                query=query,
            )

            response = runner.calculate()

            RevenueAnalyticsMRRQueryResponse.model_validate(response)
            return response

    def test_no_crash_when_no_data(self):
        self.invoices_table.delete()
        self.products_table.delete()
        self.customers_table.delete()
        self.charges_table.delete()
        self.subscriptions_table.delete()
        results = self._run_revenue_analytics_mrr_query().results

        self.assertEqual(results, [])

    def test_no_crash_when_no_source_is_selected(self):
        results = self._run_revenue_analytics_mrr_query(
            properties=[
                RevenueAnalyticsPropertyFilter(
                    key="source_label",
                    operator=PropertyOperator.EXACT,
                    value=["non-existent-source"],
                )
            ],
        ).results

        self.assertEqual(results, [])

    def test_with_data(self):
        # Use huge date range to collect all data
        results = self._run_revenue_analytics_mrr_query(
            date_range=DateRange(date_from="2024-11-01", date_to="2026-05-01")
        ).results

        self.assertEqual(len(results), 1)

        self.assertEqual(
            results[0].total,
            {
                "label": "stripe.posthog_test",
                "days": ALL_MONTHS_DAYS,
                "labels": ALL_MONTHS_LABELS,
                "data": [
                    0,
                    0,
                    Decimal("636.4423413331"),
                    Decimal("1664.1658713331"),
                    Decimal("2027.1834313331"),
                    Decimal("2297.8366613331"),
                    Decimal("1610.3628763904"),
                    Decimal("20.4450263331"),
                    Decimal("20.4450263331"),
                    Decimal("20.4450263331"),
                    Decimal("20.4450263331"),
                    Decimal("20.4450263331"),
                    Decimal("20.4450263331"),
                    Decimal("20.4450263331"),
                    0,
                    0,
                    0,
                    0,
                    0,
                ],
                "breakdown": {"property": "stripe.posthog_test", "kind": None},
                "action": {
                    "days": ALL_MONTHS_FAKEDATETIMES,
                    "id": "stripe.posthog_test",
                    "name": "stripe.posthog_test",
                },
            },
        )

        self.assertEqual(
            results[0].new,
            {
                "label": "New | stripe.posthog_test",
                "days": ALL_MONTHS_DAYS,
                "labels": ALL_MONTHS_LABELS,
                "data": [
                    0,
                    0,
                    Decimal("636.4423413331"),
                    Decimal("1027.72353"),
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
                    0,
                ],
                "breakdown": {"property": "stripe.posthog_test", "kind": "New"},
                "action": {
                    "days": ALL_MONTHS_FAKEDATETIMES,
                    "id": "New | stripe.posthog_test",
                    "name": "New | stripe.posthog_test",
                },
            },
        )

        self.assertEqual(
            results[0].expansion,
            {
                "label": "Expansion | stripe.posthog_test",
                "days": ALL_MONTHS_DAYS,
                "labels": ALL_MONTHS_LABELS,
                "data": [
                    0,
                    0,
                    0,
                    0,
                    Decimal("363.01756"),
                    Decimal("790.34505"),
                    Decimal("898.5402750573"),
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
                "breakdown": {"property": "stripe.posthog_test", "kind": "Expansion"},
                "action": {
                    "days": ALL_MONTHS_FAKEDATETIMES,
                    "id": "Expansion | stripe.posthog_test",
                    "name": "Expansion | stripe.posthog_test",
                },
            },
        )

        self.assertEqual(
            results[0].contraction,
            {
                "label": "Contraction | stripe.posthog_test",
                "days": ALL_MONTHS_DAYS,
                "labels": ALL_MONTHS_LABELS,
                "data": [
                    0,
                    0,
                    0,
                    0,
                    0,
                    Decimal("-519.69182"),
                    0,
                    Decimal("-43.3234100573"),
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
                "breakdown": {"property": "stripe.posthog_test", "kind": "Contraction"},
                "action": {
                    "days": ALL_MONTHS_FAKEDATETIMES,
                    "id": "Contraction | stripe.posthog_test",
                    "name": "Contraction | stripe.posthog_test",
                },
            },
        )

        self.assertEqual(
            results[0].churn,
            {
                "label": "Churn | stripe.posthog_test",
                "days": ALL_MONTHS_DAYS,
                "labels": ALL_MONTHS_LABELS,
                "data": [
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    Decimal("-1586.01406"),
                    Decimal("-1546.59444"),
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    Decimal("-20.4450263331"),
                    0,
                    0,
                    0,
                    0,
                ],
                "breakdown": {"property": "stripe.posthog_test", "kind": "Churn"},
                "action": {
                    "days": ALL_MONTHS_FAKEDATETIMES,
                    "id": "Churn | stripe.posthog_test",
                    "name": "Churn | stripe.posthog_test",
                },
            },
        )

        # Iterate over the values and check that the new/expansion/contraction/churn values
        # properly add up to the change between the previous period and the current period
        #
        # NOTE: We're summing contraction and churn because they're negative values
        previous = Decimal(0)
        for i in range(len(results[0].total["data"])):
            change_to_previous = results[0].total["data"][i] - previous
            change = (
                results[0].new["data"][i]
                + results[0].expansion["data"][i]
                + results[0].contraction["data"][i]
                + results[0].churn["data"][i]
            )
            self.assertEqual(change_to_previous, change, f"MRR change at index {i} is incorrect")
            previous = results[0].total["data"][i]

    def test_with_data_with_managed_viewsets_ff(self):
        with patch("posthoganalytics.feature_enabled", return_value=True):
            self._create_managed_viewsets()

            # Use huge date range to collect all data
            results = self._run_revenue_analytics_mrr_query(
                date_range=DateRange(date_from="2024-11-01", date_to="2026-05-01")
            ).results

            self.assertEqual(len(results), 1)

            self.assertEqual(
                results[0].total,
                {
                    "label": "stripe.posthog_test",
                    "days": ALL_MONTHS_DAYS,
                    "labels": ALL_MONTHS_LABELS,
                    "data": [
                        0,
                        0,
                        Decimal("636.4423413331"),
                        Decimal("1664.1658713331"),
                        Decimal("2027.1834313331"),
                        Decimal("2297.8366613331"),
                        Decimal("1610.3628763904"),
                        Decimal("20.4450263331"),
                        Decimal("20.4450263331"),
                        Decimal("20.4450263331"),
                        Decimal("20.4450263331"),
                        Decimal("20.4450263331"),
                        Decimal("20.4450263331"),
                        Decimal("20.4450263331"),
                        0,
                        0,
                        0,
                        0,
                        0,
                    ],
                    "breakdown": {"property": "stripe.posthog_test", "kind": None},
                    "action": {
                        "days": ALL_MONTHS_FAKEDATETIMES,
                        "id": "stripe.posthog_test",
                        "name": "stripe.posthog_test",
                    },
                },
            )

            self.assertEqual(
                results[0].new,
                {
                    "label": "New | stripe.posthog_test",
                    "days": ALL_MONTHS_DAYS,
                    "labels": ALL_MONTHS_LABELS,
                    "data": [
                        0,
                        0,
                        Decimal("636.4423413331"),
                        Decimal("1027.72353"),
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
                        0,
                    ],
                    "breakdown": {"property": "stripe.posthog_test", "kind": "New"},
                    "action": {
                        "days": ALL_MONTHS_FAKEDATETIMES,
                        "id": "New | stripe.posthog_test",
                        "name": "New | stripe.posthog_test",
                    },
                },
            )

            self.assertEqual(
                results[0].expansion,
                {
                    "label": "Expansion | stripe.posthog_test",
                    "days": ALL_MONTHS_DAYS,
                    "labels": ALL_MONTHS_LABELS,
                    "data": [
                        0,
                        0,
                        0,
                        0,
                        Decimal("363.01756"),
                        Decimal("790.34505"),
                        Decimal("898.5402750573"),
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
                    "breakdown": {"property": "stripe.posthog_test", "kind": "Expansion"},
                    "action": {
                        "days": ALL_MONTHS_FAKEDATETIMES,
                        "id": "Expansion | stripe.posthog_test",
                        "name": "Expansion | stripe.posthog_test",
                    },
                },
            )

            self.assertEqual(
                results[0].contraction,
                {
                    "label": "Contraction | stripe.posthog_test",
                    "days": ALL_MONTHS_DAYS,
                    "labels": ALL_MONTHS_LABELS,
                    "data": [
                        0,
                        0,
                        0,
                        0,
                        0,
                        Decimal("-519.69182"),
                        0,
                        Decimal("-43.3234100573"),
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
                    "breakdown": {"property": "stripe.posthog_test", "kind": "Contraction"},
                    "action": {
                        "days": ALL_MONTHS_FAKEDATETIMES,
                        "id": "Contraction | stripe.posthog_test",
                        "name": "Contraction | stripe.posthog_test",
                    },
                },
            )

            self.assertEqual(
                results[0].churn,
                {
                    "label": "Churn | stripe.posthog_test",
                    "days": ALL_MONTHS_DAYS,
                    "labels": ALL_MONTHS_LABELS,
                    "data": [
                        0,
                        0,
                        0,
                        0,
                        0,
                        0,
                        Decimal("-1586.01406"),
                        Decimal("-1546.59444"),
                        0,
                        0,
                        0,
                        0,
                        0,
                        0,
                        Decimal("-20.4450263331"),
                        0,
                        0,
                        0,
                        0,
                    ],
                    "breakdown": {"property": "stripe.posthog_test", "kind": "Churn"},
                    "action": {
                        "days": ALL_MONTHS_FAKEDATETIMES,
                        "id": "Churn | stripe.posthog_test",
                        "name": "Churn | stripe.posthog_test",
                    },
                },
            )

            # Iterate over the values and check that the new/expansion/contraction/churn values
            # properly add up to the change between the previous period and the current period
            #
            # NOTE: We're summing contraction and churn because they're negative values
            previous = Decimal(0)
            for i in range(len(results[0].total["data"])):
                change_to_previous = results[0].total["data"][i] - previous
                change = (
                    results[0].new["data"][i]
                    + results[0].expansion["data"][i]
                    + results[0].contraction["data"][i]
                    + results[0].churn["data"][i]
                )
                self.assertEqual(change_to_previous, change, f"MRR change at index {i} is incorrect")
                previous = results[0].total["data"][i]

        def test_with_data_and_date_range(self):
            results = self._run_revenue_analytics_mrr_query(
                date_range=DateRange(date_from="2025-02-01", date_to="2025-05-01")
            ).results

            self.assertEqual(len(results), 1)

            self.assertEqual(
                results[0].total,
                {
                    "label": "stripe.posthog_test",
                    # May 1st because we use end of interval
                    "days": ["2025-02-28", "2025-03-31", "2025-04-30", "2025-05-01"],
                    "labels": ["Feb 2025", "Mar 2025", "Apr 2025", "May 2025"],
                    # This is an important test, see how MRR is included for the first month, because there's previous data from January 30 days prior to February 1st
                    "data": [
                        Decimal("1664.1658713331"),
                        Decimal("2027.1834313331"),
                        Decimal("2297.8366613331"),
                        Decimal("2297.8366613331"),
                    ],
                    "breakdown": {"property": "stripe.posthog_test", "kind": None},
                    "action": {"days": [ANY] * 4, "id": "stripe.posthog_test", "name": "stripe.posthog_test"},
                },
            )

    def test_with_data_and_date_range_for_daily_interval(self):
        results = self._run_revenue_analytics_mrr_query(
            date_range=DateRange(date_from="2025-02-01", date_to="2025-05-01"),
            interval=SimpleIntervalType.DAY,
        ).results

        self.assertEqual(len(results), 1)

        # There are 90 days between February 1st and May 1st
        a_lot_of_anys = [ANY] * 90
        self.assertEqual(
            results[0].total,
            {
                "label": "stripe.posthog_test",
                "days": a_lot_of_anys,
                "labels": a_lot_of_anys,
                "data": a_lot_of_anys,
                "breakdown": {"property": "stripe.posthog_test", "kind": None},
                "action": {"days": a_lot_of_anys, "id": "stripe.posthog_test", "name": "stripe.posthog_test"},
            },
        )

        # Asserting on the actual values would make this file humongous, so let's just assert on some aggregates!
        # Check sum of all MRR values and also a hash of the values
        total_mrr = sum(results[0].total["data"])
        self.assertEqual(total_mrr, Decimal("144121.5922299790"))
        self.assertEqual(
            hashlib.sha256(",".join(str(x) for x in results[0].total["data"]).encode()).hexdigest(),
            "6d4d5493654fae577ae2c3ca45e20c0713b8fa071f25be618dc8b3621e996434",
        )

        new_mrr = sum(results[0].new["data"])
        self.assertEqual(new_mrr, Decimal("1027.72353"))
        self.assertEqual(
            hashlib.sha256(",".join(str(x) for x in results[0].new["data"]).encode()).hexdigest(),
            "61f5a7730f25acad320b476d884eca9360f881cacfefe524d6e3174a7ae364a0",
        )

        expansion_mrr = sum(results[0].expansion["data"])
        self.assertEqual(expansion_mrr, Decimal("1153.36261"))
        self.assertEqual(
            hashlib.sha256(",".join(str(x) for x in results[0].expansion["data"]).encode()).hexdigest(),
            "6bb00ac4691e4ae161f74bfed10a24abe38ff45484f6ebdd8e1e75dc308b8a84",
        )

        contraction_mrr = sum(results[0].contraction["data"])
        self.assertEqual(contraction_mrr, Decimal("-519.69182"))
        self.assertEqual(
            hashlib.sha256(",".join(str(x) for x in results[0].contraction["data"]).encode()).hexdigest(),
            "3ae3548dcb601bb1f6f3f6acf32cf0b0cba97be0d3a94a6e9391ee38c40363a4",
        )

        churn_mrr = sum(results[0].churn["data"])
        self.assertEqual(churn_mrr, 0)
        self.assertEqual(
            hashlib.sha256(",".join(str(x) for x in results[0].churn["data"]).encode()).hexdigest(),
            "c437cc187e67c1ac601f65fcc1ac3a5d492ba904c63ed805109e4a417c98865b",
        )

        # Iterate over the values and check that the new/expansion/contraction/churn values
        # properly add up to the change between the previous period and the current period
        #
        # NOTE: We're summing contraction and churn because they're negative values
        previous = results[0].total["data"][0]
        for i in range(len(results[0].total["data"])):
            change_to_previous = results[0].total["data"][i] - previous
            change = (
                results[0].new["data"][i]
                + results[0].expansion["data"][i]
                + results[0].contraction["data"][i]
                + results[0].churn["data"][i]
            )
            self.assertEqual(change_to_previous, change, f"MRR change at index {i} is incorrect")
            previous = results[0].total["data"][i]

    def test_with_empty_date_range(self):
        results = self._run_revenue_analytics_mrr_query(
            date_range=DateRange(date_from="2024-12-01", date_to="2024-12-31")
        ).results

        self.assertEqual(results, [])

    def test_with_data_and_product_grouping(self):
        results = self._run_revenue_analytics_mrr_query(
            breakdown=[RevenueAnalyticsBreakdown(property="revenue_analytics_product.name")]
        ).results

        self.assertEqual(len(results), 6)

        expected_products = [
            "stripe.posthog_test - Product A",
            "stripe.posthog_test - Product B",
            "stripe.posthog_test - Product C",
            "stripe.posthog_test - Product D",
            "stripe.posthog_test - Product E",
            "stripe.posthog_test - Product F",
        ]
        self.assertEqual([result.total["label"] for result in results], expected_products)

        self.assertEqual(
            [result.total["data"] for result in results],
            [
                [
                    0,
                    0,
                    Decimal("4.1397346665"),
                    Decimal("89.6179846665"),
                    Decimal("304.9673846665"),
                    Decimal("87.3066846665"),
                    Decimal("106.1300947238"),
                ],
                [
                    0,
                    0,
                    Decimal("16.3052916666"),
                    Decimal("289.8755416666"),
                    Decimal("362.1634416666"),
                    Decimal("60.1323216666"),
                    Decimal("84.6323216666"),
                ],
                [
                    0,
                    0,
                    Decimal("5.758325"),
                    Decimal("24.352335"),
                    Decimal("19.960865"),
                    Decimal("1.462495"),
                    Decimal("0.09564"),
                ],
                [
                    0,
                    0,
                    Decimal("193.451825"),
                    Decimal("386.90365"),
                    Decimal("386.90365"),
                    Decimal("580.355475"),
                    Decimal("773.8073"),
                ],
                [
                    0,
                    0,
                    Decimal("0.171355"),
                    Decimal("0.34271"),
                    Decimal("0.34271"),
                    Decimal("0.514065"),
                    Decimal("0.68542"),
                ],
                [
                    0,
                    0,
                    Decimal("416.61581"),
                    Decimal("873.07365"),
                    Decimal("952.84538"),
                    Decimal("1568.06562"),
                    Decimal("1159.34808"),
                ],
            ],
        )

    def test_with_data_and_double_grouping(self):
        results = self._run_revenue_analytics_mrr_query(
            breakdown=[
                RevenueAnalyticsBreakdown(property="revenue_analytics_customer.cohort"),
                RevenueAnalyticsBreakdown(property="revenue_analytics_product.name"),
            ]
        ).results

        # 12 comes from the 6 products * 2 cohorts
        self.assertEqual(len(results), 12)

        expected_breakdowns = [
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
        ]
        self.assertEqual([result.total["label"] for result in results], expected_breakdowns)

        self.assertEqual(
            [result.total["data"] for result in results],
            [
                [
                    0,
                    0,
                    Decimal("4.1397346665"),
                    Decimal("4.1397346665"),
                    Decimal("219.4891346665"),
                    Decimal("4.1397346665"),
                    Decimal("22.9631447238"),
                ],
                [
                    0,
                    0,
                    Decimal("16.3052916666"),
                    Decimal("16.3052916666"),
                    Decimal("88.5931916666"),
                    Decimal("16.3052916666"),
                    Decimal("40.8052916666"),
                ],
                [0, 0, Decimal("5.758325"), Decimal("5.758325"), Decimal("1.366855"), Decimal("1.366855"), 0],
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
                    Decimal("0.171355"),
                    Decimal("0.171355"),
                    Decimal("0.171355"),
                    Decimal("0.171355"),
                    Decimal("0.34271"),
                ],
                [
                    0,
                    0,
                    Decimal("416.61581"),
                    Decimal("416.61581"),
                    Decimal("496.38754"),
                    Decimal("496.38754"),
                    Decimal("1159.34808"),
                ],
                [0, 0, 0, Decimal("85.47825"), Decimal("85.47825"), Decimal("83.16695"), Decimal("83.16695")],
                [0, 0, 0, Decimal("273.57025"), Decimal("273.57025"), Decimal("43.82703"), Decimal("43.82703")],
                [0, 0, 0, Decimal("18.59401"), Decimal("18.59401"), Decimal("0.09564"), Decimal("0.09564")],
                [0, 0, 0, Decimal("193.451825"), Decimal("193.451825"), Decimal("386.90365"), Decimal("386.90365")],
                [0, 0, 0, Decimal("0.171355"), Decimal("0.171355"), Decimal("0.34271"), Decimal("0.34271")],
                [0, 0, 0, Decimal("456.45784"), Decimal("456.45784"), Decimal("1071.67808"), 0],
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
                Decimal("0.09564"),
            ]
        ]

        results = self._run_revenue_analytics_mrr_query(
            properties=[
                RevenueAnalyticsPropertyFilter(
                    key="revenue_analytics_product.name",
                    operator=PropertyOperator.EXACT,
                    value=["Product C"],  # Equivalent to `prod_c` but we're querying by name
                )
            ]
        ).results

        self.assertEqual(len(results), 1)
        self.assertEqual([result.total["label"] for result in results], ["stripe.posthog_test"])
        self.assertEqual([result.total["data"] for result in results], expected_data)

        # When grouping results should be exactly the same, just the label changes
        results = self._run_revenue_analytics_mrr_query(
            breakdown=[RevenueAnalyticsBreakdown(property="revenue_analytics_product.name")],
            properties=[
                RevenueAnalyticsPropertyFilter(
                    key="revenue_analytics_product.name",
                    operator=PropertyOperator.EXACT,
                    value=["Product C"],  # Equivalent to `prod_c` but we're querying by name
                )
            ],
        ).results

        self.assertEqual(len(results), 1)
        self.assertEqual([result.total["label"] for result in results], ["stripe.posthog_test - Product C"])
        self.assertEqual([result.total["data"] for result in results], expected_data)

    def test_with_country_filter(self):
        results = self._run_revenue_analytics_mrr_query(
            properties=[
                RevenueAnalyticsPropertyFilter(
                    key="revenue_analytics_customer.country",
                    operator=PropertyOperator.EXACT,
                    value=["US"],
                )
            ]
        ).results

        self.assertEqual(len(results), 1)
        self.assertEqual([result.total["label"] for result in results], ["stripe.posthog_test"])
        self.assertEqual(
            [result.total["data"] for result in results],
            [
                [
                    0,
                    0,
                    Decimal("20.4450263331"),
                    Decimal("20.4450263331"),
                    Decimal("308.0823263331"),
                    Decimal("20.4450263331"),
                    Decimal("63.7684363904"),
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

        results = self._run_revenue_analytics_mrr_query(
            properties=[
                RevenueAnalyticsPropertyFilter(
                    key="source_label",
                    operator=PropertyOperator.EXACT,
                    value=["revenue_analytics.events.purchase"],
                )
            ],
        ).results

        self.assertEqual(len(results), 1)

        self.assertEqual(
            results[0].total,
            {
                "label": "revenue_analytics.events.purchase",
                "days": LAST_7_MONTHS_DAYS,
                "labels": LAST_7_MONTHS_LABELS,
                "data": [0, 0, Decimal("33.474"), Decimal("25.4879321819"), Decimal("36.9999675355"), 0, 0],
                "breakdown": {"property": "revenue_analytics.events.purchase", "kind": None},
                "action": {
                    "days": LAST_7_MONTHS_FAKEDATETIMES,
                    "id": "revenue_analytics.events.purchase",
                    "name": "revenue_analytics.events.purchase",
                },
            },
        )

        self.assertEqual(
            results[0].new,
            {
                "label": "New | revenue_analytics.events.purchase",
                "days": LAST_7_MONTHS_DAYS,
                "labels": LAST_7_MONTHS_LABELS,
                "data": [0, 0, Decimal("33.474"), Decimal("5.5629321819"), 0, 0, 0],
                "breakdown": {"property": "revenue_analytics.events.purchase", "kind": "New"},
                "action": {
                    "days": LAST_7_MONTHS_FAKEDATETIMES,
                    "id": "New | revenue_analytics.events.purchase",
                    "name": "New | revenue_analytics.events.purchase",
                },
            },
        )

        self.assertEqual(
            results[0].expansion,
            {
                "label": "Expansion | revenue_analytics.events.purchase",
                "days": LAST_7_MONTHS_DAYS,
                "labels": LAST_7_MONTHS_LABELS,
                "data": [0, 0, 0, 0, Decimal("31.4370353536"), 0, 0],
                "breakdown": {"property": "revenue_analytics.events.purchase", "kind": "Expansion"},
                "action": {
                    "days": LAST_7_MONTHS_FAKEDATETIMES,
                    "id": "Expansion | revenue_analytics.events.purchase",
                    "name": "Expansion | revenue_analytics.events.purchase",
                },
            },
        )

        self.assertEqual(
            results[0].contraction,
            {
                "label": "Contraction | revenue_analytics.events.purchase",
                "days": LAST_7_MONTHS_DAYS,
                "labels": LAST_7_MONTHS_LABELS,
                "data": [0, 0, 0, Decimal("-13.549"), 0, 0, 0],
                "breakdown": {"property": "revenue_analytics.events.purchase", "kind": "Contraction"},
                "action": {
                    "days": LAST_7_MONTHS_FAKEDATETIMES,
                    "id": "Contraction | revenue_analytics.events.purchase",
                    "name": "Contraction | revenue_analytics.events.purchase",
                },
            },
        )

        self.assertEqual(
            results[0].churn,
            {
                "label": "Churn | revenue_analytics.events.purchase",
                "days": LAST_7_MONTHS_DAYS,
                "labels": LAST_7_MONTHS_LABELS,
                "data": [0, 0, 0, 0, Decimal("-19.925"), Decimal("-36.9999675355"), 0],
                "breakdown": {"property": "revenue_analytics.events.purchase", "kind": "Churn"},
                "action": {
                    "days": LAST_7_MONTHS_FAKEDATETIMES,
                    "id": "Churn | revenue_analytics.events.purchase",
                    "name": "Churn | revenue_analytics.events.purchase",
                },
            },
        )

    def test_with_events_data_with_managed_viewsets_ff(self):
        with patch("posthoganalytics.feature_enabled", return_value=True):
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

            self.team.revenue_analytics_config.events = [
                REVENUE_ANALYTICS_CONFIG_SAMPLE_EVENT.model_copy(
                    update={
                        "subscriptionDropoffMode": "after_dropoff_period",  # More reasonable default for tests
                    }
                )
            ]
            self.team.revenue_analytics_config.save()
            self._create_managed_viewsets()

            results = self._run_revenue_analytics_mrr_query(
                properties=[
                    RevenueAnalyticsPropertyFilter(
                        key="source_label",
                        operator=PropertyOperator.EXACT,
                        value=["revenue_analytics.events.purchase"],
                    )
                ],
            ).results

            self.assertEqual(len(results), 1)

            self.assertEqual(
                results[0].total,
                {
                    "label": "revenue_analytics.events.purchase",
                    "days": LAST_7_MONTHS_DAYS,
                    "labels": LAST_7_MONTHS_LABELS,
                    "data": [0, 0, Decimal("33.474"), Decimal("25.4879321819"), Decimal("36.9999675355"), 0, 0],
                    "breakdown": {"property": "revenue_analytics.events.purchase", "kind": None},
                    "action": {
                        "days": LAST_7_MONTHS_FAKEDATETIMES,
                        "id": "revenue_analytics.events.purchase",
                        "name": "revenue_analytics.events.purchase",
                    },
                },
            )

            self.assertEqual(
                results[0].new,
                {
                    "label": "New | revenue_analytics.events.purchase",
                    "days": LAST_7_MONTHS_DAYS,
                    "labels": LAST_7_MONTHS_LABELS,
                    "data": [0, 0, Decimal("33.474"), Decimal("5.5629321819"), 0, 0, 0],
                    "breakdown": {"property": "revenue_analytics.events.purchase", "kind": "New"},
                    "action": {
                        "days": LAST_7_MONTHS_FAKEDATETIMES,
                        "id": "New | revenue_analytics.events.purchase",
                        "name": "New | revenue_analytics.events.purchase",
                    },
                },
            )

            self.assertEqual(
                results[0].expansion,
                {
                    "label": "Expansion | revenue_analytics.events.purchase",
                    "days": LAST_7_MONTHS_DAYS,
                    "labels": LAST_7_MONTHS_LABELS,
                    "data": [0, 0, 0, 0, Decimal("31.4370353536"), 0, 0],
                    "breakdown": {"property": "revenue_analytics.events.purchase", "kind": "Expansion"},
                    "action": {
                        "days": LAST_7_MONTHS_FAKEDATETIMES,
                        "id": "Expansion | revenue_analytics.events.purchase",
                        "name": "Expansion | revenue_analytics.events.purchase",
                    },
                },
            )

            self.assertEqual(
                results[0].contraction,
                {
                    "label": "Contraction | revenue_analytics.events.purchase",
                    "days": LAST_7_MONTHS_DAYS,
                    "labels": LAST_7_MONTHS_LABELS,
                    "data": [0, 0, 0, Decimal("-13.549"), 0, 0, 0],
                    "breakdown": {"property": "revenue_analytics.events.purchase", "kind": "Contraction"},
                    "action": {
                        "days": LAST_7_MONTHS_FAKEDATETIMES,
                        "id": "Contraction | revenue_analytics.events.purchase",
                        "name": "Contraction | revenue_analytics.events.purchase",
                    },
                },
            )

            self.assertEqual(
                results[0].churn,
                {
                    "label": "Churn | revenue_analytics.events.purchase",
                    "days": LAST_7_MONTHS_DAYS,
                    "labels": LAST_7_MONTHS_LABELS,
                    "data": [0, 0, 0, 0, Decimal("-19.925"), Decimal("-36.9999675355"), 0],
                    "breakdown": {"property": "revenue_analytics.events.purchase", "kind": "Churn"},
                    "action": {
                        "days": LAST_7_MONTHS_FAKEDATETIMES,
                        "id": "Churn | revenue_analytics.events.purchase",
                        "name": "Churn | revenue_analytics.events.purchase",
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

        results = self._run_revenue_analytics_mrr_query(
            properties=[
                RevenueAnalyticsPropertyFilter(
                    key="source_label",
                    operator=PropertyOperator.EXACT,
                    value=["revenue_analytics.events.purchase"],
                )
            ],
        ).results

        self.assertEqual(len(results), 1)
        self.assertEqual(
            results[0].total,
            {
                "label": "revenue_analytics.events.purchase",
                "days": LAST_7_MONTHS_DAYS,
                "labels": LAST_7_MONTHS_LABELS,
                "data": [0, 0, 0, 0, 0, 0, 0],  # No MRR data because events aren"t recurring/got no subscription
                "breakdown": {"property": "revenue_analytics.events.purchase", "kind": None},
                "action": {
                    "days": LAST_7_MONTHS_FAKEDATETIMES,
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

        results = self._run_revenue_analytics_mrr_query(
            properties=[
                RevenueAnalyticsPropertyFilter(
                    key="source_label",
                    operator=PropertyOperator.EXACT,
                    value=["revenue_analytics.events.purchase"],
                )
            ],
            breakdown=[
                RevenueAnalyticsBreakdown(property="revenue_analytics_product.name"),
                RevenueAnalyticsBreakdown(property="revenue_analytics_coupon.name"),
            ],
        ).results

        # No MRR data because events have no subscription
        assert all(entry == 0 for result in results for entry in result.total["data"])
