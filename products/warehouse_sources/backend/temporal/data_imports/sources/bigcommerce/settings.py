from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Resources a user is likely to want from a BigCommerce store. BigCommerce is mid-migration
# from its legacy V2 REST API to V3: catalog resources and customers already have V3
# equivalents, but core order objects are still V2-only (BigCommerce has never shipped a V3
# replacement for `/v2/orders`), so orders stays on the legacy API.
ENDPOINTS = (
    "products",
    "variants",
    "categories",
    "brands",
    "customers",
    "channels",
    "customer_groups",
    "orders",
    "order_statuses",
    "order_products",
    "order_shipments",
    "order_transactions",
    "refunds",
)

# Schema/endpoint name -> BigCommerce REST API path (relative to
# `https://api.bigcommerce.com/stores/{store_hash}`).
ENDPOINT_PATHS: dict[str, str] = {
    "products": "/v3/catalog/products",
    "variants": "/v3/catalog/variants",
    "categories": "/v3/catalog/categories",
    "brands": "/v3/catalog/brands",
    "customers": "/v3/customers",
    "channels": "/v3/channels",
    "customer_groups": "/v2/customer_groups",
    "orders": "/v2/orders",
    "order_statuses": "/v2/order_statuses",
    "order_products": "/v2/orders/{order_id}/products",
    "order_shipments": "/v2/orders/{order_id}/shipments",
    "order_transactions": "/v3/orders/{order_id}/transactions",
    "refunds": "/v3/orders/payment_actions/refunds",
}

# Endpoints still served by the legacy V2 API: no `data` envelope, no `meta.pagination`,
# and a different incremental filter param + date format than V3.
V2_ENDPOINTS = frozenset({"customer_groups", "orders", "order_statuses", "order_products", "order_shipments"})

# Order statuses is a fixed list of BigCommerce's order states with no `page`/`limit` params.
UNPAGINATED_ENDPOINTS = frozenset({"order_statuses"})

# Endpoints read per order, because BigCommerce has no collection endpoint for them.
ORDER_FAN_OUT_ENDPOINTS = frozenset({"order_products", "order_shipments", "order_transactions"})

# Endpoint -> (server-side "since" filter param, cursor field it filters on). Categories, brands,
# variants, customer groups and order statuses carry no modification timestamp, and the per-order
# endpoints have no filter, so those are full refresh only.
INCREMENTAL_FILTERS: dict[str, tuple[str, str]] = {
    "products": ("date_modified:min", "date_modified"),
    "customers": ("date_modified:min", "date_modified"),
    "channels": ("date_modified:min", "date_modified"),
    "orders": ("min_date_modified", "date_modified"),
    # Refunds are never modified after creation, so their creation time is the cursor.
    "refunds": ("created:min", "created"),
}

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    endpoint: [
        {
            "label": field,
            "type": IncrementalFieldType.DateTime,
            "field": field,
            "field_type": IncrementalFieldType.DateTime,
        }
    ]
    for endpoint, (_, field) in INCREMENTAL_FILTERS.items()
}

# Per-order rows are read one order at a time. The order id joins the key so it stays unique
# table-wide even if a store reuses child ids across orders.
PRIMARY_KEYS: dict[str, list[str]] = {
    "order_products": ["order_id", "id"],
    "order_shipments": ["order_id", "id"],
    "order_transactions": ["order_id", "id"],
}

# Stable creation-time field to partition on, per endpoint. Categories, brands, variants,
# customer groups, order statuses and order products have no creation timestamp field and are
# left unpartitioned.
PARTITION_FIELDS: dict[str, str] = {
    "products": "date_created",
    "customers": "date_created",
    "channels": "date_created",
    "orders": "date_created",
    "order_shipments": "date_created",
    "order_transactions": "date_created",
    "refunds": "created",
}
