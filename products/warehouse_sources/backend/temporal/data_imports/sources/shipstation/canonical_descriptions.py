"""Canonical, documentation-sourced descriptions for ShipStation endpoints and columns.

Sourced from the official ShipStation v1 API reference (https://www.shipstation.com/docs/api/).
Keyed by the resource names in `settings.py` `SHIPSTATION_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced ShipStation table. Note: ShipStation v1 returns all DateTime
values in US Pacific time, not UTC. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "orders": {
        "description": "A customer order imported from a connected selling channel and managed in ShipStation.",
        "docs_url": "https://www.shipstation.com/docs/api/orders/list-orders/",
        "columns": {
            "orderId": "Unique system-generated identifier for the order.",
            "orderNumber": "User-facing order number from the selling channel.",
            "orderKey": "Unique key used to reference the order across systems.",
            "orderStatus": "Status of the order (e.g. awaiting_shipment, shipped, cancelled).",
            "orderDate": "Date the order was placed.",
            "createDate": "Date the order was created in ShipStation.",
            "modifyDate": "Date the order was last modified in ShipStation.",
            "shipDate": "Date the order was shipped.",
            "customerId": "ID of the customer who placed the order.",
            "customerEmail": "Email address of the customer.",
            "orderTotal": "Total monetary value of the order.",
            "amountPaid": "Amount the customer has paid for the order.",
            "shippingAmount": "Shipping amount charged for the order.",
            "storeId": "ID of the store (selling channel) the order came from.",
            "billTo": "Billing address for the order.",
            "shipTo": "Shipping address for the order.",
            "items": "Line items included in the order.",
        },
    },
    "shipments": {
        "description": "A shipment created in ShipStation for an order, including tracking and cost details.",
        "docs_url": "https://www.shipstation.com/docs/api/shipments/list/",
        "columns": {
            "shipmentId": "Unique identifier for the shipment.",
            "orderId": "ID of the order this shipment fulfills.",
            "orderNumber": "Order number associated with the shipment.",
            "createDate": "Date the shipment was created.",
            "shipDate": "Date the shipment was shipped.",
            "trackingNumber": "Carrier tracking number for the shipment.",
            "carrierCode": "Code identifying the shipping carrier.",
            "serviceCode": "Code identifying the shipping service used.",
            "shipmentCost": "Cost of the shipment.",
            "voided": "Whether the shipment label was voided.",
            "customerEmail": "Email address of the customer.",
            "shipTo": "Destination shipping address.",
            "weight": "Weight of the shipment.",
        },
    },
    "fulfillments": {
        "description": "A fulfillment record for an order shipped outside ShipStation (e.g. by a third party).",
        "docs_url": "https://www.shipstation.com/docs/api/fulfillments/list/",
        "columns": {
            "fulfillmentId": "Unique identifier for the fulfillment.",
            "orderId": "ID of the order this fulfillment relates to.",
            "orderNumber": "Order number associated with the fulfillment.",
            "createDate": "Date the fulfillment was created.",
            "shipDate": "Date the fulfillment was shipped.",
            "trackingNumber": "Carrier tracking number for the fulfillment.",
            "carrierCode": "Code identifying the shipping carrier.",
            "fulfillmentProviderCode": "Code identifying the fulfillment provider.",
            "voided": "Whether the fulfillment was voided.",
            "customerEmail": "Email address of the customer.",
            "shipTo": "Destination shipping address.",
        },
    },
    "products": {
        "description": "A product in the ShipStation catalog, used on order line items.",
        "docs_url": "https://www.shipstation.com/docs/api/products/list/",
        "columns": {
            "productId": "Unique identifier for the product.",
            "sku": "Stock keeping unit identifying the product.",
            "name": "Name of the product.",
            "price": "Price of the product.",
            "weightOz": "Weight of the product in ounces.",
            "active": "Whether the product is active.",
            "createDate": "Date the product was created.",
            "modifyDate": "Date the product was last modified.",
        },
    },
    "customers": {
        "description": "A customer record aggregated from orders in ShipStation.",
        "docs_url": "https://www.shipstation.com/docs/api/customers/list/",
        "columns": {
            "customerId": "Unique identifier for the customer.",
            "name": "Name of the customer.",
            "email": "Email address of the customer.",
            "addressVerified": "Whether the customer's address has been verified.",
            "createDate": "Date the customer record was created.",
            "modifyDate": "Date the customer record was last modified.",
            "city": "City portion of the customer's address.",
            "countryCode": "Country code of the customer's address.",
        },
    },
    "stores": {
        "description": "A connected selling channel (store) that orders are imported from.",
        "docs_url": "https://www.shipstation.com/docs/api/stores/list/",
        "columns": {
            "storeId": "Unique identifier for the store.",
            "storeName": "Name of the store.",
            "marketplaceId": "ID of the marketplace the store belongs to.",
            "marketplaceName": "Name of the marketplace the store belongs to.",
            "active": "Whether the store is active.",
            "createDate": "Date the store connection was created.",
            "modifyDate": "Date the store connection was last modified.",
        },
    },
    "warehouses": {
        "description": "A ship-from location (warehouse) configured in ShipStation.",
        "docs_url": "https://www.shipstation.com/docs/api/warehouses/list/",
        "columns": {
            "warehouseId": "Unique identifier for the warehouse.",
            "warehouseName": "Name of the warehouse.",
            "originAddress": "Origin (ship-from) address of the warehouse.",
            "returnAddress": "Return address associated with the warehouse.",
            "isDefault": "Whether this is the default warehouse.",
            "createDate": "Date the warehouse was created.",
        },
    },
}
