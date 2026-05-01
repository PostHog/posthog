import tempfile
from pathlib import Path

from freezegun import freeze_time
from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from posthog.schema import (
    CurrencyCode,
    DateRange,
    HogQLQueryModifiers,
    RevenueAnalyticsTopCustomersGroupBy,
    RevenueAnalyticsTopCustomersQuery,
    RevenueAnalyticsTopCustomersQueryResponse,
)

from posthog.temporal.data_imports.sources.stripe.constants import (
    CHARGE_RESOURCE_NAME as STRIPE_CHARGE_RESOURCE_NAME,
    CUSTOMER_RESOURCE_NAME as STRIPE_CUSTOMER_RESOURCE_NAME,
    INVOICE_RESOURCE_NAME as STRIPE_INVOICE_RESOURCE_NAME,
    SUBSCRIPTION_RESOURCE_NAME as STRIPE_SUBSCRIPTION_RESOURCE_NAME,
)

from products.data_warehouse.backend.models.external_data_schema import ExternalDataSchema
from products.data_warehouse.backend.test.utils import create_data_warehouse_table_from_csv
from products.revenue_analytics.backend.hogql_queries.revenue_analytics_top_customers_query_runner import (
    RevenueAnalyticsTopCustomersQueryRunner,
)
from products.revenue_analytics.backend.hogql_queries.test.data.structure import (
    STRIPE_CHARGE_COLUMNS,
    STRIPE_INVOICE_COLUMNS,
)


def _nullable_columns(basic_types: dict[str, str]) -> dict[str, dict[str, str | bool]]:
    from products.data_warehouse.backend.models import CLICKHOUSE_HOGQL_MAPPING
    from products.data_warehouse.backend.models.util import clean_type

    return {
        key: {
            "hogql": CLICKHOUSE_HOGQL_MAPPING[clean_type(value)].__name__,
            "clickhouse": f"Nullable({value})",
            "valid": True,
        }
        for key, value in basic_types.items()
    }


NULLABLE_STRIPE_CUSTOMER_COLUMNS = _nullable_columns(
    {
        "id": "String",
        "created": "Int64",
        "name": "String",
        "email": "String",
        "phone": "String",
        "address": "String",
        "metadata": "String",
    }
)

NULLABLE_STRIPE_SUBSCRIPTION_COLUMNS = _nullable_columns(
    {
        "id": "String",
        "customer": "String",
        "plan": "String",
        "created": "Int64",
        "ended_at": "Int64",
        "status": "String",
        "metadata": "String",
    }
)

CUSTOMER_TEST_BUCKET = "test_storage_bucket-posthog.revenue_analytics.customer_metadata_resolution.stripe_customers"
SUBSCRIPTION_TEST_BUCKET = (
    "test_storage_bucket-posthog.revenue_analytics.customer_metadata_resolution.stripe_subscriptions"
)
INVOICE_TEST_BUCKET = "test_storage_bucket-posthog.revenue_analytics.customer_metadata_resolution.stripe_invoices"
CHARGE_TEST_BUCKET = "test_storage_bucket-posthog.revenue_analytics.customer_metadata_resolution.stripe_charges"


class TestStripeCustomerMetadataResolution(ClickhouseTestMixin, APIBaseTest):
    QUERY_TIMESTAMP = "2025-04-21"

    def setUp(self):
        super().setUp()

        self.customer_csv = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False)
        self.customer_csv.write(
            "id,created,name,email,phone,address,metadata\n"
            'cus_no_meta,1672531200,"Alice","alice@example.com","","{}",'
            '"{}"\n'
            'cus_with_meta,1672531200,"Bob","bob@example.com","","{}",'
            '"{""posthog_person_distinct_id"": ""bob_distinct""}"\n'
            'cus_no_sub,1672531200,"Charlie","charlie@example.com","","{}",'
            '"{}"\n'
        )
        self.customer_csv.close()

        self.subscription_csv = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False)
        self.subscription_csv.write(
            "id,customer,plan,created,ended_at,status,metadata\n"
            'sub_1,cus_no_meta,"{}",1704067200,0,active,'
            '"{""posthog_person_distinct_id"": ""alice_distinct""}"\n'
        )
        self.subscription_csv.close()

        self.invoice_csv = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False)
        self.invoice_csv.write(
            "id,tax,paid,lines,total,charge,issuer,number,object,status,created,currency,customer,"
            "discount,due_date,livemode,metadata,subtotal,attempted,discounts,rendering,amount_due,"
            "period_start,period_end,amount_paid,description,invoice_pdf,account_name,auto_advance,"
            "effective_at,subscription,attempt_count,automatic_tax,customer_name,billing_reason,"
            "customer_email,ending_balance,payment_intent,account_country,amount_shipping,"
            "amount_remaining,customer_address,customer_tax_ids,paid_out_of_band,payment_settings,"
            "starting_balance,collection_method,default_tax_rates,total_tax_amounts,"
            "hosted_invoice_url,status_transitions,customer_tax_exempt,total_excluding_tax,"
            "subscription_details,webhooks_delivered_at,subtotal_excluding_tax,"
            "total_discount_amounts,pre_payment_credit_notes_amount,post_payment_credit_notes_amount\n"
            'in_1,0,1,"{}",1549,ch_1,"{}",SH-0001,invoice,paid,1704067200,usd,cus_no_meta,'
            ',,0,"{}",1549,1,"[]",,1549,1704067200,1706745600,1549,,,StreamHog,1,1704067200,'
            'sub_1,1,"{}",Alice,subscription_create,alice@example.com,0,pi_1,US,0,0,,,0,"{}",0,'
            'charge_automatically,"[]","[]",,"{}",none,1549,"{}",1704067200,1549,"[]",0,0\n'
        )
        self.invoice_csv.close()

        self.charge_csv = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False)
        self.charge_csv.write(
            "id,paid,amount,object,source,status,created,invoice,outcome,captured,currency,customer,"
            "disputed,livemode,metadata,refunded,description,receipt_url,failure_code,fraud_details,"
            "radar_options,receipt_email,payment_intent,payment_method,amount_captured,amount_refunded,"
            "billing_details,failure_message,balance_transaction,statement_descriptor,"
            "payment_method_details,calculated_statement_descriptor\n"
            'ch_1,1,1549,charge,,succeeded,1704067200,in_1,"{}",1,usd,cus_no_meta,'
            '0,0,"{}",0,Payment,,,,,,pi_1,pm_1,1549,0,"{}",,,STREAMHOG,"{}",STREAMHOG\n'
        )
        self.charge_csv.close()

        self.customers_table, self.source, self.credential, _, self.customers_cleanup = (
            create_data_warehouse_table_from_csv(
                Path(self.customer_csv.name),
                "stripe_customer",
                NULLABLE_STRIPE_CUSTOMER_COLUMNS,
                CUSTOMER_TEST_BUCKET,
                self.team,
            )
        )

        self.subscriptions_table, _, _, _, self.subscriptions_cleanup = create_data_warehouse_table_from_csv(
            Path(self.subscription_csv.name),
            "stripe_subscription",
            NULLABLE_STRIPE_SUBSCRIPTION_COLUMNS,
            SUBSCRIPTION_TEST_BUCKET,
            self.team,
            source=self.source,
            credential=self.credential,
        )

        self.invoices_table, _, _, _, self.invoices_cleanup = create_data_warehouse_table_from_csv(
            Path(self.invoice_csv.name),
            "stripe_invoice",
            STRIPE_INVOICE_COLUMNS,
            INVOICE_TEST_BUCKET,
            self.team,
            source=self.source,
            credential=self.credential,
        )

        self.charges_table, _, _, _, self.charges_cleanup = create_data_warehouse_table_from_csv(
            Path(self.charge_csv.name),
            "stripe_charge",
            STRIPE_CHARGE_COLUMNS,
            CHARGE_TEST_BUCKET,
            self.team,
            source=self.source,
            credential=self.credential,
        )

        for name, table in [
            (STRIPE_CUSTOMER_RESOURCE_NAME, self.customers_table),
            (STRIPE_SUBSCRIPTION_RESOURCE_NAME, self.subscriptions_table),
            (STRIPE_INVOICE_RESOURCE_NAME, self.invoices_table),
            (STRIPE_CHARGE_RESOURCE_NAME, self.charges_table),
        ]:
            ExternalDataSchema.objects.create(
                team=self.team,
                name=name,
                source=self.source,
                table=table,
                should_sync=True,
                last_synced_at="2024-01-01",
            )

        self.team.base_currency = CurrencyCode.USD.value
        self.team.save()

    def tearDown(self):
        self.customers_cleanup()
        self.subscriptions_cleanup()
        self.invoices_cleanup()
        self.charges_cleanup()
        for f in [self.customer_csv, self.subscription_csv, self.invoice_csv, self.charge_csv]:
            Path(f.name).unlink(missing_ok=True)
        super().tearDown()

    def _run_top_customers_query(self) -> RevenueAnalyticsTopCustomersQueryResponse:
        with freeze_time(self.QUERY_TIMESTAMP):
            query = RevenueAnalyticsTopCustomersQuery(
                dateRange=DateRange(date_from="all"),
                groupBy=RevenueAnalyticsTopCustomersGroupBy.ALL,
                properties=[],
            )
            runner = RevenueAnalyticsTopCustomersQueryRunner(
                team=self.team,
                query=query,
                modifiers=HogQLQueryModifiers(formatCsvAllowDoubleQuotes=True),
            )
            response = runner.calculate()
            RevenueAnalyticsTopCustomersQueryResponse.model_validate(response)
            return response

    def test_top_customers_query_works_with_nullable_metadata_columns(self):
        response = self._run_top_customers_query()

        self.assertIsNotNone(response)
