from datetime import date
from decimal import Decimal

from django.test import SimpleTestCase

from parameterized import parameterized

from products.managed_warehouse.backend.logic.console_pricing import (
    COMPUTE_FREE_BYTES,
    GIB,
    TIB,
    compute_cost_usd,
    storage_cost_usd,
    storage_gib_months,
)


class TestConsolePricing(SimpleTestCase):
    @parameterized.expand(
        [
            ("zero", 0, "0"),
            ("exactly the free tier", COMPUTE_FREE_BYTES, "0"),
            ("one byte over is nearly free", COMPUTE_FREE_BYTES + 1, None),
            ("one TiB over", COMPUTE_FREE_BYTES + TIB, "2.5"),
            ("ten TiB", 10 * TIB, "15"),
        ]
    )
    def test_compute_cost(self, _name: str, billable_bytes: int, expected: str | None) -> None:
        cost = compute_cost_usd(billable_bytes)
        if expected is None:
            assert 0 < cost < Decimal("0.000001")
        else:
            assert cost == Decimal(expected)

    @parameterized.expand(
        [
            ("zero", "0", "0"),
            ("exactly the free tier", "100", "0"),
            ("inside the second tier", "300", "8"),
            ("exactly the second tier top", "500", "16"),
            ("crossing two tiers", "1024", "34.34"),
            ("crossing three tiers", "2048", "65.06"),
            ("top tier", "61440", "1554.98"),
        ]
    )
    def test_storage_cost_is_progressive(self, _name: str, gib_months: str, expected: str) -> None:
        assert storage_cost_usd(Decimal(gib_months)) == Decimal(expected)

    @parameterized.expand(
        [
            ("february", date(2026, 2, 1), 28),
            ("long month", date(2026, 3, 1), 31),
            ("leap february", date(2028, 2, 1), 29),
        ]
    )
    def test_storage_gib_months_uses_the_length_of_the_month(self, _name: str, month: date, days: int) -> None:
        one_gib_all_month = Decimal(GIB * days * 86400)
        assert storage_gib_months(one_gib_all_month, month) == Decimal(1)
