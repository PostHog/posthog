from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions sourced from the inFlow Inventory Cloud API docs (https://cloudapi.inflowinventory.com/docs).
# Partial coverage is fine — uncovered columns fall back to LLM enrichment.
_DOCS_URL = "https://cloudapi.inflowinventory.com/docs"

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "products": {
        "description": "A product (inventory item) tracked in inFlow Inventory.",
        "docs_url": _DOCS_URL,
        "columns": {
            "productId": "The unique ID of the product.",
            "name": "The product name.",
            "sku": "The product's stock keeping unit (SKU).",
            "description": "A description of the product.",
            "itemType": "The type of item (e.g. stocked product, service, or non-stocked).",
            "isActive": "Whether the product is active.",
            "defaultPrice": "The default sales price of the product.",
            "cost": "The cost of the product.",
            "barcode": "The product's barcode value.",
            "categoryId": "The ID of the category the product belongs to.",
            "timestamp": "The row version timestamp used for change tracking.",
        },
    },
    "customers": {
        "description": "A customer in inFlow Inventory that sales orders are placed for.",
        "docs_url": _DOCS_URL,
        "columns": {
            "customerId": "The unique ID of the customer.",
            "name": "The customer name.",
            "email": "The customer's primary email address.",
            "phone": "The customer's phone number.",
            "remarks": "Free-text remarks recorded against the customer.",
            "isActive": "Whether the customer is active.",
            "defaultCarrier": "The default shipping carrier for the customer.",
            "defaultPaymentTerms": "The default payment terms for the customer.",
            "timestamp": "The row version timestamp used for change tracking.",
        },
    },
    "vendors": {
        "description": "A vendor (supplier) that purchase orders are placed with in inFlow Inventory.",
        "docs_url": _DOCS_URL,
        "columns": {
            "vendorId": "The unique ID of the vendor.",
            "name": "The vendor name.",
            "email": "The vendor's primary email address.",
            "phone": "The vendor's phone number.",
            "remarks": "Free-text remarks recorded against the vendor.",
            "isActive": "Whether the vendor is active.",
            "defaultCarrier": "The default shipping carrier for the vendor.",
            "defaultPaymentTerms": "The default payment terms for the vendor.",
            "timestamp": "The row version timestamp used for change tracking.",
        },
    },
    "sales_orders": {
        "description": "A sales order recording products sold to a customer.",
        "docs_url": _DOCS_URL,
        "columns": {
            "salesOrderId": "The unique ID of the sales order.",
            "orderNumber": "The human-readable order number.",
            "customerId": "The ID of the customer the order is for.",
            "orderDate": "The date the order was placed.",
            "orderStatus": "The current status of the order.",
            "total": "The total value of the order.",
            "subTotal": "The order subtotal before tax and shipping.",
            "currencyCode": "The currency the order is denominated in.",
            "lines": "The line items on the order.",
            "timestamp": "The row version timestamp used for change tracking.",
        },
    },
    "purchase_orders": {
        "description": "A purchase order recording products bought from a vendor.",
        "docs_url": _DOCS_URL,
        "columns": {
            "purchaseOrderId": "The unique ID of the purchase order.",
            "orderNumber": "The human-readable order number.",
            "vendorId": "The ID of the vendor the order is placed with.",
            "orderDate": "The date the order was placed.",
            "orderStatus": "The current status of the order.",
            "total": "The total value of the order.",
            "subTotal": "The order subtotal before tax and shipping.",
            "currencyCode": "The currency the order is denominated in.",
            "lines": "The line items on the order.",
            "timestamp": "The row version timestamp used for change tracking.",
        },
    },
}
