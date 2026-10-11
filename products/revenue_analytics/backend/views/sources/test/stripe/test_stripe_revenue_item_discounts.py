import csv
import json
import tempfile
from decimal import Decimal
from pathlib import Path
from typing import Any

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from posthog.schema import CurrencyCode, HogQLQueryModifiers

from posthog.hogql.query import execute_hogql_query

from products.revenue_analytics.backend.views.schemas.revenue_item import SCHEMA as REVENUE_ITEM_SCHEMA
from products.revenue_analytics.backend.views.test.data.structure import STRIPE_INVOICE_COLUMNS
from products.warehouse_sources.backend.facade.models import ExternalDataSchema
from products.warehouse_sources.backend.facade.sources import INVOICE_RESOURCE_NAME as STRIPE_INVOICE_RESOURCE_NAME
from products.warehouse_sources.backend.facade.testing import create_data_warehouse_table_from_csv

INVOICE_TEST_BUCKET = "test_storage_bucket-posthog.revenue_analytics.revenue_item_discounts.stripe_invoices"

JAN_1_2024 = 1704067200
FEB_1_2024 = 1706745600
JAN_1_2025 = 1735689600


def _line(
    line_id: str,
    amount: int,
    *,
    period_end: int = FEB_1_2024,
    discount_amounts: list[int] | None = None,
    discountable: bool = True,
) -> dict[str, Any]:
    return {
        "id": line_id,
        "object": "line_item",
        "amount": amount,
        "currency": "usd",
        "discountable": discountable,
        "discount_amounts": [{"amount": a, "discount": "di_test"} for a in discount_amounts or []],
        "period": {"start": JAN_1_2024, "end": period_end},
        "price": {"product": "prod_test"},
    }


def _invoice(invoice_id: str, lines: list[dict[str, Any]], total_discount_amounts: list[int]) -> dict[str, Any]:
    row: dict[str, Any] = {}
    for column, column_type in STRIPE_INVOICE_COLUMNS.items():
        clickhouse_type = column_type["clickhouse"]
        if clickhouse_type == "DateTime":
            row[column] = JAN_1_2024
        elif clickhouse_type in ("Int64", "UInt8"):
            row[column] = 0
        else:
            row[column] = ""
    row.update(
        {
            "id": invoice_id,
            "paid": 1,
            "currency": "usd",
            "customer": "cus_test",
            "subscription": "sub_test",
            "lines": json.dumps({"data": lines}),
            "total_discount_amounts": json.dumps(
                [{"amount": a, "discount": "di_test"} for a in total_discount_amounts]
            ),
        }
    )
    return row


INVOICES = [
    # Legacy annual invoice: the coupon covers the whole line, but only the invoice reports it
    _invoice("in_full", [_line("il_full", 94800, period_end=JAN_1_2025)], [94800]),
    _invoice("in_partial", [_line("il_partial_1", 1000), _line("il_partial_2", 2000)], [1000]),
    _invoice(
        "in_non_discountable",
        [_line("il_discountable", 1000), _line("il_non_discountable", 500, discountable=False)],
        [500],
    ),
    _invoice(
        "in_rounding", [_line("il_rounding_1", 100), _line("il_rounding_2", 100), _line("il_rounding_3", 100)], [100]
    ),
    # Modern invoice: lines already carry the invoice discount, so nothing is left to allocate
    _invoice("in_modern", [_line("il_modern", 1000, discount_amounts=[200])], [200]),
    _invoice(
        "in_mixed",
        [_line("il_mixed_1", 1000, discount_amounts=[100]), _line("il_mixed_2", 900)],
        [600],
    ),
]


class TestStripeRevenueItemInvoiceDiscounts(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()

        self.invoice_csv = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, newline="")
        writer = csv.DictWriter(self.invoice_csv, fieldnames=list(STRIPE_INVOICE_COLUMNS.keys()))
        writer.writeheader()
        writer.writerows(INVOICES)
        self.invoice_csv.close()

        self.invoices_table, self.source, _, _, self.invoices_cleanup = create_data_warehouse_table_from_csv(
            Path(self.invoice_csv.name),
            "stripe_invoice",
            STRIPE_INVOICE_COLUMNS,
            INVOICE_TEST_BUCKET,
            self.team,
        )
        ExternalDataSchema.objects.create(
            team=self.team,
            name=STRIPE_INVOICE_RESOURCE_NAME,
            source=self.source,
            table=self.invoices_table,
            should_sync=True,
            last_synced_at="2024-01-01",
        )

        self.team.base_currency = CurrencyCode.USD.value
        self.team.save()

    def tearDown(self):
        self.invoices_cleanup()
        Path(self.invoice_csv.name).unlink(missing_ok=True)
        super().tearDown()

    def test_invoice_level_discounts_are_allocated_to_lines(self):
        response = execute_hogql_query(
            query=f"""
                SELECT invoice_item_id, count(), sum(amount)
                FROM stripe.posthog_test.{REVENUE_ITEM_SCHEMA.source_suffix}
                GROUP BY invoice_item_id
            """,
            team=self.team,
            modifiers=HogQLQueryModifiers(formatCsvAllowDoubleQuotes=True),
        )

        results = {invoice_item_id: (count, amount) for invoice_item_id, count, amount in response.results}
        assert results == {
            "il_full": (12, Decimal("0")),
            "il_partial_1": (1, Decimal("6.67")),
            "il_partial_2": (1, Decimal("13.33")),
            "il_discountable": (1, Decimal("5")),
            "il_non_discountable": (1, Decimal("5")),
            "il_rounding_1": (1, Decimal("0.67")),
            "il_rounding_2": (1, Decimal("0.66")),
            "il_rounding_3": (1, Decimal("0.67")),
            "il_modern": (1, Decimal("8")),
            "il_mixed_1": (1, Decimal("6.5")),
            "il_mixed_2": (1, Decimal("6.5")),
        }
