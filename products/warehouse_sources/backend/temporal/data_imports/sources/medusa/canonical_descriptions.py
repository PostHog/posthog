from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions from the Medusa v2 Admin API reference (https://docs.medusajs.com/api/admin).
# Keyed by the endpoint names in settings.MEDUSA_ENDPOINTS.

_TIMESTAMPS = {
    "created_at": "Date the record was created.",
    "updated_at": "Date the record was last updated.",
    "deleted_at": "Date the record was soft-deleted, if it was.",
}

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "Orders": {
        "description": "A purchase placed in the store, with its items, totals, and fulfillment and payment status.",
        "docs_url": "https://docs.medusajs.com/api/admin#orders",
        "columns": {
            "id": "Unique identifier of the order.",
            "display_id": "Human-readable incrementing order number shown in the admin.",
            "status": "Status of the order, such as pending, completed, or canceled.",
            "email": "Email address associated with the order.",
            "currency_code": "Three-letter ISO currency code of the order.",
            "total": "Total amount of the order, including taxes and shipping.",
            "subtotal": "Order subtotal before taxes and shipping.",
            "tax_total": "Total tax amount on the order.",
            "customer_id": "ID of the customer who placed the order.",
            "region_id": "ID of the region the order was placed in.",
            "sales_channel_id": "ID of the sales channel the order was placed through.",
            **_TIMESTAMPS,
        },
    },
    "DraftOrders": {
        "description": "An order created manually in the admin that has not been completed by a customer.",
        "docs_url": "https://docs.medusajs.com/api/admin#draft-orders",
        "columns": {
            "id": "Unique identifier of the draft order.",
            "display_id": "Human-readable incrementing number of the draft order.",
            "status": "Status of the draft order.",
            "email": "Email address associated with the draft order.",
            "currency_code": "Three-letter ISO currency code of the draft order.",
            "customer_id": "ID of the customer the draft order is for.",
            **_TIMESTAMPS,
        },
    },
    "Products": {
        "description": "A product in the store's catalog, with its options, images, and organization metadata.",
        "docs_url": "https://docs.medusajs.com/api/admin#products",
        "columns": {
            "id": "Unique identifier of the product.",
            "title": "Title of the product.",
            "handle": "URL slug of the product, unique across the store.",
            "status": "Status of the product: draft, proposed, published, or rejected.",
            "description": "Description of the product.",
            "collection_id": "ID of the collection the product belongs to.",
            "type_id": "ID of the product's type.",
            "is_giftcard": "Whether the product is a gift card.",
            **_TIMESTAMPS,
        },
    },
    "ProductVariants": {
        "description": "A purchasable variant of a product, such as a specific size or color, with its own SKU and inventory settings.",
        "docs_url": "https://docs.medusajs.com/api/admin#product-variants",
        "columns": {
            "id": "Unique identifier of the variant.",
            "title": "Title of the variant.",
            "sku": "Stock keeping unit of the variant.",
            "barcode": "Barcode of the variant.",
            "product_id": "ID of the product the variant belongs to.",
            "allow_backorder": "Whether the variant can be ordered while out of stock.",
            "manage_inventory": "Whether Medusa tracks inventory for the variant.",
            **_TIMESTAMPS,
        },
    },
    "Customers": {
        "description": "A customer of the store, registered or created from a guest checkout.",
        "docs_url": "https://docs.medusajs.com/api/admin#customers",
        "columns": {
            "id": "Unique identifier of the customer.",
            "email": "Email address of the customer.",
            "first_name": "First name of the customer.",
            "last_name": "Last name of the customer.",
            "phone": "Phone number of the customer.",
            "company_name": "Company name of the customer.",
            "has_account": "Whether the customer registered an account, rather than checking out as a guest.",
            **_TIMESTAMPS,
        },
    },
    "CustomerGroups": {
        "description": "A named group of customers, used to target promotions and price lists.",
        "docs_url": "https://docs.medusajs.com/api/admin#customer-groups",
        "columns": {
            "id": "Unique identifier of the customer group.",
            "name": "Name of the customer group.",
            **_TIMESTAMPS,
        },
    },
    "Regions": {
        "description": "A region the store sells in, defining its currency and countries.",
        "docs_url": "https://docs.medusajs.com/api/admin#regions",
        "columns": {
            "id": "Unique identifier of the region.",
            "name": "Name of the region.",
            "currency_code": "Three-letter ISO currency code used in the region.",
            "automatic_taxes": "Whether taxes are calculated automatically in the region.",
            **_TIMESTAMPS,
        },
    },
    "PriceLists": {
        "description": "A set of prices that override default prices, for a sale or an override scoped to customer groups.",
        "docs_url": "https://docs.medusajs.com/api/admin#price-lists",
        "columns": {
            "id": "Unique identifier of the price list.",
            "title": "Title of the price list.",
            "description": "Description of the price list.",
            "status": "Status of the price list: active or draft.",
            "type": "Type of the price list: sale or override.",
            "starts_at": "Date the price list becomes active.",
            "ends_at": "Date the price list stops being active.",
            **_TIMESTAMPS,
        },
    },
    "Returns": {
        "description": "A return of one or more items from an order.",
        "docs_url": "https://docs.medusajs.com/api/admin#returns",
        "columns": {
            "id": "Unique identifier of the return.",
            "order_id": "ID of the order the items are returned from.",
            "status": "Status of the return.",
            "refund_amount": "Amount refunded for the return.",
            "received_at": "Date the returned items were received.",
            **_TIMESTAMPS,
        },
    },
}
