from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class ChargedeskEndpointConfig:
    name: str
    path: str
    primary_keys: list[str]
    # Response column holding a stable epoch-second creation timestamp. Used for partitioning, for the
    # incremental watermark, and as the upper bound when window-shifting past the offset cap. Never a
    # mutable "last edited" field — those rewrite partitions on every sync.
    timestamp_field: str
    # Base name of the bracketed server-side range filter (e.g. `occurred` -> occurred[min]/occurred[max]).
    # This is NOT always the same as `timestamp_field`: subscriptions/products filter on `created` but the
    # only timestamp the response carries is `first_seen`.
    filter_param: str
    # The API rejects an `offset` past this value (charges/customers cap at 50,000, subscriptions/products
    # at 10,000). When pagination approaches it we reset the offset and tighten the `[max]` time window to
    # the oldest row seen so far, as the docs recommend.
    max_offset: int
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    page_size: int = 500  # documented maximum for the `count` param
    supports_incremental: bool = True


def _epoch_incremental_field(field_name: str) -> IncrementalField:
    # ChargeDesk timestamps are Unix epoch seconds stored as integers, so the merge cursor is compared
    # as an integer even though it represents a datetime.
    return {
        "label": field_name,
        "type": IncrementalFieldType.DateTime,
        "field": field_name,
        "field_type": IncrementalFieldType.Integer,
    }


CHARGEDESK_ENDPOINTS: dict[str, ChargedeskEndpointConfig] = {
    "charges": ChargedeskEndpointConfig(
        name="charges",
        path="/charges",
        primary_keys=["charge_id"],
        timestamp_field="occurred",
        filter_param="occurred",
        max_offset=50000,
        incremental_fields=[_epoch_incremental_field("occurred")],
    ),
    "customers": ChargedeskEndpointConfig(
        name="customers",
        path="/customers",
        primary_keys=["customer_id"],
        timestamp_field="first_seen",
        filter_param="first_seen",
        max_offset=50000,
        incremental_fields=[_epoch_incremental_field("first_seen")],
    ),
    "subscriptions": ChargedeskEndpointConfig(
        name="subscriptions",
        path="/subscriptions",
        primary_keys=["subscription_id"],
        timestamp_field="first_seen",
        # Subscriptions expose `created[min]/created[max]` server-side, but the only timestamp on the row
        # is `first_seen` (the creation time). They track the same moment, so we watermark on `first_seen`
        # and send its value as `created[min]`.
        filter_param="created",
        max_offset=10000,
        incremental_fields=[_epoch_incremental_field("first_seen")],
    ),
    "products": ChargedeskEndpointConfig(
        name="products",
        path="/products",
        primary_keys=["product_id"],
        timestamp_field="first_seen",
        filter_param="created",
        max_offset=10000,
        # Products are a small, mutable catalog with no useful append-only cursor, so we full-refresh them
        # every sync (matching the canonical Airbyte connector). The `created[*]` filter still bounds the
        # window-shift when an account somehow has more than 10,000 products.
        supports_incremental=False,
    ),
}

ENDPOINTS = tuple(CHARGEDESK_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: cfg.incremental_fields for name, cfg in CHARGEDESK_ENDPOINTS.items() if cfg.supports_incremental
}
