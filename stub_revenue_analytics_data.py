#!/usr/bin/env python
"""
Script to stub revenue analytics test data.

Run from the posthog directory:
    flox activate -- bash -c "python stub_revenue_analytics_data.py"
"""
import os
import sys
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
django.setup()

import json
from datetime import datetime, timedelta
from django.utils import timezone
from pathlib import Path

import pandas as pd
import s3fs

from posthog.models.team import Team
from posthog.settings import (
    OBJECT_STORAGE_ACCESS_KEY_ID,
    OBJECT_STORAGE_BUCKET,
    OBJECT_STORAGE_ENDPOINT,
    OBJECT_STORAGE_SECRET_ACCESS_KEY,
)

from products.data_warehouse.backend.models import CLICKHOUSE_HOGQL_MAPPING
from products.data_warehouse.backend.models.credential import DataWarehouseCredential
from products.data_warehouse.backend.models.datawarehouse_managed_viewset import DataWarehouseManagedViewSet
from products.data_warehouse.backend.models.external_data_source import ExternalDataSource
from products.data_warehouse.backend.models.external_data_schema import ExternalDataSchema
from products.data_warehouse.backend.models.revenue_analytics_config import ExternalDataSourceRevenueAnalyticsConfig
from products.data_warehouse.backend.models.table import DataWarehouseTable
from products.data_warehouse.backend.types import DataWarehouseManagedViewSetKind, ExternalDataSourceType

from posthog.temporal.data_imports.sources.stripe.constants import (
    CHARGE_RESOURCE_NAME,
    CUSTOMER_RESOURCE_NAME,
    INVOICE_RESOURCE_NAME,
    PRODUCT_RESOURCE_NAME,
    SUBSCRIPTION_RESOURCE_NAME,
)

# Use the exact same column structure as the test data
from products.revenue_analytics.backend.hogql_queries.test.data.structure import (
    STRIPE_CHARGE_COLUMNS,
    STRIPE_CUSTOMER_COLUMNS,
    STRIPE_INVOICE_COLUMNS,
    STRIPE_PRODUCT_COLUMNS,
    STRIPE_SUBSCRIPTION_COLUMNS,
)


def main():
    team_id = 1  # Default project

    try:
        team = Team.objects.get(id=team_id)
    except Team.DoesNotExist:
        print(f"Team with ID {team_id} not found")
        sys.exit(1)

    print(f"Setting up revenue analytics test data for team: {team.name} (ID: {team_id})")

    if not OBJECT_STORAGE_ACCESS_KEY_ID or not OBJECT_STORAGE_SECRET_ACCESS_KEY:
        print("ERROR: Missing S3 credentials")
        sys.exit(1)

    # Initialize S3 filesystem
    fs = s3fs.S3FileSystem(
        client_kwargs={
            "region_name": "us-east-1",
            "endpoint_url": OBJECT_STORAGE_ENDPOINT,
            "aws_access_key_id": OBJECT_STORAGE_ACCESS_KEY_ID,
            "aws_secret_access_key": OBJECT_STORAGE_SECRET_ACCESS_KEY,
        },
    )

    test_bucket = f"revenue_analytics_stub_{team_id}"
    # Use "stub_" prefix so table_name_without_prefix() returns "stripe_customer" etc
    # which matches the keys in external_table_definitions.py
    source_prefix = "stub_"

    # Delete ALL existing stub/test data sources to start fresh
    ExternalDataSource.objects.filter(team=team, prefix__startswith="stub").delete()
    ExternalDataSource.objects.filter(team=team, prefix__startswith="test").delete()

    # Create external data source
    source = ExternalDataSource.objects.create(
        team=team,
        source_id=f"stub_source_{team_id}",
        connection_id=f"stub_connection_{team_id}",
        status=ExternalDataSource.Status.COMPLETED,
        source_type=ExternalDataSourceType.STRIPE,
        prefix=source_prefix,
    )

    # Enable revenue analytics
    config, _ = ExternalDataSourceRevenueAnalyticsConfig.objects.get_or_create(
        external_data_source=source,
        defaults={"enabled": True},
    )
    config.enabled = True
    config.save()

    # Create credential
    credential, _ = DataWarehouseCredential.objects.get_or_create(
        team=team,
        access_key=OBJECT_STORAGE_ACCESS_KEY_ID,
        defaults={"access_secret": OBJECT_STORAGE_SECRET_ACCESS_KEY},
    )

    # Generate test data with custom metadata
    base_date = datetime.now() - timedelta(days=90)

    # Customers with different revenue_source metadata
    customers_data = []
    for i in range(1, 11):
        revenue_source = "self-serve" if i <= 5 else "sales-led"
        plan_type = "starter" if i <= 3 else ("growth" if i <= 7 else "enterprise")
        customers_data.append({
            "id": f"cus_{i}",
            "created": (base_date + timedelta(days=i)).strftime("%Y-%m-%d %H:%M:%S"),
            "name": f"Customer {i}",
            "email": f"customer{i}@example.com",
            "phone": f"+1234567890{i}",
            "address": json.dumps({"country": "US" if i % 2 == 0 else "UK"}),
            "metadata": json.dumps({
                "revenue_source": revenue_source,
                "plan_type": plan_type,
                "signup_channel": "website" if i % 3 == 0 else "referral",
            }),
        })

    # Subscriptions
    subscriptions_data = []
    for i in range(1, 11):
        subscriptions_data.append({
            "id": f"sub_{i}",
            "customer": f"cus_{i}",
            "plan": f"plan_{(i % 3) + 1}",
            "created": (base_date + timedelta(days=i + 5)).strftime("%Y-%m-%d %H:%M:%S"),
            "ended_at": None,
            "status": "active",
            "metadata": json.dumps({
                "subscription_tier": "basic" if i <= 3 else ("pro" if i <= 7 else "enterprise"),
            }),
        })

    # Invoices - using full schema to match test data
    invoices_data = []
    invoice_id = 1
    for month in range(3):
        for cust_i in range(1, 11):
            amount = (cust_i * 1000 + month * 100) * 100
            invoice_date = base_date + timedelta(days=month * 30 + cust_i)
            period_start = int(invoice_date.timestamp())
            period_end = int((invoice_date + timedelta(days=30)).timestamp())
            product_id = f"prod_{(cust_i % 3) + 1}"
            invoice_line_item = {
                "id": f"ii_{invoice_id}",
                "amount": amount,
                "currency": "usd",
                "price": {"product": product_id},
                "period": {"start": period_start, "end": period_end},
                "discount_amounts": [],
            }
            invoices_data.append({
                "id": f"inv_{invoice_id}",
                "tax": 0,
                "paid": 1,
                "lines": json.dumps({"data": [invoice_line_item]}),
                "total": amount,
                "charge": f"ch_{invoice_id}",
                "issuer": json.dumps({}),
                "number": f"INV-{invoice_id:04d}",
                "object": "invoice",
                "status": "paid",
                "created": invoice_date.strftime("%Y-%m-%d %H:%M:%S"),
                "currency": "usd",
                "customer": f"cus_{cust_i}",
                "subscription": f"sub_{cust_i}",
                "discount": json.dumps({}),
                "due_date": invoice_date.strftime("%Y-%m-%d %H:%M:%S"),
                "livemode": 1,
                "metadata": json.dumps({}),
                "subtotal": amount,
                "attempted": 1,
                "discounts": json.dumps([]),
                "rendering": json.dumps({}),
                "amount_due": amount,
                "period_start_at": invoice_date.strftime("%Y-%m-%d %H:%M:%S"),
                "period_end_at": (invoice_date + timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S"),
                "amount_paid": amount,
                "description": f"Invoice {invoice_id}",
                "invoice_pdf": "",
                "account_name": "",
                "auto_advance": 1,
                "effective_at": invoice_date.strftime("%Y-%m-%d %H:%M:%S"),
                "attempt_count": 1,
                "automatic_tax": json.dumps({}),
                "customer_name": f"Customer {cust_i}",
                "billing_reason": "subscription_cycle",
                "customer_email": f"customer{cust_i}@example.com",
                "ending_balance": 0,
                "payment_intent": f"pi_{invoice_id}",
                "account_country": "US",
                "amount_shipping": 0,
                "amount_remaining": 0,
                "customer_address": json.dumps({}),
                "customer_tax_ids": json.dumps([]),
                "paid_out_of_band": 0,
                "payment_settings": json.dumps({}),
                "starting_balance": 0,
                "collection_method": "charge_automatically",
                "default_tax_rates": json.dumps([]),
                "total_tax_amounts": json.dumps([]),
                "hosted_invoice_url": "",
                "status_transitions": json.dumps({}),
                "customer_tax_exempt": "none",
                "total_excluding_tax": amount,
                "subscription_details": json.dumps({}),
                "webhooks_delivered_at": invoice_date.strftime("%Y-%m-%d %H:%M:%S"),
                "subtotal_excluding_tax": amount,
                "total_discount_amounts": json.dumps([]),
                "pre_payment_credit_notes_amount": 0,
                "post_payment_credit_notes_amount": 0,
            })
            invoice_id += 1

    # Products
    products_data = [
        {"id": "prod_1", "name": "Starter Plan", "type": "service", "active": 1, "images": json.dumps([]), "object": "product", "created": base_date.strftime("%Y-%m-%d %H:%M:%S"), "updated_at": base_date.strftime("%Y-%m-%d %H:%M:%S"), "features": json.dumps([]), "livemode": 1, "metadata": json.dumps({}), "tax_code": "", "attributes": json.dumps([]), "description": "Starter plan", "default_price_id": ""},
        {"id": "prod_2", "name": "Growth Plan", "type": "service", "active": 1, "images": json.dumps([]), "object": "product", "created": base_date.strftime("%Y-%m-%d %H:%M:%S"), "updated_at": base_date.strftime("%Y-%m-%d %H:%M:%S"), "features": json.dumps([]), "livemode": 1, "metadata": json.dumps({}), "tax_code": "", "attributes": json.dumps([]), "description": "Growth plan", "default_price_id": ""},
        {"id": "prod_3", "name": "Enterprise Plan", "type": "service", "active": 1, "images": json.dumps([]), "object": "product", "created": base_date.strftime("%Y-%m-%d %H:%M:%S"), "updated_at": base_date.strftime("%Y-%m-%d %H:%M:%S"), "features": json.dumps([]), "livemode": 1, "metadata": json.dumps({}), "tax_code": "", "attributes": json.dumps([]), "description": "Enterprise plan", "default_price_id": ""},
    ]

    # Charges
    charges_data = []
    for i, inv in enumerate(invoices_data):
        charges_data.append({
            "id": f"ch_{i + 1}",
            "paid": 1,
            "amount": inv["total"],
            "object": "charge",
            "status": "succeeded",
            "created": inv["created"],
            "invoice": inv["id"],
            "captured": 1,
            "currency": inv["currency"],
            "customer": inv["customer"],
            "disputed": 0,
            "livemode": 1,
            "metadata": json.dumps({}),
            "refunded": 0,
            "description": "",
            "receipt_url": "",
            "failure_code": "",
            "fraud_details": json.dumps({}),
            "radar_options": json.dumps({}),
            "receipt_email": "",
            "payment_intent": inv["payment_intent"],
            "payment_method": "",
            "amount_captured": inv["total"],
            "amount_refunded": 0,
            "billing_details": json.dumps({}),
            "failure_message": "",
            "balance_transaction": "",
            "statement_descriptor": "",
            "calculated_statement_descriptor": "",
            "source": json.dumps({}),
            "outcome": json.dumps({}),
            "payment_method_details": json.dumps({}),
        })

    # Upload data
    # Table suffix should match external_table_definitions.py keys when prefixed with source_prefix
    # e.g., prefix "stub_" + suffix "stripe_customer" = "stub_stripe_customer"
    # And table_name_without_prefix() strips "stub_" to get "stripe_customer"
    tables_config = [
        ("stripe_customer", STRIPE_CUSTOMER_COLUMNS, customers_data, CUSTOMER_RESOURCE_NAME),
        ("stripe_subscription", STRIPE_SUBSCRIPTION_COLUMNS, subscriptions_data, SUBSCRIPTION_RESOURCE_NAME),
        ("stripe_invoice", STRIPE_INVOICE_COLUMNS, invoices_data, INVOICE_RESOURCE_NAME),
        ("stripe_product", STRIPE_PRODUCT_COLUMNS, products_data, PRODUCT_RESOURCE_NAME),
        ("stripe_charge", STRIPE_CHARGE_COLUMNS, charges_data, CHARGE_RESOURCE_NAME),
    ]

    for table_suffix, columns, data, schema_name in tables_config:
        table_name = f"{source_prefix}{table_suffix}"
        print(f"  Creating table: {table_name}")

        df = pd.DataFrame(data)
        folder = f"{OBJECT_STORAGE_BUCKET}/{test_bucket}/{table_name}"
        path_to_s3_object = f"{folder}/data.parquet"
        with fs.open(path_to_s3_object, "wb", blocksize=None) as f:
            df.to_parquet(f, index=False)

        # Delete existing table
        DataWarehouseTable.objects.filter(name=table_name, team=team).delete()

        table = DataWarehouseTable.objects.create(
            name=table_name,
            team=team,
            format=DataWarehouseTable.TableFormat.Parquet,
            external_data_source=source,
            credential=credential,
            url_pattern=f"http://objectstorage:19000/{folder}/*.parquet",
            columns=columns,
        )

        # Delete existing schema
        ExternalDataSchema.objects.filter(team=team, name=schema_name, source=source).delete()

        ExternalDataSchema.objects.create(
            team=team,
            name=schema_name,
            source=source,
            table=table,
            should_sync=True,
            last_synced_at=timezone.now(),
        )

    # Create managed viewset
    print("  Creating revenue analytics views...")
    viewset, _ = DataWarehouseManagedViewSet.objects.get_or_create(
        team=team,
        kind=DataWarehouseManagedViewSetKind.REVENUE_ANALYTICS,
    )
    viewset.sync_views()

    print(f"\nCreated {len(customers_data)} customers with custom metadata:")
    print("  - 5 with revenue_source='self-serve'")
    print("  - 5 with revenue_source='sales-led'")
    print(f"Created {len(invoices_data)} invoices")
    print(f"Created {len(charges_data)} charges")

    print("\n✅ Revenue analytics test data created!")
    print("\nTo test:")
    print("1. Start local server: ./bin/start")
    print(f"2. Go to http://localhost:8010/project/{team_id}/revenue")
    print("3. Click 'Filters' -> '+ Add filter'")
    print("4. Select 'HogQL expression'")
    print("5. Try: JSONExtractString(revenue_analytics_customer.metadata, 'revenue_source') = 'self-serve'")


if __name__ == "__main__":
    main()
