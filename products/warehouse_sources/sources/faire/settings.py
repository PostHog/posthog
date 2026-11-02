from dataclasses import field
from typing import Any, Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

BASE_URL = "https://www.faire.com/external-api/v2"


def _updated_at_incremental_fields() -> list[IncrementalField]:
    return [
        {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.DateTime,
        },
    ]


@frozen
class FaireEndpointConfig:
    name: str
    path: str
    # Root key of the list in the JSON response body. Ignored (and left blank) for a single-object
    # endpoint, where the whole body is the row.
    response_key: str = ""
    is_single_object: bool = False
    supports_incremental: bool = False
    # Query param the API filters on when incremental syncing is enabled.
    incremental_param: str = "updated_at_min"
    # Params always sent on the first (non-cursor) page, e.g. a sort order.
    static_params: dict[str, Any] = field(default_factory=dict)
    # Query params the API rejects once a page carries a `cursor` — the first page sets these to
    # pick the initial window (filters, sort), later pages continue purely by cursor.
    filter_params: tuple[str, ...] = ()
    page_size: int = 50
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Stable creation-time field to partition by. None for the single-row Brand endpoint.
    partition_key: Optional[str] = "created_at"
    incremental_fields: list[IncrementalField] = field(default_factory=list)


FAIRE_ENDPOINTS: dict[str, FaireEndpointConfig] = {
    "Orders": FaireEndpointConfig(
        name="Orders",
        path="/orders",
        response_key="orders",
        supports_incremental=True,
        incremental_param="updated_at_min",
        # Faire's default order isn't documented explicitly; pin it so pagination is stable
        # regardless.
        static_params={"sort_by": "UPDATED_AT"},
        filter_params=(
            "updated_at_min",
            "created_at_min",
            "excluded_states",
            "ship_after_max",
            "sort_by",
            "original_order_id",
        ),
        page_size=50,  # Faire caps the orders page size at 50.
        incremental_fields=_updated_at_incremental_fields(),
    ),
    "Products": FaireEndpointConfig(
        name="Products",
        path="/products",
        response_key="products",
        supports_incremental=True,
        incremental_param="updated_at_min",
        filter_params=("updated_at_min", "sku", "include_deleted"),
        page_size=250,
        incremental_fields=_updated_at_incremental_fields(),
    ),
    "Brand": FaireEndpointConfig(
        name="Brand",
        path="/brands/profile",
        is_single_object=True,
        primary_keys=["brand_id"],
        partition_key=None,
    ),
}

ENDPOINTS = tuple(FAIRE_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in FAIRE_ENDPOINTS.items()
}
