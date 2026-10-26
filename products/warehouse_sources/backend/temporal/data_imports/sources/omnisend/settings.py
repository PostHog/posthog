from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

OMNISEND_V3 = "v3"
# Header-versioned (`Omnisend-Version`) on the `/api` base path, with `Authorization: Omnisend-API-Key`.
OMNISEND_2026_03_15 = "2026-03-15"


@dataclass(frozen=True)
class OmnisendWire:
    path: str
    data_key: str  # Response array key, e.g. {"contacts": [...], "paging": {...}}
    primary_key: str
    # Opaque `paging.cursors.after` tokens instead of a fully-formed `paging.next` URL.
    cursor_paginated: bool = False
    params: Mapping[str, Any] = field(default_factory=dict)
    page_size: Optional[int] = None


@dataclass(frozen=True)
class OmnisendAnalyticsQuery:
    # Breakdown dimensions next to the daily `timestamp`; together they key a row.
    dimensions: tuple[str, ...]
    metrics: tuple[str, ...]
    # `/analytics/reports` needs `dateRange.interval`; `/analytics/statistics` has no such field.
    date_range_interval: Optional[str] = None


@dataclass(frozen=True)
class OmnisendEndpointConfig:
    name: str
    # Request shape per supported API version. A version missing here has no list endpoint for
    # the resource, so the table is not offered on that version.
    wires: dict[str, OmnisendWire]
    # Stable creation-time field used for delta partitioning. Never a mutable field
    # like updatedAt — partitions would rewrite on every sync.
    partition_key: Optional[str] = None
    # Advertised incremental options. Empty = full refresh only (see api_inventory.md: the list
    # endpoints' timestamp filters are unverified, so they ship full refresh).
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    analytics: Optional[OmnisendAnalyticsQuery] = None
    default_incremental_lookback_seconds: Optional[int] = None


# Count metrics only: rates and per-order averages are derivable and can't be summed across rows.
_ACTIVITY_METRICS = (
    "sent",
    "failed",
    "sentCost",
    "markedAsSpamUnique",
    "unsubscribedUnique",
    "openedUnique",
    "opened",
    "clickedUnique",
    "clicked",
    "attributedOrdersUnique",
    "attributedOrders",
    "attributedRevenue",
)

# Every statistics metric supports the timestamp dimension, so a daily account-level row can carry
# store sales and audience growth alongside message activity.
_ACCOUNT_STATISTICS_METRICS = (
    *_ACTIVITY_METRICS,
    "totalOrders",
    "totalRevenue",
    "totalOrderedProductUnits",
    "attributedOrderedProductUnits",
    "subscribedEmail",
    "subscribedSms",
    "subscribedPush",
    "unsubscribedEmail",
    "unsubscribedSms",
    "unsubscribedPush",
)

_ANALYTICS_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "timestamp",
        "type": IncrementalFieldType.Date,
        "field": "timestamp",
        "field_type": IncrementalFieldType.Date,
    },
]

# Opens, clicks and attributed orders keep landing on a send date for weeks after the send.
_ANALYTICS_LOOKBACK_SECONDS = 30 * 24 * 60 * 60


OMNISEND_ENDPOINTS: dict[str, OmnisendEndpointConfig] = {
    "contacts": OmnisendEndpointConfig(
        name="contacts",
        wires={
            OMNISEND_V3: OmnisendWire(path="/contacts", data_key="contacts", primary_key="contactID"),
            OMNISEND_2026_03_15: OmnisendWire(
                path="/contacts", data_key="contacts", primary_key="id", cursor_paginated=True
            ),
        },
        partition_key="createdAt",
    ),
    "campaigns": OmnisendEndpointConfig(
        name="campaigns",
        wires={
            # `/v3/campaigns` is the one v3 list endpoint that nests its rows under the singular
            # `campaign` key; every other resource uses the plural `<resource>` convention.
            OMNISEND_V3: OmnisendWire(path="/campaigns", data_key="campaign", primary_key="campaignID"),
            OMNISEND_2026_03_15: OmnisendWire(
                path="/campaigns", data_key="campaigns", primary_key="id", cursor_paginated=True
            ),
        },
        partition_key="createdAt",
    ),
    "carts": OmnisendEndpointConfig(
        name="carts",
        wires={OMNISEND_V3: OmnisendWire(path="/carts", data_key="carts", primary_key="cartID")},
        partition_key="createdAt",
    ),
    "orders": OmnisendEndpointConfig(
        name="orders",
        wires={OMNISEND_V3: OmnisendWire(path="/orders", data_key="orders", primary_key="orderID")},
        partition_key="createdAt",
    ),
    "products": OmnisendEndpointConfig(
        name="products",
        wires={
            OMNISEND_V3: OmnisendWire(path="/products", data_key="products", primary_key="productID"),
            OMNISEND_2026_03_15: OmnisendWire(path="/products", data_key="products", primary_key="id"),
        },
        partition_key="createdAt",
    ),
    "categories": OmnisendEndpointConfig(
        name="categories",
        wires={
            OMNISEND_V3: OmnisendWire(path="/categories", data_key="categories", primary_key="categoryID"),
            OMNISEND_2026_03_15: OmnisendWire(
                path="/product-categories", data_key="categories", primary_key="categoryID"
            ),
        },
    ),
    "automations": OmnisendEndpointConfig(
        name="automations",
        wires={
            OMNISEND_2026_03_15: OmnisendWire(
                path="/automations",
                data_key="automations",
                primary_key="id",
                cursor_paginated=True,
                # The summary view drops the `blocks` tree, whose webhook actions carry header values
                # (often third-party credentials) verbatim.
                params={"sort": "createdAt", "direction": "asc", "view": "summary"},
            ),
        },
        partition_key="createdAt",
    ),
    "segments": OmnisendEndpointConfig(
        name="segments",
        wires={
            OMNISEND_2026_03_15: OmnisendWire(
                path="/segments",
                data_key="segments",
                primary_key="segmentID",
                cursor_paginated=True,
                params={"sort": "createdAt", "direction": "asc"},
                page_size=50,
            ),
        },
        partition_key="createdAt",
    ),
    "analytics_reports": OmnisendEndpointConfig(
        name="analytics_reports",
        wires={
            OMNISEND_2026_03_15: OmnisendWire(path="/analytics/reports", data_key="reports", primary_key="timestamp"),
        },
        partition_key="timestamp",
        incremental_fields=_ANALYTICS_INCREMENTAL_FIELDS,
        analytics=OmnisendAnalyticsQuery(
            dimensions=("marketingActivityType", "marketingActivityID"),
            metrics=_ACTIVITY_METRICS,
            date_range_interval="custom",
        ),
        default_incremental_lookback_seconds=_ANALYTICS_LOOKBACK_SECONDS,
    ),
    "analytics_statistics": OmnisendEndpointConfig(
        name="analytics_statistics",
        wires={
            OMNISEND_2026_03_15: OmnisendWire(
                path="/analytics/statistics", data_key="statistics", primary_key="timestamp"
            ),
        },
        partition_key="timestamp",
        incremental_fields=_ANALYTICS_INCREMENTAL_FIELDS,
        analytics=OmnisendAnalyticsQuery(dimensions=(), metrics=_ACCOUNT_STATISTICS_METRICS),
        default_incremental_lookback_seconds=_ANALYTICS_LOOKBACK_SECONDS,
    ),
}

ENDPOINTS = tuple(OMNISEND_ENDPOINTS.keys())


def endpoints_for_version(api_version: str) -> tuple[str, ...]:
    return tuple(name for name, config in OMNISEND_ENDPOINTS.items() if api_version in config.wires)


INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in OMNISEND_ENDPOINTS.items()
}

# Analytics rows for recent days are restated on each read, so only a merge keeps one row per key.
MERGE_ONLY_ENDPOINTS = tuple(name for name, config in OMNISEND_ENDPOINTS.items() if config.analytics is not None)

DEFAULT_INCREMENTAL_LOOKBACK_SECONDS: dict[str, int] = {
    name: config.default_incremental_lookback_seconds
    for name, config in OMNISEND_ENDPOINTS.items()
    if config.default_incremental_lookback_seconds is not None
}
