from dataclasses import dataclass
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Picqer caps every list endpoint at 100 results per page and advances with the `offset`
# query param. There is no `limit`/`per_page` override, so the page size is fixed.
PAGE_SIZE = 100


def _incremental_fields(cursor_field: str) -> list[IncrementalField]:
    # Picqer's server-side time filters key off a single timestamp column per endpoint (the field
    # the `updated_after` filter compares against). Advertise just that column so the user's chosen
    # cursor always matches what the API actually filters on.
    return [
        {
            "label": cursor_field,
            "type": IncrementalFieldType.DateTime,
            "field": cursor_field,
            "field_type": IncrementalFieldType.DateTime,
        },
    ]


@dataclass
class PicqerEndpointConfig:
    name: str
    path: str  # Path under /api/v1, e.g. "/orders"
    primary_keys: list[str]
    # Query param that filters the list by modification time (e.g. `updated_after`). Only set when
    # the API documents a genuine server-side UPDATE-based filter — creation-only filters
    # (`sincedate`) are deliberately left off, since using them as an incremental cursor would miss
    # updates to mutable records. None => full refresh.
    incremental_filter_param: Optional[str] = None
    # Response field the `incremental_filter_param` compares against, and the cursor the pipeline
    # tracks. Must be present in every row so the watermark can advance. None => full refresh.
    incremental_cursor_field: Optional[str] = None
    # Stable creation-time field to partition by (never `updated`, which rewrites partitions on every
    # sync). None when the resource exposes no reliable creation timestamp.
    partition_key: Optional[str] = None
    should_sync_default: bool = True

    @property
    def supports_incremental(self) -> bool:
        return self.incremental_filter_param is not None and self.incremental_cursor_field is not None

    @property
    def incremental_fields(self) -> list[IncrementalField]:
        if self.incremental_cursor_field is None:
            return []
        return _incremental_fields(self.incremental_cursor_field)


PICQER_ENDPOINTS: dict[str, PicqerEndpointConfig] = {
    # Transactional resources. Orders and picklists only expose a creation-date filter (`sincedate`),
    # which cannot catch status updates, so they sync full refresh. Purchase orders and returns
    # expose an `updated_after` ("changed since") filter, so they sync incrementally.
    "orders": PicqerEndpointConfig(
        name="orders",
        path="/orders",
        primary_keys=["idorder"],
        partition_key="created",
    ),
    "picklists": PicqerEndpointConfig(
        name="picklists",
        path="/picklists",
        primary_keys=["idpicklist"],
        partition_key="created",
    ),
    "purchaseorders": PicqerEndpointConfig(
        name="purchaseorders",
        path="/purchaseorders",
        primary_keys=["idpurchaseorder"],
        incremental_filter_param="updated_after",
        incremental_cursor_field="updated",
        partition_key="created",
    ),
    # Receipts document an `updated_after` filter, but the list object's update field isn't confirmed,
    # so this stays full refresh until verified against the live API (see PR notes).
    "receipts": PicqerEndpointConfig(
        name="receipts",
        path="/receipts",
        primary_keys=["idreceipt"],
        partition_key="created",
    ),
    "returns": PicqerEndpointConfig(
        name="returns",
        path="/returns",
        primary_keys=["idreturn"],
        incremental_filter_param="updated_after",
        incremental_cursor_field="updated_at",
        partition_key="created_at",
    ),
    # Catalog / reference resources. Products carry a `created` field but expose no time filter.
    "products": PicqerEndpointConfig(
        name="products",
        path="/products",
        primary_keys=["idproduct"],
        partition_key="created",
    ),
    "customers": PicqerEndpointConfig(
        name="customers",
        path="/customers",
        primary_keys=["idcustomer"],
    ),
    "suppliers": PicqerEndpointConfig(
        name="suppliers",
        path="/suppliers",
        primary_keys=["idsupplier"],
    ),
    "warehouses": PicqerEndpointConfig(
        name="warehouses",
        path="/warehouses",
        primary_keys=["idwarehouse"],
    ),
    "locations": PicqerEndpointConfig(
        name="locations",
        path="/locations",
        primary_keys=["idlocation"],
    ),
    "users": PicqerEndpointConfig(
        name="users",
        path="/users",
        primary_keys=["iduser"],
    ),
    "vatgroups": PicqerEndpointConfig(
        name="vatgroups",
        path="/vatgroups",
        primary_keys=["idvatgroup"],
    ),
    "tags": PicqerEndpointConfig(
        name="tags",
        path="/tags",
        primary_keys=["idtag"],
    ),
}

ENDPOINTS = tuple(PICQER_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in PICQER_ENDPOINTS.items()
}
