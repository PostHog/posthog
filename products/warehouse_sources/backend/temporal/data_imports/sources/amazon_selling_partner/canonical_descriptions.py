"""Canonical, documentation-sourced descriptions for Amazon Selling Partner endpoints and columns.

Sourced from the official Selling Partner API reference
(https://developer-docs.amazon.com/sp-api/). Keyed by the endpoint names in `settings.py`
`AMAZON_SELLING_PARTNER_ENDPOINTS`, which match the `ExternalDataSchema.name` of a synced table.
Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "orders": {
        "description": "An order placed on one of your Amazon marketplaces, as returned by the Orders API.",
        "docs_url": "https://developer-docs.amazon.com/sp-api/docs/orders-api-v0-reference",
        "columns": {
            "AmazonOrderId": "Amazon-defined order identifier, in 3-7-7 format.",
            "SellerOrderId": "Seller-defined order identifier, when one was supplied.",
            "PurchaseDate": "Date and time the order was placed.",
            "LastUpdateDate": "Date and time the order was last updated.",
            "OrderStatus": "Current order status (e.g. Pending, Unshipped, Shipped, Canceled).",
            "FulfillmentChannel": "Whether the order is fulfilled by Amazon (AFN) or by the seller (MFN).",
            "SalesChannel": "Sales channel of the first item in the order.",
            "ShipServiceLevel": "Shipment service level of the order.",
            "OrderTotal": "Total charged to the buyer, as currency code and amount.",
            "NumberOfItemsShipped": "Number of items shipped.",
            "NumberOfItemsUnshipped": "Number of items not yet shipped.",
            "PaymentMethod": "Payment method used for the order.",
            "MarketplaceId": "Identifier of the marketplace the order was placed in.",
            "BuyerInfo": "Buyer details. Only populated when the app holds an approved restricted role.",
            "ShippingAddress": "Shipping address. Only populated when the app holds an approved restricted role.",
            "IsPrime": "Whether the order is a Prime order.",
            "IsBusinessOrder": "Whether the order is an Amazon Business order.",
            "IsReplacementOrder": "Whether the order is a replacement for another order.",
            "EarliestShipDate": "Start of the promised shipment window.",
            "LatestShipDate": "End of the promised shipment window.",
        },
    },
    "order_items": {
        "description": "A line item on an Amazon order, fanned out from the orders list.",
        "docs_url": "https://developer-docs.amazon.com/sp-api/docs/orders-api-v0-reference#getorderitems",
        "columns": {
            "AmazonOrderId": "Amazon-defined identifier of the order the item belongs to.",
            "OrderItemId": "Amazon-defined identifier of this line item, unique within its order.",
            "ASIN": "Amazon Standard Identification Number of the product ordered.",
            "SellerSKU": "Seller SKU of the product ordered.",
            "Title": "Name of the product ordered.",
            "QuantityOrdered": "Number of units ordered.",
            "QuantityShipped": "Number of units shipped.",
            "ItemPrice": "Selling price of the item, excluding shipping.",
            "ItemTax": "Tax on the item price.",
            "ShippingPrice": "Shipping price of the item.",
            "PromotionDiscount": "Total promotional discount applied to the item.",
            "IsGift": "Whether the item is a gift.",
            "_order_last_update_date": "Last-update timestamp of the parent order. Added by PostHog and used as the incremental cursor.",
            "_order_purchase_date": "Purchase date of the parent order. Added by PostHog and used as the partition key.",
        },
    },
    "financial_transactions": {
        "description": "A financial transaction on your seller account (order payments, refunds, fees, transfers), from the Finances 2024-06-19 API.",
        "docs_url": "https://developer-docs.amazon.com/sp-api/docs/finances-api-v2024-06-19-reference",
        "columns": {
            "transactionId": "Unique identifier of the transaction.",
            "transactionType": "Type of transaction (e.g. Shipment, Refund, Service Fee).",
            "transactionStatus": "Whether the transaction is deferred or released.",
            "postedDate": "Date and time the transaction was posted.",
            "description": "Description of the transaction.",
            "totalAmount": "Net amount of the transaction, as currency code and amount.",
            "marketplaceDetails": "Marketplace the transaction belongs to.",
            "sellingPartnerMetadata": "Selling partner id, marketplace id, and account type for the transaction.",
            "relatedIdentifiers": "Identifiers linking the transaction to other objects, such as an order id.",
            "items": "Per-item breakdown of the transaction.",
            "breakdowns": "Breakdown of the total amount into its component charges and fees.",
            "contexts": "Additional context about the transaction, such as product or payment details.",
        },
    },
    "fba_inventory": {
        "description": "A summary of your Fulfillment by Amazon inventory for one SKU in one marketplace.",
        "docs_url": "https://developer-docs.amazon.com/sp-api/docs/fba-inventory-api-v1-reference",
        "columns": {
            "sellerSku": "Seller SKU of the item.",
            "asin": "Amazon Standard Identification Number of the item.",
            "fnSku": "Fulfillment network SKU of the item.",
            "condition": "Condition of the item.",
            "productName": "Name of the item.",
            "totalQuantity": "Total number of units in inventory across all states.",
            "inventoryDetails": "Breakdown of quantities by fulfillable, inbound, reserved, researching, and unfulfillable state.",
            "lastUpdatedTime": "Date and time the inventory summary was last updated.",
            "stores": "Stores the item is available in.",
            "_marketplace_id": "Marketplace the summary was requested for. Added by PostHog, since the response does not repeat it.",
        },
    },
    "sales_and_traffic": {
        "description": "Daily sales and traffic metrics for your marketplaces, from the GET_SALES_AND_TRAFFIC_REPORT report.",
        "docs_url": "https://developer-docs.amazon.com/sp-api/docs/report-type-values-business",
        "columns": {
            "date": "Day the metrics cover.",
            "salesByDate": "Sales metrics for the day: ordered product sales, units ordered, total order items, and average selling price.",
            "trafficByDate": "Traffic metrics for the day: page views, sessions, buy box percentage, and unit session percentage.",
        },
    },
}
