from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Resources a user is likely to want from a BigCommerce store. BigCommerce is mid-migration
# from its legacy V2 REST API to V3: catalog resources and customers already have V3
# equivalents, but core order objects are still V2-only (BigCommerce has never shipped a V3
# replacement for `/v2/orders`), so orders stays on the legacy API.
ENDPOINTS = (
    "products",
    "categories",
    "brands",
    "customers",
    "orders",
)

# Schema/endpoint name -> BigCommerce REST API path (relative to
# `https://api.bigcommerce.com/stores/{store_hash}`).
ENDPOINT_PATHS: dict[str, str] = {
    "products": "/v3/catalog/products",
    "categories": "/v3/catalog/categories",
    "brands": "/v3/catalog/brands",
    "customers": "/v3/customers",
    "orders": "/v2/orders",
}

# Endpoints still served by the legacy V2 API: no `data` envelope, no `meta.pagination`,
# and a different incremental filter param + date format than V3.
V2_ENDPOINTS = frozenset({"orders"})

# Categories and brands carry no modification timestamp in either API version, so they're
# full refresh only. Products, customers and orders all expose a genuine server-side
# "modified since" filter.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    endpoint: [
        {
            "label": "date_modified",
            "type": IncrementalFieldType.DateTime,
            "field": "date_modified",
            "field_type": IncrementalFieldType.DateTime,
        }
    ]
    for endpoint in ("products", "customers", "orders")
}

# Stable creation-time field to partition on, per endpoint. Categories and brands have no
# creation timestamp field and are left unpartitioned.
PARTITION_FIELDS: dict[str, str] = {
    "products": "date_created",
    "customers": "date_created",
    "orders": "date_created",
}
