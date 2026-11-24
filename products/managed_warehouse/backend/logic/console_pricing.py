"""Managed warehouse pricing, mirroring the billing rules hogtower reports usage for.

All money is Decimal. Usage is priced per organization per UTC calendar month.
"""

from __future__ import annotations

import calendar
from datetime import date
from decimal import Decimal

from posthog.dataclasses import frozen

TIB = 1024**4
GIB = 1024**3

COMPUTE_FREE_BYTES = 4 * TIB
COMPUTE_USD_PER_TIB = Decimal("2.50")

STORAGE_FREE_GIB_MONTHS = Decimal(100)


@frozen
class StorageTier:
    upper_gib: Decimal | None
    usd_per_gib_month: Decimal


# Progressive tiers over the monthly-average GiB. The first 100 GiB are free.
STORAGE_TIERS: tuple[StorageTier, ...] = (
    StorageTier(upper_gib=Decimal(100), usd_per_gib_month=Decimal(0)),
    StorageTier(upper_gib=Decimal(500), usd_per_gib_month=Decimal("0.0400")),
    StorageTier(upper_gib=Decimal(1024), usd_per_gib_month=Decimal("0.0350")),
    StorageTier(upper_gib=Decimal(10240), usd_per_gib_month=Decimal("0.0300")),
    StorageTier(upper_gib=Decimal(51200), usd_per_gib_month=Decimal("0.0245")),
    StorageTier(upper_gib=None, usd_per_gib_month=Decimal("0.0235")),
)


def seconds_in_month(month_start: date) -> int:
    return calendar.monthrange(month_start.year, month_start.month)[1] * 86400


def compute_cost_usd(billable_bytes: int) -> Decimal:
    billable = max(billable_bytes - COMPUTE_FREE_BYTES, 0)
    return Decimal(billable) / Decimal(TIB) * COMPUTE_USD_PER_TIB


def storage_gib_months(byte_seconds: Decimal, month_start: date) -> Decimal:
    return byte_seconds / Decimal(GIB) / Decimal(seconds_in_month(month_start))


def storage_cost_usd(gib_months: Decimal) -> Decimal:
    cost = Decimal(0)
    lower = Decimal(0)
    for tier in STORAGE_TIERS:
        if gib_months <= lower:
            break
        upper = gib_months if tier.upper_gib is None else min(gib_months, tier.upper_gib)
        cost += (upper - lower) * tier.usd_per_gib_month
        if tier.upper_gib is None:
            break
        lower = tier.upper_gib
    return cost
