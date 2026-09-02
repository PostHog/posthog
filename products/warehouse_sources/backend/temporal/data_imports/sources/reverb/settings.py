from dataclasses import field
from typing import Literal, Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Reverb clamps `per_page` to 50 regardless of the value requested (verified against the live
# /api/listings endpoint), so always ask for the max to minimise round trips.
PER_PAGE = 50


def _incremental_fields(field_name: str) -> list[IncrementalField]:
    return [
        {
            "label": field_name,
            "type": IncrementalFieldType.DateTime,
            "field": field_name,
            "field_type": IncrementalFieldType.DateTime,
        },
    ]


@frozen
class ReverbEndpointConfig:
    name: str
    path: str  # path under https://api.reverb.com/api
    response_key: str  # root key of the list in the JSON response
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Stable creation-time field to partition by. None when there's no reliable created_at.
    partition_key: Optional[str] = "created_at"
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: Optional[str] = None
    # Reverb's date-window filters always come in start/end pairs; both must be set for an
    # endpoint to be incremental-capable.
    incremental_start_param: Optional[str] = None
    incremental_end_param: Optional[str] = None
    should_sync_default: bool = True
    page_size: int = PER_PAGE
    # Reverb's own docs describe seller orders as returned "newest first", and no documented
    # sort param lets us force ascending order. Treat incremental endpoints conservatively as
    # descending: the pipeline only commits the incremental watermark once a full sync
    # completes in that mode, which is safe regardless of the API's true internal row order.
    sort_mode: Literal["asc", "desc"] = "asc"


REVERB_ENDPOINTS: dict[str, ReverbEndpointConfig] = {
    "Orders": ReverbEndpointConfig(
        name="Orders",
        path="/my/orders/selling/all",
        response_key="orders",
        primary_keys=["order_number"],
        partition_key="created_at",
        incremental_fields=_incremental_fields("updated_at"),
        default_incremental_field="updated_at",
        incremental_start_param="updated_start_date",
        incremental_end_param="updated_end_date",
        sort_mode="desc",
    ),
    "Listings": ReverbEndpointConfig(
        name="Listings",
        path="/my/listings",
        response_key="listings",
        primary_keys=["id"],
        partition_key="created_at",
        # Reverb's docs document only `sku`/`state` filters for this endpoint, no date window,
        # so it stays full refresh.
    ),
    "Payouts": ReverbEndpointConfig(
        name="Payouts",
        path="/my/payouts",
        response_key="payouts",
        primary_keys=["id"],
        partition_key="created_at",
        incremental_fields=_incremental_fields("created_at"),
        default_incremental_field="created_at",
        incremental_start_param="created_start_date",
        incremental_end_param="created_end_date",
        sort_mode="desc",
    ),
}

ENDPOINTS = tuple(REVERB_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in REVERB_ENDPOINTS.items()
}
