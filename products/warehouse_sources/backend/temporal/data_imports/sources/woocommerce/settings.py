from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Resources a user is likely to want from a WooCommerce store. Each maps to a
# top-level WooCommerce REST API v3 collection endpoint (relative to
# `/wp-json/wc/v3`). Fan-out resources (product variations, per-order notes and
# refunds) are intentionally left out of this first pass.
ENDPOINTS = (
    "products",
    "orders",
    "coupons",
    "customers",
    "product_categories",
    "product_tags",
    "product_reviews",
    "product_attributes",
    "tax_rates",
    "shipping_zones",
)

# Schema/endpoint name -> WooCommerce REST API path (relative to `/wp-json/wc/v3`).
ENDPOINT_PATHS: dict[str, str] = {
    "products": "/products",
    "orders": "/orders",
    "coupons": "/coupons",
    "customers": "/customers",
    "product_categories": "/products/categories",
    "product_tags": "/products/tags",
    "product_reviews": "/products/reviews",
    "product_attributes": "/products/attributes",
    "tax_rates": "/taxes",
    "shipping_zones": "/shipping/zones",
}

# Only products, orders and coupons expose a genuine server-side `modified_after`
# timestamp filter (added in WooCommerce 5.8.0), so only those advertise
# incremental sync. Everything else is full refresh.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    endpoint: [
        {
            "label": "date_modified_gmt",
            "type": IncrementalFieldType.DateTime,
            "field": "date_modified_gmt",
            "field_type": IncrementalFieldType.DateTime,
        }
    ]
    for endpoint in ("products", "orders", "coupons")
}

# Stable creation-time field to partition on, per endpoint. Endpoints whose
# objects carry no creation timestamp (categories, tags, attributes, tax rates,
# shipping zones) are left unpartitioned.
PARTITION_FIELDS: dict[str, str] = {
    "products": "date_created_gmt",
    "orders": "date_created_gmt",
    "coupons": "date_created_gmt",
    "customers": "date_created_gmt",
    "product_reviews": "date_created_gmt",
}
