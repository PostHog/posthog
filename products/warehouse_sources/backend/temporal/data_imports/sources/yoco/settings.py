from dataclasses import dataclass, field
from datetime import timedelta

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField

YOCO_BASE_URL = "https://api.yoco.com"

# Yoco documents a default page size of 50 and no maximum, so we send the documented default
# rather than guessing at a higher cap that the API might reject.
DEFAULT_PAGE_SIZE = 50

# Yoco caps any `created_at`/`updated_at` range at 31 days, and fills in the missing bound 31
# days away when only one is given. An incremental sync therefore walks the interval between
# the watermark and now in windows of at most this size instead of one open-ended `__gte`.
MAX_FILTER_WINDOW = timedelta(days=31)

# Scope each endpoint needs on the API key, surfaced per table in the schema picker.
ENDPOINT_SCOPES: dict[str, str] = {
    "payments": "business/orders:read",
    "orders": "business/orders:read",
    "refunds": "business/orders:read",
    "payment_links": "business/orders:read",
    "payouts": "business/payouts:read",
    "payout_entries": "business/payouts:read",
    "items": "business/catalogue:read",
    "item_categories": "business/catalogue:read",
    "item_brands": "business/catalogue:read",
    "modifier_groups": "business/catalogue:read",
    "locations": "business/locations:read",
    "staff": "business/staff:read",
    "card_machines": "business/devices:read",
}


# Mutable by choice, not oversight: instances flow into `build_dependent_resource`'s
# `endpoint_configs: Mapping[str, FanoutEndpointLike]`, and mypy treats a frozen dataclass's
# fields as read-only, which is incompatible with that Protocol's plain (read-write) attributes.
@dataclass(frozen=False)
class YocoEndpointConfig:
    name: str
    path: str
    primary_key: list[str]
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: str | None = None
    partition_key: str | None = None
    page_size: int = DEFAULT_PAGE_SIZE
    fanout: DependentEndpointConfig | None = None


def _created_and_updated() -> list[IncrementalField]:
    # Both filters exist on every dated list endpoint. `updated_at` is the better cursor
    # because it also catches later edits, but Yoco types it nullable on several resources,
    # so `created_at` stays available for anyone who sees never-modified rows drop out.
    return [incremental_field("updated_at"), incremental_field("created_at")]


YOCO_ENDPOINTS: dict[str, YocoEndpointConfig] = {
    "payments": YocoEndpointConfig(
        name="payments",
        path="/v1/payments/",
        primary_key=["id"],
        incremental_fields=_created_and_updated(),
        default_incremental_field="updated_at",
        partition_key="created_at",
    ),
    "orders": YocoEndpointConfig(
        name="orders",
        path="/v1/orders/",
        primary_key=["id"],
        incremental_fields=_created_and_updated(),
        default_incremental_field="updated_at",
        partition_key="created_at",
    ),
    "refunds": YocoEndpointConfig(
        name="refunds",
        path="/v1/refunds/",
        primary_key=["id"],
        incremental_fields=_created_and_updated(),
        default_incremental_field="updated_at",
        partition_key="created_at",
    ),
    "payouts": YocoEndpointConfig(
        name="payouts",
        path="/v1/payouts/",
        primary_key=["id"],
        incremental_fields=_created_and_updated(),
        default_incremental_field="updated_at",
        partition_key="created_at",
    ),
    "payout_entries": YocoEndpointConfig(
        name="payout_entries",
        path="/v1/payouts/{payout_id}/payout_entries",
        # Yoco calls `id` the unique identifier of the payout entry, but this table aggregates
        # entries from every payout and the docs never claim uniqueness beyond the parent, so
        # the payout id is part of the key.
        primary_key=["payout_id", "id"],
        # No date filters and no timestamp on the entry itself: full refresh, no partitioning.
        fanout=DependentEndpointConfig(
            parent_name="payouts",
            resolve_param="payout_id",
            resolve_field="id",
            # Entries already carry `payout_id`, so nothing needs injecting from the parent.
            include_from_parent=[],
        ),
    ),
    "payment_links": YocoEndpointConfig(
        name="payment_links",
        path="/v1/payment_links/",
        primary_key=["id"],
        incremental_fields=_created_and_updated(),
        default_incremental_field="updated_at",
        partition_key="created_at",
    ),
    "items": YocoEndpointConfig(
        name="items",
        path="/v1/items/",
        primary_key=["id"],
        incremental_fields=_created_and_updated(),
        default_incremental_field="updated_at",
        partition_key="created_at",
    ),
    "item_categories": YocoEndpointConfig(
        name="item_categories",
        path="/v1/item_categories/",
        primary_key=["id"],
        incremental_fields=_created_and_updated(),
        default_incremental_field="updated_at",
        partition_key="created_at",
    ),
    "item_brands": YocoEndpointConfig(
        name="item_brands",
        path="/v1/item_brands/",
        primary_key=["id"],
        incremental_fields=_created_and_updated(),
        default_incremental_field="updated_at",
        partition_key="created_at",
    ),
    "modifier_groups": YocoEndpointConfig(
        name="modifier_groups",
        path="/v1/modifier_groups/",
        primary_key=["id"],
        # Only `created_at` is filterable here — the resource has no `updated_at` at all.
        incremental_fields=[incremental_field("created_at")],
        default_incremental_field="created_at",
        partition_key="created_at",
    ),
    "locations": YocoEndpointConfig(
        name="locations",
        path="/v1/locations/",
        primary_key=["id"],
        # The location object has timestamps but the endpoint takes no date filters, so
        # filtering would happen client side. Full refresh instead.
        partition_key="created_at",
    ),
    "staff": YocoEndpointConfig(
        name="staff",
        path="/v1/staff/",
        primary_key=["id"],
        incremental_fields=_created_and_updated(),
        default_incremental_field="updated_at",
        partition_key="created_at",
    ),
    "card_machines": YocoEndpointConfig(
        name="card_machines",
        path="/v1/card_machines/",
        primary_key=["id"],
        incremental_fields=_created_and_updated(),
        default_incremental_field="updated_at",
        partition_key="created_at",
    ),
}

ENDPOINTS = tuple(YOCO_ENDPOINTS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in YOCO_ENDPOINTS.items()
}
