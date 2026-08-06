from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions taken from the official Squarespace Commerce + Website API docs.
# Keyed by the endpoint/schema name returned by `get_schemas`.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "orders": {
        "description": "Commerce orders placed on the Squarespace store, including totals, "
        "line items, and fulfillment status.",
        "docs_url": "https://developers.squarespace.com/commerce-apis/retrieve-all-orders",
        "columns": {
            "id": "Unique order id.",
            "orderNumber": "Human-readable order number shown to the merchant and customer.",
            "createdOn": "ISO 8601 UTC timestamp of when the order was placed.",
            "modifiedOn": "ISO 8601 UTC timestamp of when the order was last modified.",
            "channel": "Sales channel the order was placed through (e.g. web, pos).",
            "fulfillmentStatus": "Fulfillment state: PENDING, FULFILLED, or CANCELED.",
            "customerEmail": "Email address of the customer who placed the order.",
            "customerId": "Identifier of the customer profile, when available.",
            "grandTotal": "Order total including tax and shipping.",
            "subtotal": "Order subtotal before tax, shipping, and discounts.",
            "taxTotal": "Total tax charged on the order.",
            "shippingTotal": "Total shipping charged on the order.",
            "discountTotal": "Total discount applied to the order.",
            "refundedTotal": "Total amount refunded against the order.",
            "lineItems": "Items purchased in the order.",
            "billingAddress": "Billing address supplied for the order.",
            "shippingAddress": "Shipping address supplied for the order.",
            "testmode": "Whether the order was created in test mode.",
        },
    },
    "products": {
        "description": "Products in the Squarespace store (physical, service, gift card, and "
        "digital), including pricing variants and images.",
        "docs_url": "https://developers.squarespace.com/commerce-apis/retrieve-all-products",
        "columns": {
            "id": "Unique product id.",
            "createdOn": "ISO 8601 UTC timestamp of when the product was created.",
            "modifiedOn": "ISO 8601 UTC timestamp of when the product was last modified.",
            "type": "Product type: PHYSICAL, SERVICE, GIFT_CARD, or DIGITAL.",
            "storePageId": "Identifier of the store page the product belongs to.",
            "name": "Product name.",
            "description": "Product description (HTML).",
            "url": "Public URL of the product.",
            "urlSlug": "URL slug of the product.",
            "isVisible": "Whether the product is visible on the storefront.",
            "tags": "Tags assigned to the product.",
            "images": "Images associated with the product.",
        },
    },
    "transactions": {
        "description": "Financial transaction documents for orders and donations, grouping the "
        "payments, taxes, and totals for each.",
        "docs_url": "https://developers.squarespace.com/commerce-apis/retrieve-all-transactions",
        "columns": {
            "id": "Unique transaction document id.",
            "createdOn": "ISO 8601 UTC timestamp of when the document was created.",
            "modifiedOn": "ISO 8601 UTC timestamp of when the document was last modified.",
            "customerEmail": "Email address of the customer for the transaction.",
            "salesOrderId": "Identifier of the order this transaction relates to.",
            "voided": "Whether the transaction was voided.",
            "total": "Total amount of the transaction.",
            "totalSales": "Total sales amount.",
            "totalNetSales": "Net sales amount after discounts.",
            "totalTaxes": "Total taxes for the transaction.",
            "totalNetPayment": "Net payment amount received.",
            "payments": "Individual payments that make up the transaction.",
        },
    },
    "inventory": {
        "description": "Stock levels per product variant. Inventory is tracked per variant, not per product.",
        "docs_url": "https://developers.squarespace.com/commerce-apis/retrieve-all-inventory",
        "columns": {
            "variantId": "Product variant id; also the unique id of the inventory item.",
            "sku": "Stock keeping unit (SKU) code assigned by the merchant.",
            "descriptor": "Human-readable descriptor for the variant.",
            "quantity": "Current stock quantity available.",
            "isUnlimited": "Whether the variant has unlimited stock.",
        },
    },
    "store_pages": {
        "description": "Commerce-enabled store pages on the Squarespace site.",
        "docs_url": "https://developers.squarespace.com/commerce-apis/retrieve-all-store-pages",
        "columns": {
            "id": "Unique store page id.",
            "title": "Store page title shown on the merchant site.",
            "isEnabled": "Whether the store page is enabled (accessible to visitors).",
            "urlSlug": "URL slug of the store page.",
        },
    },
    "profiles": {
        "description": "Customer profiles on the Squarespace site, including order/donation summary data.",
        "docs_url": "https://developers.squarespace.com/commerce-apis/retrieve-all-profiles",
        "columns": {
            "id": "Unique profile id.",
            "firstName": "Profile first name.",
            "lastName": "Profile last name.",
            "email": "Profile email address.",
            "hasAccount": "Whether the profile has an account on the website.",
            "isCustomer": "Whether the profile has any commerce orders or donations.",
            "createdOn": "ISO 8601 UTC timestamp of when the profile was created.",
            "acceptsMarketing": "Whether the profile accepts marketing.",
            "address": "Approximate address derived from existing data (not for shipping/billing).",
            "transactionsSummary": "Summary of the profile's orders and donations.",
        },
    },
}
