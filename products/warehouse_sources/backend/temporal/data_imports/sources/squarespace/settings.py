from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SortMode
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class SquarespaceEndpointConfig:
    name: str
    # Per-API version segment of the URL (e.g. "1.0", "v2"). Squarespace versions each
    # Commerce API independently, so this is per-endpoint, not global.
    api_version: str
    path: str
    # Top-level key in the JSON response holding the list of rows. Differs per endpoint:
    # orders -> "result", products -> "products", transactions -> "documents", etc.
    data_key: str
    primary_keys: list[str]
    incremental_fields: list[IncrementalField]
    # Stable datetime field used for partitioning. Must never change for a row
    # (so `createdOn`, never `modifiedOn`). `None` disables partitioning.
    partition_key: Optional[str] = None
    # Whether the endpoint honours the server-side `modifiedAfter`/`modifiedBefore`
    # time window (which filters on `modifiedOn`). Only set when the API genuinely
    # filters — this is what enables incremental sync. `None`/False => full refresh.
    supports_time_filter: bool = False
    # Order rows arrive in. Squarespace returns the time-filtered list endpoints
    # newest-modified-first (descending). `desc` is also crash-safe for the watermark:
    # the pipeline only finalizes the last incremental value at the end of a run.
    sort_mode: SortMode = "asc"
    # Static query params applied to the first page only (sort/filter). Cannot be sent
    # alongside a cursor, so they're dropped once pagination starts.
    extra_params: dict[str, str] = field(default_factory=dict)


def _modified_on_incremental_field() -> list[IncrementalField]:
    return [
        {
            "label": "modifiedOn",
            "type": IncrementalFieldType.DateTime,
            "field": "modifiedOn",
            "field_type": IncrementalFieldType.DateTime,
        }
    ]


# Squarespace Commerce + Website APIs reachable with a single API-key (Bearer) token.
# Webhook Subscriptions and OAuth-only resources are intentionally excluded — a simple
# API-key connector cannot manage them.
SQUARESPACE_ENDPOINTS: dict[str, SquarespaceEndpointConfig] = {
    # Orders, Products and Transactions expose `modifiedAfter`/`modifiedBefore`, a
    # server-side filter on `modifiedOn`, so they support incremental sync. The window
    # params are mutually exclusive with `cursor`, so they apply to the first page only
    # and pagination continues via the cursor (which preserves the window).
    "orders": SquarespaceEndpointConfig(
        name="orders",
        api_version="1.0",
        path="/commerce/orders",
        data_key="result",
        primary_keys=["id"],
        partition_key="createdOn",
        supports_time_filter=True,
        sort_mode="desc",
        incremental_fields=_modified_on_incremental_field(),
    ),
    "products": SquarespaceEndpointConfig(
        name="products",
        api_version="v2",
        path="/commerce/products",
        data_key="products",
        primary_keys=["id"],
        partition_key="createdOn",
        supports_time_filter=True,
        sort_mode="desc",
        incremental_fields=_modified_on_incremental_field(),
    ),
    "transactions": SquarespaceEndpointConfig(
        name="transactions",
        api_version="1.0",
        path="/commerce/transactions",
        data_key="documents",
        primary_keys=["id"],
        partition_key="createdOn",
        supports_time_filter=True,
        sort_mode="desc",
        incremental_fields=_modified_on_incremental_field(),
    ),
    # Inventory exposes only the cursor — no time filter and no timestamp fields — so
    # it's full refresh with no stable partition key. The primary key is the variant id.
    "inventory": SquarespaceEndpointConfig(
        name="inventory",
        api_version="1.0",
        path="/commerce/inventory",
        data_key="inventory",
        primary_keys=["variantId"],
        incremental_fields=[],
    ),
    # Store Pages carry no timestamp fields, so full refresh only.
    "store_pages": SquarespaceEndpointConfig(
        name="store_pages",
        api_version="1.0",
        path="/commerce/store_pages",
        data_key="storePages",
        primary_keys=["id"],
        incremental_fields=[],
    ),
    # Profiles has a `createdOn` (stable partition key) but no `modifiedAfter` filter —
    # only `sortField`/`sortDirection`/`filter` — so it's full refresh. We sort by
    # createdOn ascending for stable cursor pagination.
    "profiles": SquarespaceEndpointConfig(
        name="profiles",
        api_version="1.0",
        path="/profiles",
        data_key="profiles",
        primary_keys=["id"],
        partition_key="createdOn",
        incremental_fields=[],
        extra_params={"sortField": "createdOn", "sortDirection": "asc"},
    ),
}

ENDPOINTS = tuple(SQUARESPACE_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in SQUARESPACE_ENDPOINTS.items()
}
