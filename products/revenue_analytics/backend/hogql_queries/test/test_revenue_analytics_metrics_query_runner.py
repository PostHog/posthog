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
from unittest.mock import ANY

from posthog.schema import (
    CurrencyCode,
    DateRange,
    HogQLQueryModifiers,
    IntervalType,
    PropertyOperator,
    RevenueAnalyticsBreakdown,
    RevenueAnalyticsMetricsQuery,
    RevenueAnalyticsMetricsQueryResponse,
    RevenueAnalyticsPropertyFilter,
    SubscriptionDropoffMode,
)

from posthog.models.utils import uuid7
from posthog.temporal.data_imports.sources.stripe.constants import (
    CHARGE_RESOURCE_NAME as STRIPE_CHARGE_RESOURCE_NAME,
    CUSTOMER_RESOURCE_NAME as STRIPE_CUSTOMER_RESOURCE_NAME,
    INVOICE_RESOURCE_NAME as STRIPE_INVOICE_RESOURCE_NAME,
    PRODUCT_RESOURCE_NAME as STRIPE_PRODUCT_RESOURCE_NAME,
    SUBSCRIPTION_RESOURCE_NAME as STRIPE_SUBSCRIPTION_RESOURCE_NAME,
)
from posthog.warehouse.models import ExternalDataSchema
from posthog.warehouse.test.utils import create_data_warehouse_table_from_csv

from products.revenue_analytics.backend.hogql_queries.revenue_analytics_metrics_query_runner import (
    RevenueAnalyticsMetricsQueryRunner,
)
from products.revenue_analytics.backend.hogql_queries.test.data.structure import (
    REVENUE_ANALYTICS_CONFIG_SAMPLE_EVENT,
    STRIPE_CHARGE_COLUMNS,
    STRIPE_CUSTOMER_COLUMNS,
    STRIPE_INVOICE_COLUMNS,
    STRIPE_PRODUCT_COLUMNS,
    STRIPE_SUBSCRIPTION_COLUMNS,
)

SUBSCRIPTIONS_TEST_BUCKET = "test_storage_bucket-posthog.revenue_analytics.insights_query_runner.stripe_subscriptions"
PRODUCTS_TEST_BUCKET = "test_storage_bucket-posthog.revenue_analytics.insights_query_runner.stripe_products"
CUSTOMERS_TEST_BUCKET = "test_storage_bucket-posthog.revenue_analytics.insights_query_runner.stripe_customers"
INVOICES_TEST_BUCKET = "test_storage_bucket-posthog.revenue_analytics.insights_query_runner.stripe_invoices"
CHARGES_TEST_BUCKET = "test_storage_bucket-posthog.revenue_analytics.insights_query_runner.stripe_charges"

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
class TestRevenueAnalyticsMetricsQueryRunner(ClickhouseTestMixin, APIBaseTest):
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
            for timestamp, session_id, revenue, currency, extra_properties in timestamps:
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
                            **extra_properties,
                        },
                    )
                )
            person_result.append((person, event_ids))
        return person_result

    def setUp(self):
        super().setUp()

        self.subscriptions_csv_path = Path(__file__).parent / "data" / "stripe_subscriptions.csv"
        (
            self.subscriptions_table,
            self.source,
            self.credential,
            self.subscriptions_csv_df,
            self.subscriptions_cleanup_filesystem,
        ) = create_data_warehouse_table_from_csv(
            self.subscriptions_csv_path,
            "stripe_subscription",
            STRIPE_SUBSCRIPTION_COLUMNS,
            SUBSCRIPTIONS_TEST_BUCKET,
            self.team,
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

        self.invoices_csv_path = Path(__file__).parent / "data" / "stripe_invoices.csv"
        self.invoices_table, _, _, self.invoices_csv_df, self.invoices_cleanup_filesystem = (
            create_data_warehouse_table_from_csv(
                self.invoices_csv_path,
                "stripe_invoice",
                STRIPE_INVOICE_COLUMNS,
                INVOICES_TEST_BUCKET,
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

        # Besides the default creation above, also create the external data schema
        # because this is required by the `RevenueAnalyticsBaseView` to find the right tables
        self.subscriptions_schema = ExternalDataSchema.objects.create(
            team=self.team,
            name=STRIPE_SUBSCRIPTION_RESOURCE_NAME,
            source=self.source,
            table=self.subscriptions_table,
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

        self.customers_schema = ExternalDataSchema.objects.create(
            team=self.team,
            name=STRIPE_CUSTOMER_RESOURCE_NAME,
            source=self.source,
            table=self.customers_table,
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

        self.charges_schema = ExternalDataSchema.objects.create(
            team=self.team,
            name=STRIPE_CHARGE_RESOURCE_NAME,
            source=self.source,
            table=self.charges_table,
            should_sync=True,
            last_synced_at="2024-01-01",
        )

        self.team.base_currency = CurrencyCode.GBP.value
        self.team.revenue_analytics_config.events = [REVENUE_ANALYTICS_CONFIG_SAMPLE_EVENT]
        self.team.revenue_analytics_config.save()
        self.team.save()

    def tearDown(self):
        self.charges_cleanup_filesystem()
        self.subscriptions_cleanup_filesystem()
        self.products_cleanup_filesystem()
        self.customers_cleanup_filesystem()
        self.invoices_cleanup_filesystem()
        super().tearDown()

    def _run_revenue_analytics_metrics_query(
        self,
        date_range: DateRange | None = None,
        interval: IntervalType | None = None,
        breakdown: list[RevenueAnalyticsBreakdown] | None = None,
        properties: list[RevenueAnalyticsPropertyFilter] | None = None,
    ):
        if date_range is None:
            date_range = DateRange(date_from="-6m")
        if interval is None:
            interval = IntervalType.MONTH
        if breakdown is None:
            breakdown = []
        if properties is None:
            properties = []

        with freeze_time(self.QUERY_TIMESTAMP):
            query = RevenueAnalyticsMetricsQuery(
                dateRange=date_range,
                interval=interval,
                breakdown=breakdown,
                properties=properties,
                modifiers=HogQLQueryModifiers(formatCsvAllowDoubleQuotes=True),
            )

            runner = RevenueAnalyticsMetricsQueryRunner(
                team=self.team,
                query=query,
            )
            response = runner.calculate()

            RevenueAnalyticsMetricsQueryResponse.model_validate(response)
            return response

    def test_no_crash_when_no_data(self):
        self.subscriptions_table.delete()
        self.products_table.delete()
        self.customers_table.delete()
        self.invoices_table.delete()
        self.charges_table.delete()
        results = self._run_revenue_analytics_metrics_query().results

        self.assertEqual(results, [])

    def test_no_crash_when_no_source_is_selected(self):
        results = self._run_revenue_analytics_metrics_query(
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
        results = self._run_revenue_analytics_metrics_query(
            date_range=DateRange(date_from="2024-11-01", date_to="2026-05-01")
        ).results

        self.assertEqual(
            results,
            [
                {
                    "label": "Subscription Count | stripe.posthog_test",
                    "days": ALL_MONTHS_DAYS,
                    "labels": ALL_MONTHS_LABELS,
                    "data": [0, 0, 3, 6, 6, 6, 6, 3, 2, 2, 2, 2, 2, 2, 2, 0, 0, 0, 0],
                    "breakdown": {
                        "property": "stripe.posthog_test",
                        "kind": "Subscription Count",
                    },
                    "action": {
                        "days": ALL_MONTHS_FAKEDATETIMES,
                        "id": "Subscription Count | stripe.posthog_test",
                        "name": "Subscription Count | stripe.posthog_test",
                    },
                },
                {
                    "label": "New Subscription Count | stripe.posthog_test",
                    "days": ALL_MONTHS_DAYS,
                    "labels": ALL_MONTHS_LABELS,
                    "data": [0, 0, 3, 3, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
                    "breakdown": {
                        "property": "stripe.posthog_test",
                        "kind": "New Subscription Count",
                    },
                    "action": {
                        "days": ALL_MONTHS_FAKEDATETIMES,
                        "id": "New Subscription Count | stripe.posthog_test",
                        "name": "New Subscription Count | stripe.posthog_test",
                    },
                },
                {
                    "label": "Churned Subscription Count | stripe.posthog_test",
                    "days": ALL_MONTHS_DAYS,
                    "labels": ALL_MONTHS_LABELS,
                    "data": [0, 0, 0, 0, 0, 0, 0, 3, 1, 0, 0, 0, 0, 0, 0, 2, 0, 0, 0],
                    "breakdown": {
                        "property": "stripe.posthog_test",
                        "kind": "Churned Subscription Count",
                    },
                    "action": {
                        "days": ALL_MONTHS_FAKEDATETIMES,
                        "id": "Churned Subscription Count | stripe.posthog_test",
                        "name": "Churned Subscription Count | stripe.posthog_test",
                    },
                },
                {
                    "label": "Customer Count | stripe.posthog_test",
                    "days": ALL_MONTHS_DAYS,
                    "labels": ALL_MONTHS_LABELS,
                    "data": [0, 0, 3, 6, 6, 6, 6, 3, 2, 2, 2, 2, 2, 2, 2, 0, 0, 0, 0],
                    "breakdown": {
                        "property": "stripe.posthog_test",
                        "kind": "Customer Count",
                    },
                    "action": {
                        "days": ALL_MONTHS_FAKEDATETIMES,
                        "id": "Customer Count | stripe.posthog_test",
                        "name": "Customer Count | stripe.posthog_test",
                    },
                },
                {
                    "label": "New Customer Count | stripe.posthog_test",
                    "days": ALL_MONTHS_DAYS,
                    "labels": ALL_MONTHS_LABELS,
                    "data": [0, 0, 3, 3, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
                    "breakdown": {
                        "property": "stripe.posthog_test",
                        "kind": "New Customer Count",
                    },
                    "action": {
                        "days": ALL_MONTHS_FAKEDATETIMES,
                        "id": "New Customer Count | stripe.posthog_test",
                        "name": "New Customer Count | stripe.posthog_test",
                    },
                },
                {
                    "label": "Churned Customer Count | stripe.posthog_test",
                    "days": ALL_MONTHS_DAYS,
                    "labels": ALL_MONTHS_LABELS,
                    "data": [0, 0, 0, 0, 0, 0, 0, 3, 1, 0, 0, 0, 0, 0, 0, 2, 0, 0, 0],
                    "breakdown": {
                        "property": "stripe.posthog_test",
                        "kind": "Churned Customer Count",
                    },
                    "action": {
                        "days": ALL_MONTHS_FAKEDATETIMES,
                        "id": "Churned Customer Count | stripe.posthog_test",
                        "name": "Churned Customer Count | stripe.posthog_test",
                    },
                },
                {
                    "label": "ARPU | stripe.posthog_test",
                    "days": ALL_MONTHS_DAYS,
                    "labels": ALL_MONTHS_LABELS,
                    "data": [
                        0,
                        0,
                        Decimal("212.147447111"),
                        Decimal("277.3609785555"),
                        Decimal("337.8639052221"),
                        Decimal("382.9727768888"),
                        Decimal("268.3938127317"),
                        Decimal("6.8150087777"),
                        Decimal("10.2225131665"),
                        Decimal("10.2225131665"),
                        Decimal("10.2225131665"),
                        Decimal("10.2225131665"),
                        Decimal("10.2225131665"),
                        Decimal("10.2225131665"),
                        0,
                        0,
                        0,
                        0,
                        0,
                    ],
                    "breakdown": {
                        "property": "stripe.posthog_test",
                        "kind": "ARPU",
                    },
                    "action": {
                        "days": ALL_MONTHS_FAKEDATETIMES,
                        "id": "ARPU | stripe.posthog_test",
                        "name": "ARPU | stripe.posthog_test",
                    },
                },
                {
                    "label": "LTV | stripe.posthog_test",
                    "days": ALL_MONTHS_DAYS,
                    "labels": ALL_MONTHS_LABELS,
                    "data": [
                        0,
                        0,
                        None,
                        None,
                        None,
                        None,
                        None,
                        Decimal("6.8150087777"),
                        Decimal("20.445026333"),
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                        0,
                        0,
                        0,
                        0,
                    ],
                    "breakdown": {
                        "property": "stripe.posthog_test",
                        "kind": "LTV",
                    },
                    "action": {
                        "days": ALL_MONTHS_FAKEDATETIMES,
                        "id": "LTV | stripe.posthog_test",
                        "name": "LTV | stripe.posthog_test",
                    },
                },
            ],
        )

        # Assert that `previous_subscription_count` + `new_subscription_count` - `churned_subscription_count` = `subscription_count`
        for subscription_count, prev_subscription_count, new_subscription_count, churned_subscription_count in zip(
            results[0]["data"][1:],
            results[0]["data"][:-1],
            results[1]["data"][1:],
            results[2]["data"][1:],
        ):
            self.assertEqual(
                subscription_count, prev_subscription_count + new_subscription_count - churned_subscription_count
            )

        # Same for customer count
        for customer_count, prev_customer_count, new_customer_count, churned_customer_count in zip(
            results[3]["data"][1:],
            results[3]["data"][:-1],
            results[4]["data"][1:],
            results[5]["data"][1:],
        ):
            self.assertEqual(customer_count, prev_customer_count + new_customer_count - churned_customer_count)

    def test_with_data_and_date_range(self):
        results = self._run_revenue_analytics_metrics_query(
            date_range=DateRange(date_from="2025-04-01", date_to="2025-07-01")
        ).results

        days = ["2025-04-01", "2025-05-01", "2025-06-01", "2025-07-01"]
        labels = ["Apr 2025", "May 2025", "Jun 2025", "Jul 2025"]
        action_days = [ANY] * 4

        self.assertEqual(
            results,
            [
                {
                    "label": "Subscription Count | stripe.posthog_test",
                    "days": days,
                    "labels": labels,
                    "data": [6, 6, 3, 2],
                    "breakdown": {
                        "property": "stripe.posthog_test",
                        "kind": "Subscription Count",
                    },
                    "action": {
                        "days": action_days,
                        "id": "Subscription Count | stripe.posthog_test",
                        "name": "Subscription Count | stripe.posthog_test",
                    },
                },
                {
                    "label": "New Subscription Count | stripe.posthog_test",
                    "days": days,
                    "labels": labels,
                    "data": [0, 0, 0, 0],
                    "breakdown": {
                        "property": "stripe.posthog_test",
                        "kind": "New Subscription Count",
                    },
                    "action": {
                        "days": action_days,
                        "id": "New Subscription Count | stripe.posthog_test",
                        "name": "New Subscription Count | stripe.posthog_test",
                    },
                },
                {
                    "label": "Churned Subscription Count | stripe.posthog_test",
                    "days": days,
                    "labels": labels,
                    "data": [0, 0, 3, 1],
                    "breakdown": {
                        "property": "stripe.posthog_test",
                        "kind": "Churned Subscription Count",
                    },
                    "action": {
                        "days": action_days,
                        "id": "Churned Subscription Count | stripe.posthog_test",
                        "name": "Churned Subscription Count | stripe.posthog_test",
                    },
                },
                {
                    "label": "Customer Count | stripe.posthog_test",
                    "days": days,
                    "labels": labels,
                    "data": [6, 6, 3, 2],
                    "breakdown": {
                        "property": "stripe.posthog_test",
                        "kind": "Customer Count",
                    },
                    "action": {
                        "days": action_days,
                        "id": "Customer Count | stripe.posthog_test",
                        "name": "Customer Count | stripe.posthog_test",
                    },
                },
                {
                    "label": "New Customer Count | stripe.posthog_test",
                    "days": days,
                    "labels": labels,
                    "data": [0, 0, 0, 0],
                    "breakdown": {
                        "property": "stripe.posthog_test",
                        "kind": "New Customer Count",
                    },
                    "action": {
                        "days": action_days,
                        "id": "New Customer Count | stripe.posthog_test",
                        "name": "New Customer Count | stripe.posthog_test",
                    },
                },
                {
                    "label": "Churned Customer Count | stripe.posthog_test",
                    "days": days,
                    "labels": labels,
                    "data": [0, 0, 3, 1],
                    "breakdown": {
                        "property": "stripe.posthog_test",
                        "kind": "Churned Customer Count",
                    },
                    "action": {
                        "days": action_days,
                        "id": "Churned Customer Count | stripe.posthog_test",
                        "name": "Churned Customer Count | stripe.posthog_test",
                    },
                },
                {
                    "label": "ARPU | stripe.posthog_test",
                    "days": days,
                    "labels": labels,
                    "data": [
                        Decimal("382.9727768888"),
                        Decimal("268.3938127317"),
                        Decimal("6.8150087777"),
                        Decimal("10.2225131665"),
                    ],
                    "breakdown": {
                        "property": "stripe.posthog_test",
                        "kind": "ARPU",
                    },
                    "action": {
                        "days": action_days,
                        "id": "ARPU | stripe.posthog_test",
                        "name": "ARPU | stripe.posthog_test",
                    },
                },
                {
                    "label": "LTV | stripe.posthog_test",
                    "days": days,
                    "labels": labels,
                    "data": [None, None, Decimal("6.8150087777"), Decimal("20.445026333")],
                    "breakdown": {
                        "property": "stripe.posthog_test",
                        "kind": "LTV",
                    },
                    "action": {
                        "days": action_days,
                        "id": "LTV | stripe.posthog_test",
                        "name": "LTV | stripe.posthog_test",
                    },
                },
            ],
        )

    def test_with_empty_date_range(self):
        results = self._run_revenue_analytics_metrics_query(
            date_range=DateRange(date_from="2024-06-01", date_to="2024-06-30")
        ).results

        days = ["2024-06-01"]
        labels = ["Jun 2024"]
        action_days = [ANY]

        # Restricted to the date range
        self.assertEqual(
            results,
            [
                {
                    "label": "Subscription Count | stripe.posthog_test",
                    "days": days,
                    "labels": labels,
                    "data": [0],
                    "breakdown": {
                        "property": "stripe.posthog_test",
                        "kind": "Subscription Count",
                    },
                    "action": {
                        "days": action_days,
                        "id": "Subscription Count | stripe.posthog_test",
                        "name": "Subscription Count | stripe.posthog_test",
                    },
                },
                {
                    "label": "New Subscription Count | stripe.posthog_test",
                    "days": days,
                    "labels": labels,
                    "data": [0],
                    "breakdown": {
                        "property": "stripe.posthog_test",
                        "kind": "New Subscription Count",
                    },
                    "action": {
                        "days": action_days,
                        "id": "New Subscription Count | stripe.posthog_test",
                        "name": "New Subscription Count | stripe.posthog_test",
                    },
                },
                {
                    "label": "Churned Subscription Count | stripe.posthog_test",
                    "days": days,
                    "labels": labels,
                    "data": [0],
                    "breakdown": {
                        "property": "stripe.posthog_test",
                        "kind": "Churned Subscription Count",
                    },
                    "action": {
                        "days": action_days,
                        "id": "Churned Subscription Count | stripe.posthog_test",
                        "name": "Churned Subscription Count | stripe.posthog_test",
                    },
                },
                {
                    "label": "Customer Count | stripe.posthog_test",
                    "days": days,
                    "labels": labels,
                    "data": [0],
                    "breakdown": {
                        "property": "stripe.posthog_test",
                        "kind": "Customer Count",
                    },
                    "action": {
                        "days": action_days,
                        "id": "Customer Count | stripe.posthog_test",
                        "name": "Customer Count | stripe.posthog_test",
                    },
                },
                {
                    "label": "New Customer Count | stripe.posthog_test",
                    "days": days,
                    "labels": labels,
                    "data": [0],
                    "breakdown": {
                        "property": "stripe.posthog_test",
                        "kind": "New Customer Count",
                    },
                    "action": {
                        "days": action_days,
                        "id": "New Customer Count | stripe.posthog_test",
                        "name": "New Customer Count | stripe.posthog_test",
                    },
                },
                {
                    "label": "Churned Customer Count | stripe.posthog_test",
                    "days": days,
                    "labels": labels,
                    "data": [0],
                    "breakdown": {
                        "property": "stripe.posthog_test",
                        "kind": "Churned Customer Count",
                    },
                    "action": {
                        "days": action_days,
                        "id": "Churned Customer Count | stripe.posthog_test",
                        "name": "Churned Customer Count | stripe.posthog_test",
                    },
                },
                {
                    "label": "ARPU | stripe.posthog_test",
                    "days": days,
                    "labels": labels,
                    "data": [0],
                    "breakdown": {
                        "property": "stripe.posthog_test",
                        "kind": "ARPU",
                    },
                    "action": {
                        "days": action_days,
                        "id": "ARPU | stripe.posthog_test",
                        "name": "ARPU | stripe.posthog_test",
                    },
                },
                {
                    "label": "LTV | stripe.posthog_test",
                    "days": days,
                    "labels": labels,
                    "data": [0],
                    "breakdown": {
                        "property": "stripe.posthog_test",
                        "kind": "LTV",
                    },
                    "action": {
                        "days": action_days,
                        "id": "LTV | stripe.posthog_test",
                        "name": "LTV | stripe.posthog_test",
                    },
                },
            ],
        )

    def test_with_data_and_product_grouping(self):
        results = self._run_revenue_analytics_metrics_query(
            breakdown=[RevenueAnalyticsBreakdown(property="revenue_analytics_product.name")]
        ).results

        self.assertEqual(len(results), 48)  # 6 Products * 8 insights = 48

        self.assertEqual(
            [(result["data"], result["label"]) for result in results],
            [
                ([0, 0, 1, 1, 1, 1, 1], "Subscription Count | stripe.posthog_test - Product A"),
                ([0, 0, 1, 0, 0, 0, 0], "New Subscription Count | stripe.posthog_test - Product A"),
                ([0, 0, 0, 0, 0, 0, 0], "Churned Subscription Count | stripe.posthog_test - Product A"),
                ([0, 0, 1, 1, 1, 1, 1], "Customer Count | stripe.posthog_test - Product A"),
                ([0, 0, 1, 0, 0, 0, 0], "New Customer Count | stripe.posthog_test - Product A"),
                ([0, 0, 0, 0, 0, 0, 0], "Churned Customer Count | stripe.posthog_test - Product A"),
                (
                    [
                        0,
                        0,
                        Decimal("4.1397346665"),
                        Decimal("4.1397346665"),
                        Decimal("219.4891346665"),
                        Decimal("4.1397346665"),
                        Decimal("22.9631447238"),
                    ],
                    "ARPU | stripe.posthog_test - Product A",
                ),
                ([0, 0, None, None, None, None, None], "LTV | stripe.posthog_test - Product A"),
                ([0, 0, 1, 1, 1, 1, 1], "Subscription Count | stripe.posthog_test - Product B"),
                ([0, 0, 1, 0, 0, 0, 0], "New Subscription Count | stripe.posthog_test - Product B"),
                ([0, 0, 0, 0, 0, 0, 0], "Churned Subscription Count | stripe.posthog_test - Product B"),
                ([0, 0, 1, 1, 1, 1, 1], "Customer Count | stripe.posthog_test - Product B"),
                ([0, 0, 1, 0, 0, 0, 0], "New Customer Count | stripe.posthog_test - Product B"),
                ([0, 0, 0, 0, 0, 0, 0], "Churned Customer Count | stripe.posthog_test - Product B"),
                (
                    [
                        0,
                        0,
                        Decimal("16.3052916666"),
                        Decimal("16.3052916666"),
                        Decimal("88.5931916666"),
                        Decimal("16.3052916666"),
                        Decimal("40.8052916666"),
                    ],
                    "ARPU | stripe.posthog_test - Product B",
                ),
                ([0, 0, None, None, None, None, None], "LTV | stripe.posthog_test - Product B"),
                ([0, 0, 1, 1, 1, 1, 1], "Subscription Count | stripe.posthog_test - Product C"),
                ([0, 0, 1, 0, 0, 0, 0], "New Subscription Count | stripe.posthog_test - Product C"),
                ([0, 0, 0, 0, 0, 0, 0], "Churned Subscription Count | stripe.posthog_test - Product C"),
                ([0, 0, 1, 1, 1, 1, 1], "Customer Count | stripe.posthog_test - Product C"),
                ([0, 0, 1, 0, 0, 0, 0], "New Customer Count | stripe.posthog_test - Product C"),
                ([0, 0, 0, 0, 0, 0, 0], "Churned Customer Count | stripe.posthog_test - Product C"),
                (
                    [
                        0,
                        0,
                        Decimal("615.997315"),
                        Decimal("615.997315"),
                        Decimal("691.377575"),
                        Decimal("691.377575"),
                        Decimal("1546.59444"),
                    ],
                    "ARPU | stripe.posthog_test - Product C",
                ),
                ([0, 0, None, None, None, None, None], "LTV | stripe.posthog_test - Product C"),
                ([0, 0, 0, 1, 1, 1, 1], "Subscription Count | stripe.posthog_test - Product D"),
                ([0, 0, 0, 1, 0, 0, 0], "New Subscription Count | stripe.posthog_test - Product D"),
                ([0, 0, 0, 0, 0, 0, 0], "Churned Subscription Count | stripe.posthog_test - Product D"),
                ([0, 0, 0, 1, 1, 1, 1], "Customer Count | stripe.posthog_test - Product D"),
                ([0, 0, 0, 1, 0, 0, 0], "New Customer Count | stripe.posthog_test - Product D"),
                ([0, 0, 0, 0, 0, 0, 0], "Churned Customer Count | stripe.posthog_test - Product D"),
                (
                    [0, 0, 0, Decimal("85.47825"), Decimal("85.47825"), Decimal("83.16695"), 0],
                    "ARPU | stripe.posthog_test - Product D",
                ),
                ([0, 0, 0, None, None, None, None], "LTV | stripe.posthog_test - Product D"),
                ([0, 0, 0, 1, 1, 1, 1], "Subscription Count | stripe.posthog_test - Product E"),
                ([0, 0, 0, 1, 0, 0, 0], "New Subscription Count | stripe.posthog_test - Product E"),
                ([0, 0, 0, 0, 0, 0, 0], "Churned Subscription Count | stripe.posthog_test - Product E"),
                ([0, 0, 0, 1, 1, 1, 1], "Customer Count | stripe.posthog_test - Product E"),
                ([0, 0, 0, 1, 0, 0, 0], "New Customer Count | stripe.posthog_test - Product E"),
                ([0, 0, 0, 0, 0, 0, 0], "Churned Customer Count | stripe.posthog_test - Product E"),
                (
                    [0, 0, 0, Decimal("273.57025"), Decimal("273.57025"), Decimal("43.82703"), 0],
                    "ARPU | stripe.posthog_test - Product E",
                ),
                ([0, 0, 0, None, None, None, None], "LTV | stripe.posthog_test - Product E"),
                ([0, 0, 0, 1, 1, 1, 1], "Subscription Count | stripe.posthog_test - Product F"),
                ([0, 0, 0, 1, 0, 0, 0], "New Subscription Count | stripe.posthog_test - Product F"),
                ([0, 0, 0, 0, 0, 0, 0], "Churned Subscription Count | stripe.posthog_test - Product F"),
                ([0, 0, 0, 1, 1, 1, 1], "Customer Count | stripe.posthog_test - Product F"),
                ([0, 0, 0, 1, 0, 0, 0], "New Customer Count | stripe.posthog_test - Product F"),
                ([0, 0, 0, 0, 0, 0, 0], "Churned Customer Count | stripe.posthog_test - Product F"),
                (
                    [0, 0, 0, Decimal("668.67503"), Decimal("668.67503"), Decimal("1459.02008"), 0],
                    "ARPU | stripe.posthog_test - Product F",
                ),
                ([0, 0, 0, None, None, None, None], "LTV | stripe.posthog_test - Product F"),
            ],
        )

    def test_with_product_filter(self):
        expected_data = [
            [0, 0, 1, 1, 1, 1, 1],  # Subscription Count
            [0, 0, 1, 0, 0, 0, 0],  # New Subscription Count
            [0, 0, 0, 0, 0, 0, 0],  # Churned Subscription Count
            [0, 0, 1, 1, 1, 1, 1],  # Customer Count
            [0, 0, 1, 0, 0, 0, 0],  # New Customer Count
            [0, 0, 0, 0, 0, 0, 0],  # Churned Customer Count
            [
                0,
                0,
                Decimal("615.997315"),
                Decimal("615.997315"),
                Decimal("691.377575"),
                Decimal("691.377575"),
                Decimal("1546.59444"),
            ],  # ARPU
            [0, 0, None, None, None, None, None],  # LTV
        ]

        results = self._run_revenue_analytics_metrics_query(
            properties=[
                RevenueAnalyticsPropertyFilter(
                    key="revenue_analytics_product.name",
                    operator=PropertyOperator.EXACT,
                    value=["Product C"],  # Equivalent to `prod_c` but we're querying by name
                ),
            ]
        ).results

        self.assertEqual(len(results), 8)
        self.assertEqual([result["data"] for result in results], expected_data)

        # When grouping results should be exactly the same, just the label changes
        results = self._run_revenue_analytics_metrics_query(
            breakdown=[RevenueAnalyticsBreakdown(property="revenue_analytics_product.name")],
            properties=[
                RevenueAnalyticsPropertyFilter(
                    key="revenue_analytics_product.name",
                    operator=PropertyOperator.EXACT,
                    value=["Product C"],  # Equivalent to `prod_c` but we're querying by name
                ),
            ],
        ).results

        self.assertEqual(len(results), 8)
        self.assertEqual([result["data"] for result in results], expected_data)

        labels = [result["label"] for result in results]
        self.assertIn("Subscription Count | stripe.posthog_test - Product C", labels)

    def test_with_multiple_products_filter(self):
        results = self._run_revenue_analytics_metrics_query(
            properties=[
                RevenueAnalyticsPropertyFilter(
                    key="revenue_analytics_product.name",
                    operator=PropertyOperator.EXACT,
                    value=["Product A", "Product C"],
                ),
            ]
        ).results

        self.assertEqual(len(results), 8)
        self.assertEqual(
            [result["data"] for result in results],
            [
                [0, 0, 2, 2, 2, 2, 2],  # Subscription Count
                [0, 0, 2, 0, 0, 0, 0],  # New Subscription Count
                [0, 0, 0, 0, 0, 0, 0],  # Churned Subscription Count
                [0, 0, 2, 2, 2, 2, 2],  # Customer Count
                [0, 0, 2, 0, 0, 0, 0],  # New Customer Count
                [0, 0, 0, 0, 0, 0, 0],  # Churned Customer Count
                [
                    0,
                    0,
                    Decimal("310.0685248332"),
                    Decimal("310.0685248332"),
                    Decimal("455.4333548332"),
                    Decimal("347.7586548332"),
                    Decimal("784.7787923619"),
                ],  # ARPU
                [0, 0, None, None, None, None, None],  # LTV
            ],
        )

    def test_with_country_filter(self):
        results = self._run_revenue_analytics_metrics_query(
            properties=[
                RevenueAnalyticsPropertyFilter(
                    key="revenue_analytics_customer.country",
                    operator=PropertyOperator.EXACT,
                    value=["US"],
                )
            ]
        ).results

        self.assertEqual(len(results), 8)
        self.assertEqual(
            [result["data"] for result in results],
            [
                [0, 0, 2, 2, 2, 2, 2],  # Subscription Count
                [0, 0, 2, 0, 0, 0, 0],  # New Subscription Count
                [0, 0, 0, 0, 0, 0, 0],  # Churned Subscription Count
                [0, 0, 2, 2, 2, 2, 2],  # Customer Count
                [0, 0, 2, 0, 0, 0, 0],  # New Customer Count
                [0, 0, 0, 0, 0, 0, 0],  # Churned Customer Count
                [
                    0,
                    0,
                    Decimal("10.2225131665"),
                    Decimal("10.2225131665"),
                    Decimal("154.0411631665"),
                    Decimal("10.2225131665"),
                    Decimal("31.8842181952"),
                ],  # ARPU
                [0, 0, None, None, None, None, None],  # LTV
            ],
        )

    def test_with_events_data(self):
        s1 = str(uuid7("2024-12-02"))
        s2 = str(uuid7("2025-01-03"))
        s3 = str(uuid7("2025-02-04"))
        s4 = str(uuid7("2025-03-06"))
        self._create_purchase_events(
            [
                (
                    "p1",
                    [
                        ("2024-12-02", s1, 42, "USD", {"subscription": "sub1"}),
                        ("2024-12-02", s1, 35456, "ARS", {"subscription": "sub2"}),
                    ],
                ),
                (
                    "p2",
                    [
                        ("2025-01-01", s2, 43, "BRL", {"subscription": "sub3"}),
                        ("2025-02-04", s3, 87, "BRL", {"subscription": "sub3"}),
                        ("2025-03-06", s4, 126, "BRL", {"subscription": "sub3"}),
                        (
                            "2025-03-06",
                            s4,
                            385,
                            "BRL",
                            {"subscription": 47},
                        ),  # Works with numerical subscription_properties
                    ],
                ),  # 3 events, 1 customer
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

        results = self._run_revenue_analytics_metrics_query(
            properties=[
                RevenueAnalyticsPropertyFilter(
                    key="source_label",
                    operator=PropertyOperator.EXACT,
                    value=["revenue_analytics.events.purchase"],
                )
            ],
        ).results

        self.assertEqual(len(results), 8)

        self.assertEqual(
            [result["data"] for result in results],
            [
                [0, 1, 1, 1, 2, 0, 0],  # Subscription Count
                [0, 1, 1, 0, 1, 0, 0],  # New Subscription Count
                [0, 0, 1, 0, 0, 2, 0],  # Churned Subscription Count
                [0, 1, 1, 1, 1, 0, 0],  # Customer Count
                [0, 1, 1, 0, 0, 0, 0],  # New Customer Count
                [0, 0, 1, 0, 0, 1, 0],  # Churned Customer Count
                [
                    0,
                    Decimal("33.0414"),
                    Decimal("5.5629321819"),
                    Decimal("11.2552348796"),
                    Decimal("66.1083336037"),
                    0,
                    0,
                ],  # ARPU
                [0, None, Decimal("5.5629321819"), None, None, 0, 0],  # LTV
            ],
        )

        # Assert that `previous_subscription_count` + `new_subscription_count` - `churned_subscription_count` = `subscription_count`
        for subscription_count, prev_subscription_count, new_subscription_count, churned_subscription_count in zip(
            results[0]["data"][1:],
            results[0]["data"][:-1],
            results[1]["data"][1:],
            results[2]["data"][1:],
        ):
            self.assertEqual(
                subscription_count, prev_subscription_count + new_subscription_count - churned_subscription_count
            )

        # Same for customer count
        for customer_count, prev_customer_count, new_customer_count, churned_customer_count in zip(
            results[3]["data"][1:],
            results[3]["data"][:-1],
            results[4]["data"][1:],
            results[5]["data"][1:],
        ):
            self.assertEqual(customer_count, prev_customer_count + new_customer_count - churned_customer_count)

        # Then, update the team to use the after_dropoff_period subscriptionDropoffMode
        event_item = REVENUE_ANALYTICS_CONFIG_SAMPLE_EVENT.model_copy(
            update={"subscriptionDropoffMode": SubscriptionDropoffMode.AFTER_DROPOFF_PERIOD}
        )
        self.team.revenue_analytics_config.events = [event_item]
        self.team.revenue_analytics_config.save()

        results = self._run_revenue_analytics_metrics_query(
            properties=[
                RevenueAnalyticsPropertyFilter(
                    key="source_label",
                    operator=PropertyOperator.EXACT,
                    value=["revenue_analytics.events.purchase"],
                )
            ],
        ).results

        self.assertEqual(len(results), 8)
        self.assertEqual(
            [result["data"] for result in results],
            [
                [0, 1, 2, 1, 2, 2, 0],  # Subscription Count
                [0, 1, 1, 0, 1, 0, 0],  # New Subscription Count
                [0, 0, 0, 1, 0, 0, 2],  # Churned Subscription Count
                [0, 1, 2, 1, 1, 1, 0],  # Customer Count
                [0, 1, 1, 0, 0, 0, 0],  # New Customer Count
                [0, 0, 0, 1, 0, 0, 1],  # Churned Customer Count
                [
                    0,
                    Decimal("33.0414"),
                    Decimal("2.7814660909"),
                    Decimal("11.2552348796"),
                    Decimal("66.1083336037"),
                    0,
                    0,
                ],  # ARPU
                [0, None, None, Decimal("11.2552348796"), None, None, 0],  # LTV
            ],
        )
