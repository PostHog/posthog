from freezegun import freeze_time
from pathlib import Path
from unittest.mock import ANY

from products.revenue_analytics.backend.hogql_queries.revenue_analytics_customer_count_query_runner import (
    RevenueAnalyticsCustomerCountQueryRunner,
)
from posthog.schema import (
    CurrencyCode,
    DateRange,
    PropertyOperator,
    RevenueAnalyticsCustomerCountQuery,
    RevenueAnalyticsCustomerCountQueryResponse,
    RevenueAnalyticsGroupBy,
    IntervalType,
    HogQLQueryModifiers,
    RevenueAnalyticsPropertyFilter,
)
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    snapshot_clickhouse_queries,
)
from posthog.warehouse.models import ExternalDataSchema

from posthog.temporal.data_imports.pipelines.stripe.constants import (
    SUBSCRIPTION_RESOURCE_NAME as STRIPE_SUBSCRIPTION_RESOURCE_NAME,
    PRODUCT_RESOURCE_NAME as STRIPE_PRODUCT_RESOURCE_NAME,
    CUSTOMER_RESOURCE_NAME as STRIPE_CUSTOMER_RESOURCE_NAME,
)
from posthog.warehouse.test.utils import create_data_warehouse_table_from_csv
from products.revenue_analytics.backend.hogql_queries.test.data.structure import (
    REVENUE_ANALYTICS_CONFIG_SAMPLE_EVENT,
    STRIPE_CUSTOMER_COLUMNS,
    STRIPE_PRODUCT_COLUMNS,
    STRIPE_SUBSCRIPTION_COLUMNS,
)

SUBSCRIPTIONS_TEST_BUCKET = "test_storage_bucket-posthog.revenue_analytics.insights_query_runner.stripe_subscriptions"
PRODUCTS_TEST_BUCKET = "test_storage_bucket-posthog.revenue_analytics.insights_query_runner.stripe_products"
CUSTOMERS_TEST_BUCKET = "test_storage_bucket-posthog.revenue_analytics.insights_query_runner.stripe_customers"

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
class TestRevenueAnalyticsCustomerCountQueryRunner(ClickhouseTestMixin, APIBaseTest):
    QUERY_TIMESTAMP = "2025-05-30"

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

        self.team.base_currency = CurrencyCode.GBP.value
        self.team.revenue_analytics_config.events = [REVENUE_ANALYTICS_CONFIG_SAMPLE_EVENT]
        self.team.revenue_analytics_config.save()
        self.team.save()

    def tearDown(self):
        self.subscriptions_cleanup_filesystem()
        self.products_cleanup_filesystem()
        self.customers_cleanup_filesystem()
        super().tearDown()

    def _run_revenue_analytics_customer_count_query(
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
            query = RevenueAnalyticsCustomerCountQuery(
                dateRange=date_range,
                interval=interval,
                groupBy=group_by,
                properties=properties,
                modifiers=HogQLQueryModifiers(formatCsvAllowDoubleQuotes=True),
            )

            runner = RevenueAnalyticsCustomerCountQueryRunner(
                team=self.team,
                query=query,
            )
            response = runner.calculate()

            RevenueAnalyticsCustomerCountQueryResponse.model_validate(response)
            return response

    def test_no_crash_when_no_data(self):
        self.subscriptions_table.delete()
        self.products_table.delete()
        self.customers_table.delete()
        results = self._run_revenue_analytics_customer_count_query().results

        self.assertEqual(results, [])

    def test_no_crash_when_no_source_is_selected(self):
        results = self._run_revenue_analytics_customer_count_query(
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
        results = self._run_revenue_analytics_customer_count_query(
            date_range=DateRange(date_from="2024-11-01", date_to="2026-01-01")
        ).results

        self.assertEqual(
            results,
            [
                {
                    "label": "Subscription Count | stripe.posthog_test",
                    "days": ALL_MONTHS_DAYS,
                    "labels": ALL_MONTHS_LABELS,
                    "data": [0, 0, 1, 2, 3, 4, 5, 6, 0, 0, 0, 0, 0, 0, 0],
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
                    "data": [0, 0, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0],
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
                    "data": [0, 0, 0, 0, 0, 0, 0, 6, 0, 0, 0, 0, 0, 0, 0],
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
                    "data": [0, 0, 1, 2, 3, 4, 5, 6, 0, 0, 0, 0, 0, 0, 0],
                    "action": {
                        "days": ALL_MONTHS_FAKEDATETIMES,
                        "id": "Customer Count | stripe.posthog_test",
                        "name": "Customer Count | stripe.posthog_test",
                    },
                },
            ],
        )

    def test_with_data_and_date_range(self):
        results = self._run_revenue_analytics_customer_count_query(
            date_range=DateRange(date_from="2025-02-01", date_to="2025-05-01")
        ).results

        days = ["2025-02-01", "2025-03-01", "2025-04-01", "2025-05-01"]
        labels = ["Feb 2025", "Mar 2025", "Apr 2025", "May 2025"]
        action_days = [ANY] * 4

        self.assertEqual(
            results,
            [
                {
                    "label": "Subscription Count | stripe.posthog_test",
                    "days": days,
                    "labels": labels,
                    "data": [2, 3, 4, 5],
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
                    "data": [1, 1, 1, 1],
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
                    "data": [0, 0, 0, 0],
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
                    "data": [2, 3, 4, 5],
                    "action": {
                        "days": action_days,
                        "id": "Customer Count | stripe.posthog_test",
                        "name": "Customer Count | stripe.posthog_test",
                    },
                },
            ],
        )

    def test_with_empty_date_range(self):
        results = self._run_revenue_analytics_customer_count_query(
            date_range=DateRange(date_from="2024-12-01", date_to="2024-12-31")
        ).results

        days = ["2024-12-01"]
        labels = ["Dec 2024"]
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
                    "action": {
                        "days": action_days,
                        "id": "Customer Count | stripe.posthog_test",
                        "name": "Customer Count | stripe.posthog_test",
                    },
                },
            ],
        )

    def test_with_data_and_product_grouping(self):
        results = self._run_revenue_analytics_customer_count_query(group_by=[RevenueAnalyticsGroupBy.PRODUCT]).results

        self.assertEqual(len(results), 24)  # 6 Products * 4 insights = 24
        self.assertEqual(
            [(result["data"], result["label"]) for result in results],
            [
                ([0, 0, 1, 1, 1, 1, 1], "Subscription Count | stripe.posthog_test - Product A"),
                ([0, 0, 1, 0, 0, 0, 0], "New Subscription Count | stripe.posthog_test - Product A"),
                ([0, 0, 0, 0, 0, 0, 0], "Churned Subscription Count | stripe.posthog_test - Product A"),
                ([0, 0, 1, 1, 1, 1, 1], "Customer Count | stripe.posthog_test - Product A"),
                ([0, 0, 0, 1, 1, 1, 1], "Subscription Count | stripe.posthog_test - Product B"),
                ([0, 0, 0, 1, 0, 0, 0], "New Subscription Count | stripe.posthog_test - Product B"),
                ([0, 0, 0, 0, 0, 0, 0], "Churned Subscription Count | stripe.posthog_test - Product B"),
                ([0, 0, 0, 1, 1, 1, 1], "Customer Count | stripe.posthog_test - Product B"),
                ([0, 0, 0, 0, 1, 1, 1], "Subscription Count | stripe.posthog_test - Product C"),
                ([0, 0, 0, 0, 1, 0, 0], "New Subscription Count | stripe.posthog_test - Product C"),
                ([0, 0, 0, 0, 0, 0, 0], "Churned Subscription Count | stripe.posthog_test - Product C"),
                ([0, 0, 0, 0, 1, 1, 1], "Customer Count | stripe.posthog_test - Product C"),
                ([0, 0, 0, 0, 0, 1, 1], "Subscription Count | stripe.posthog_test - Product D"),
                ([0, 0, 0, 0, 0, 1, 0], "New Subscription Count | stripe.posthog_test - Product D"),
                ([0, 0, 0, 0, 0, 0, 0], "Churned Subscription Count | stripe.posthog_test - Product D"),
                ([0, 0, 0, 0, 0, 1, 1], "Customer Count | stripe.posthog_test - Product D"),
                ([0, 0, 0, 0, 0, 0, 1], "Subscription Count | stripe.posthog_test - Product E"),
                ([0, 0, 0, 0, 0, 0, 1], "New Subscription Count | stripe.posthog_test - Product E"),
                ([0, 0, 0, 0, 0, 0, 0], "Churned Subscription Count | stripe.posthog_test - Product E"),
                ([0, 0, 0, 0, 0, 0, 1], "Customer Count | stripe.posthog_test - Product E"),
                ([0, 0, 0, 0, 0, 0, 0], "Subscription Count | stripe.posthog_test - Product F"),
                ([0, 0, 0, 0, 0, 0, 0], "New Subscription Count | stripe.posthog_test - Product F"),
                ([0, 0, 0, 0, 0, 0, 0], "Churned Subscription Count | stripe.posthog_test - Product F"),
                ([0, 0, 0, 0, 0, 0, 0], "Customer Count | stripe.posthog_test - Product F"),
            ],
        )

    def test_with_product_filter(self):
        expected_data = [[0, 0, 0, 0, 1, 1, 1], [0, 0, 0, 0, 1, 0, 0], [0, 0, 0, 0, 0, 0, 0], [0, 0, 0, 0, 1, 1, 1]]

        results = self._run_revenue_analytics_customer_count_query(
            properties=[
                RevenueAnalyticsPropertyFilter(
                    key="product",
                    operator=PropertyOperator.EXACT,
                    value=["Product C"],  # Equivalent to `prod_c` but we're querying by name
                )
            ]
        ).results

        self.assertEqual(len(results), 4)
        self.assertEqual([result["data"] for result in results], expected_data)

        # When grouping results should be exactly the same, just the label changes
        results = self._run_revenue_analytics_customer_count_query(
            group_by=[RevenueAnalyticsGroupBy.PRODUCT],
            properties=[
                RevenueAnalyticsPropertyFilter(
                    key="product",
                    operator=PropertyOperator.EXACT,
                    value=["Product C"],  # Equivalent to `prod_c` but we're querying by name
                )
            ],
        ).results

        self.assertEqual(len(results), 4)
        self.assertEqual([result["data"] for result in results], expected_data)

        labels = [result["label"] for result in results]
        self.assertIn("Subscription Count | stripe.posthog_test - Product C", labels)

    def test_with_country_filter(self):
        results = self._run_revenue_analytics_customer_count_query(
            properties=[
                RevenueAnalyticsPropertyFilter(
                    key="country",
                    operator=PropertyOperator.EXACT,
                    value=["US"],
                )
            ]
        ).results

        self.assertEqual(len(results), 4)
        self.assertEqual(
            [result["data"] for result in results],
            [[0, 0, 1, 2, 2, 2, 2], [0, 0, 1, 1, 0, 0, 0], [0, 0, 0, 0, 0, 0, 0], [0, 0, 1, 2, 2, 2, 2]],
        )
