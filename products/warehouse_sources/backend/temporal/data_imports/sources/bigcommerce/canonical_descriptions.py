"""Canonical, documentation-sourced descriptions for BigCommerce endpoints and columns.

Sourced from the official BigCommerce REST API reference
(https://developer.bigcommerce.com/api-reference). Keyed by the resource names in
`settings.py` `ENDPOINTS`, which match the `ExternalDataSchema.name` of a synced
BigCommerce table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "products": {
        "description": "A product listed for sale in the BigCommerce catalog.",
        "docs_url": "https://developer.bigcommerce.com/docs/rest-catalog/products",
        "columns": {
            "id": "Unique identifier for the product.",
            "name": "Product name.",
            "sku": "Stock keeping unit (SKU) of the product.",
            "type": "Product type: `physical` or `digital`.",
            "price": "Base price of the product, excluding tax.",
            "cost_price": "Cost price of the product, for internal reporting.",
            "retail_price": "Suggested retail price (MSRP) of the product.",
            "sale_price": "Sale price of the product, if on sale.",
            "weight": "Weight of the product, in the store's configured weight unit.",
            "inventory_level": "Current stock level, when inventory tracking is enabled.",
            "inventory_tracking": "How inventory is tracked: `none`, `product`, or `variant`.",
            "brand_id": "Identifier of the brand this product belongs to, if any.",
            "categories": "Identifiers of the categories this product is assigned to.",
            "is_visible": "Whether the product is visible on the storefront.",
            "is_featured": "Whether the product is marked as featured.",
            "date_created": "Date and time the product was created.",
            "date_modified": "Date and time the product was last modified.",
            "availability": "Availability status: `available`, `disabled`, or `preorder`.",
            "condition": "Condition of the product: `New`, `Used`, or `Refurbished`.",
        },
    },
    "categories": {
        "description": "A category used to organize products in the storefront navigation.",
        "docs_url": "https://developer.bigcommerce.com/docs/rest-catalog/catalog-categories",
        "columns": {
            "id": "Unique identifier for the category.",
            "parent_id": "Identifier of the parent category, or 0 for a top-level category.",
            "name": "Category name.",
            "description": "Category description, which may contain HTML.",
            "views": "Number of times the category page has been viewed.",
            "sort_order": "Position of the category relative to its siblings.",
            "is_visible": "Whether the category is visible on the storefront.",
            "custom_url": "Custom URL path for the category page.",
        },
    },
    "brands": {
        "description": "A brand that products in the catalog can be assigned to.",
        "docs_url": "https://developer.bigcommerce.com/docs/rest-catalog/catalog-brands",
        "columns": {
            "id": "Unique identifier for the brand.",
            "name": "Brand name.",
            "page_title": "Title shown in the browser tab for the brand's storefront page.",
            "meta_description": "Meta description used for the brand's storefront page.",
            "search_keywords": "Comma-separated keywords used for on-site search.",
            "custom_url": "Custom URL path for the brand page.",
        },
    },
    "customers": {
        "description": "A registered customer account on the storefront.",
        "docs_url": "https://developer.bigcommerce.com/docs/rest-management/customers",
        "columns": {
            "id": "Unique identifier for the customer.",
            "email": "Customer's email address.",
            "first_name": "Customer's first name.",
            "last_name": "Customer's last name.",
            "company": "Company name associated with the customer.",
            "phone": "Customer's phone number.",
            "customer_group_id": "Identifier of the customer group this customer belongs to.",
            "notes": "Internal notes about the customer.",
            "tax_exempt_category": "Tax exemption category applied to the customer, if any.",
            "date_created": "Date and time the customer account was created.",
            "date_modified": "Date and time the customer account was last modified.",
            "registration_ip_address": "IP address the customer used when registering.",
            "store_credit_amounts": "Store credit balances held by the customer.",
        },
    },
    "orders": {
        "description": "A customer order placed on the store.",
        "docs_url": "https://developer.bigcommerce.com/docs/rest-management/orders",
        "columns": {
            "id": "Unique identifier for the order.",
            "customer_id": "Identifier of the customer who placed the order, or 0 for a guest order.",
            "status": "Human-readable order status (e.g. `Awaiting Fulfillment`, `Shipped`).",
            "status_id": "Numeric identifier of the order status.",
            "date_created": "Date and time the order was created.",
            "date_modified": "Date and time the order was last modified.",
            "date_shipped": "Date and time the order was shipped, if applicable.",
            "subtotal_ex_tax": "Order subtotal, excluding tax.",
            "subtotal_inc_tax": "Order subtotal, including tax.",
            "total_ex_tax": "Order total, excluding tax.",
            "total_inc_tax": "Order total, including tax.",
            "total_tax": "Total tax charged on the order.",
            "total_shipping": "Total shipping cost charged on the order.",
            "currency_code": "Three-letter ISO currency code of the order.",
            "payment_method": "Payment method used for the order.",
            "payment_status": "Status of payment collection for the order.",
            "items_total": "Total number of items in the order.",
            "is_deleted": "Whether the order has been deleted.",
        },
    },
}
