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


@dataclass(frozen=True)
class PicqerFanoutConfig:
    # Parent endpoint whose rows drive the child requests, and the parent field substituted into
    # the `{<resolve_field>}` placeholder of the child path.
    parent_name: str
    resolve_field: str


@dataclass(frozen=True)
class PicqerEndpointConfig:
    name: str
    path: str  # Path under /api/v1, e.g. "/orders"
    primary_keys: list[str]
    # Query param that filters the list by modification time (e.g. `updated_after`). Only set when
    # the API documents a genuine server-side UPDATE-based filter — creation-only filters
    # (`sincedate`) are deliberately left off for mutable records, since using them as an
    # incremental cursor would miss updates. Immutable records may use them. None => full refresh.
    incremental_filter_param: Optional[str] = None
    # Response field the `incremental_filter_param` compares against, and the cursor the pipeline
    # tracks. Must be present in every row so the watermark can advance. None => full refresh.
    incremental_cursor_field: Optional[str] = None
    # Stable creation-time field to partition by (never `updated`, which rewrites partitions on every
    # sync). None when the resource exposes no reliable creation timestamp.
    partition_key: Optional[str] = None
    should_sync_default: bool = True
    # False for list endpoints the docs do not mark as paginated. An offset loop on an endpoint that
    # ignores `offset` would fetch the same full page forever.
    paginated: bool = True
    fanout: Optional[PicqerFanoutConfig] = None

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
    # Batches change status as picking completes and expose no time filter.
    "picklist_batches": PicqerEndpointConfig(
        name="picklist_batches",
        path="/picklists/batches",
        primary_keys=["idpicklist_batch"],
        partition_key="created_at",
    ),
    # Backorders change as stock is reserved and disappear once processed, so only a full refresh
    # reflects the current set. `sincedate` filters by creation and would miss both.
    "backorders": PicqerEndpointConfig(
        name="backorders",
        path="/backorders",
        primary_keys=["idbackorder"],
        partition_key="created_at",
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
    # Shipments can be cancelled after creation and only expose a creation-date filter
    # (`sincedate`), so they sync full refresh like orders and picklists.
    "shipments": PicqerEndpointConfig(
        name="shipments",
        path="/shipments",
        primary_keys=["idshipment"],
        partition_key="created",
    ),
    # Stock history rows can never be changed, so the creation-date filter is a safe cursor.
    "stockhistory": PicqerEndpointConfig(
        name="stockhistory",
        path="/stockhistory",
        primary_keys=["idproduct_stock_history"],
        incremental_filter_param="sincedate",
        incremental_cursor_field="changed_at",
        partition_key="changed_at",
    ),
    # Current stock per product per warehouse. Fanned out over warehouses rather than products,
    # because a warehouse returns all of its products in pages of 100.
    "warehouse_stock": PicqerEndpointConfig(
        name="warehouse_stock",
        path="/warehouses/{idwarehouse}/stock",
        primary_keys=["idwarehouse", "idproduct"],
        fanout=PicqerFanoutConfig(parent_name="warehouses", resolve_field="idwarehouse"),
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
    "return_reasons": PicqerEndpointConfig(
        name="return_reasons",
        path="/return_reasons",
        primary_keys=["idreturn_reason"],
        paginated=False,
    ),
    "return_statuses": PicqerEndpointConfig(
        name="return_statuses",
        path="/return_statuses",
        primary_keys=["idreturn_status"],
        paginated=False,
    ),
    "pricelists": PicqerEndpointConfig(
        name="pricelists",
        path="/pricelists",
        primary_keys=["idpricelist"],
    ),
}

ENDPOINTS = tuple(PICQER_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in PICQER_ENDPOINTS.items()
}
