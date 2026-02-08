from decimal import Decimal
from pathlib import Path

from freezegun import freeze_time
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    QueryMatchingTest,
    _create_event,
    _create_person,
    snapshot_clickhouse_queries,
)
from unittest.mock import ANY

from posthog.schema import CurrencyCode, HogQLQueryModifiers, HogQLQueryResponse

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.models.utils import uuid7
from posthog.temporal.data_imports.sources.stripe.constants import (
    CHARGE_RESOURCE_NAME as STRIPE_CHARGE_RESOURCE_NAME,
    INVOICE_RESOURCE_NAME as STRIPE_INVOICE_RESOURCE_NAME,
    SUBSCRIPTION_RESOURCE_NAME as STRIPE_SUBSCRIPTION_RESOURCE_NAME,
)

from products.data_warehouse.backend.models.external_data_schema import ExternalDataSchema
from products.data_warehouse.backend.test.utils import create_data_warehouse_table_from_csv
from products.revenue_analytics.backend.hogql_queries.test.data.structure import (
    REVENUE_ANALYTICS_CONFIG_SAMPLE_EVENT,
    STRIPE_CHARGE_COLUMNS,
    STRIPE_INVOICE_COLUMNS,
    STRIPE_SUBSCRIPTION_COLUMNS,
)
from products.revenue_analytics.backend.views.schemas.mrr import SCHEMA as MRR_SCHEMA

INVOICES_TEST_BUCKET = "test_storage_bucket-posthog.revenue_analytics.mrr_views.stripe_invoices"
CHARGES_TEST_BUCKET = "test_storage_bucket-posthog.revenue_analytics.mrr_views.stripe_charges"
SUBSCRIPTIONS_TEST_BUCKET = "test_storage_bucket-posthog.revenue_analytics.mrr_views.stripe_subscriptions"


@snapshot_clickhouse_queries
class TestMRRViewsE2E(ClickhouseTestMixin, QueryMatchingTest, APIBaseTest):
    """E2E tests for MRR views that execute actual queries and assert on output values."""

    QUERY_TIMESTAMP = "2025-05-31"

    def setUp(self):
        super().setUp()
        self._setup_stripe_data()

    def _setup_stripe_data(self):
        data_dir = Path(__file__).parent.parent.parent / "hogql_queries" / "test" / "data"

        self.invoices_table, self.source, self.credential, _, self.invoices_cleanup = (
            create_data_warehouse_table_from_csv(
                data_dir / "stripe_invoices.csv",
                "stripe_invoice",
                STRIPE_INVOICE_COLUMNS,
                INVOICES_TEST_BUCKET,
                self.team,
            )
        )

        self.charges_table, _, _, _, self.charges_cleanup = create_data_warehouse_table_from_csv(
            data_dir / "stripe_charges.csv",
            "stripe_charge",
            STRIPE_CHARGE_COLUMNS,
            CHARGES_TEST_BUCKET,
            self.team,
            source=self.source,
            credential=self.credential,
        )

        self.subscriptions_table, _, _, _, self.subscriptions_cleanup = create_data_warehouse_table_from_csv(
            data_dir / "stripe_subscriptions.csv",
            "stripe_subscription",
            STRIPE_SUBSCRIPTION_COLUMNS,
            SUBSCRIPTIONS_TEST_BUCKET,
            self.team,
            source=self.source,
            credential=self.credential,
        )

        ExternalDataSchema.objects.create(
            team=self.team,
            name=STRIPE_INVOICE_RESOURCE_NAME,
            source=self.source,
            table=self.invoices_table,
            should_sync=True,
            last_synced_at="2024-01-01",
        )
        ExternalDataSchema.objects.create(
            team=self.team,
            name=STRIPE_CHARGE_RESOURCE_NAME,
            source=self.source,
            table=self.charges_table,
            should_sync=True,
            last_synced_at="2024-01-01",
        )
        ExternalDataSchema.objects.create(
            team=self.team,
            name=STRIPE_SUBSCRIPTION_RESOURCE_NAME,
            source=self.source,
            table=self.subscriptions_table,
            should_sync=True,
            last_synced_at="2024-01-01",
        )

        self.team.base_currency = CurrencyCode.GBP.value
        self.team.save()

    def tearDown(self):
        self.invoices_cleanup()
        self.charges_cleanup()
        self.subscriptions_cleanup()
        super().tearDown()

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

    def _execute_query(self, query: ast.SelectQuery) -> HogQLQueryResponse:
        with freeze_time(self.QUERY_TIMESTAMP):
            return execute_hogql_query(
                query=query,
                team=self.team,
                modifiers=HogQLQueryModifiers(formatCsvAllowDoubleQuotes=True),
            )

    def test_no_data_when_no_stripe_source_data_warehouse_tables(self):
        self.invoices_table.delete()
        self.charges_table.delete()
        self.subscriptions_table.delete()

        query = ast.SelectQuery(
            select=[ast.Alias(alias="count", expr=ast.Call(name="count", args=[]))],
            select_from=ast.JoinExpr(table=ast.Field(chain=[f"stripe.posthog_test.{MRR_SCHEMA.source_suffix}"])),
        )

        response = self._execute_query(query)
        results = response.results
        self.assertEqual(results[0][0], 0)

    def test_no_data_when_no_events(self):
        self.team.revenue_analytics_config.events = [
            REVENUE_ANALYTICS_CONFIG_SAMPLE_EVENT.model_copy(
                update={
                    "subscriptionDropoffMode": "after_dropoff_period",  # More reasonable default for tests
                }
            )
        ]
        self.team.revenue_analytics_config.save()

        query = ast.SelectQuery(
            select=[ast.Alias(alias="count", expr=ast.Call(name="count", args=[]))],
            select_from=ast.JoinExpr(
                table=ast.Field(chain=[f"revenue_analytics.events.purchase.{MRR_SCHEMA.events_suffix}"])
            ),
        )

        response = self._execute_query(query)
        results = response.results
        self.assertEqual(results[0][0], 0)

    def test_query_output_data_warehouse_tables(self):
        query = ast.SelectQuery(
            select=[ast.Field(chain=["*"])],
            select_from=ast.JoinExpr(table=ast.Field(chain=[f"stripe.posthog_test.{MRR_SCHEMA.source_suffix}"])),
        )

        response = self._execute_query(query)

        self.assertEqual(len(response.results), 6)
        self.assertEqual(
            response.results,
            [
                ("stripe.posthog_test", "cus_1", "sub_1", Decimal("22.9631447238")),
                ("stripe.posthog_test", "cus_2", "sub_2", Decimal("40.8052916666")),
                ("stripe.posthog_test", "cus_3", "sub_3", Decimal("1546.59444")),
                ("stripe.posthog_test", "cus_4", "sub_4", Decimal("0")),
                ("stripe.posthog_test", "cus_5", "sub_5", Decimal("0")),
                ("stripe.posthog_test", "cus_6", "sub_6", Decimal("0")),
            ],
        )

    def test_query_output_events(self):
        self.team.revenue_analytics_config.events = [
            REVENUE_ANALYTICS_CONFIG_SAMPLE_EVENT.model_copy(
                update={
                    "subscriptionDropoffMode": "after_dropoff_period",  # More reasonable default for tests
                }
            )
        ]
        self.team.revenue_analytics_config.save()

        s1 = str(uuid7("2025-04-25"))
        s2 = str(uuid7("2025-05-03"))
        s3 = str(uuid7("2025-05-05"))
        s4 = str(uuid7("2025-05-08"))
        self._create_purchase_events(
            [
                (
                    "p1",
                    [
                        ("2025-04-25", s1, 55, "USD", "", "", None),  # Subscriptionless event
                        ("2025-04-25", s1, 42, "USD", "Prod A", "coupon_x", "sub_1"),
                        ("2025-05-03", s2, 25, "USD", "Prod A", "", "sub_1"),  # Contraction
                    ],
                ),
                (
                    "p2",
                    [
                        ("2025-05-05", s3, 43, "BRL", "Prod B", "coupon_y", "sub_2"),
                        ("2025-03-08", s4, 286, "BRL", "Prod B", "", "sub_2"),  # Expansion
                    ],
                ),
            ]
        )

        query = ast.SelectQuery(
            select=[ast.Field(chain=["*"])],
            select_from=ast.JoinExpr(
                table=ast.Field(chain=[f"revenue_analytics.events.purchase.{MRR_SCHEMA.events_suffix}"])
            ),
        )

        response = self._execute_query(query)

        self.assertEqual(len(response.results), 2)
        self.assertEqual(
            response.results,
            [
                (
                    "revenue_analytics.events.purchase",
                    ANY,
                    "sub_1",
                    Decimal("19.925"),
                ),
                (
                    "revenue_analytics.events.purchase",
                    ANY,
                    "sub_2",
                    Decimal("5.5629321819"),
                ),
            ],
        )
