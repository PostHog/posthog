from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_DOCS = "https://api.bol.com/retailer/public/Retailer-API/"

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "order_items": {
        "description": "One line of an order placed on bol.com for the seller's offers.",
        "docs_url": f"{_DOCS}v10/functional/retailer-api/orders-shipments.html",
        "columns": {
            "orderId": "The order the item belongs to.",
            "orderPlacedDateTime": "When the customer placed the order.",
            "orderItemId": "Identifier of the order item.",
            "ean": "EAN of the ordered product.",
            "fulfilmentMethod": "Whether the seller (FBR) or bol (FBB) ships the item.",
            "fulfilmentStatus": "Whether the item is still open or handled.",
            "quantity": "Units ordered.",
            "quantityShipped": "Units shipped so far.",
            "quantityCancelled": "Units cancelled.",
            "cancellationRequest": "Whether the customer asked to cancel the item.",
            "latestChangedDateTime": "When the item last changed. Used for incremental sync.",
        },
    },
    "shipments": {
        "description": "A shipment of order items. The API lists the last three months.",
        "docs_url": f"{_DOCS}v10/functional/retailer-api/orders-shipments.html",
        "columns": {
            "shipmentId": "Unique identifier of the shipment.",
            "shipmentDateTime": "When the shipment was made.",
            "shipmentReference": "The seller's own reference for the shipment.",
            "order": "The order the shipment belongs to.",
            "shipmentItems": "The order items in the shipment.",
            "transport": "Carrier and track-and-trace details.",
        },
    },
    "returns": {
        "description": "A customer return of one or more order items.",
        "docs_url": f"{_DOCS}v10/functional/retailer-api/returns.html",
        "columns": {
            "returnId": "Unique identifier of the return.",
            "registrationDateTime": "When the return was registered.",
            "fulfilmentMethod": "Whether the seller (FBR) or bol (FBB) handles the return.",
            "returnItems": "The returned items, each with its order, EAN, quantity and handling state.",
        },
    },
    "inventory": {
        "description": "Stock the seller keeps in bol's warehouses (fulfilment by bol), one row per product.",
        "docs_url": f"{_DOCS}v10/functional/retailer-api/inventory-shipments-fbb.html",
        "columns": {
            "ean": "EAN of the product.",
            "bsku": "bol's stock keeping unit for the product.",
            "title": "Product title.",
            "regularStock": "Units in sellable condition.",
            "gradedStock": "Units in graded (second-hand) condition.",
        },
    },
    "invoices": {
        "description": "An invoice bol issued to the seller, such as the monthly sales invoice or an advertising invoice.",
        "docs_url": f"{_DOCS}v10/functional/retailer-api/invoices.html",
        "columns": {
            "invoiceId": "Unique identifier of the invoice.",
            "issueDate": "When bol issued the invoice.",
            "invoiceType": "ALL_IN_ONE for the seller invoice or ADVERTISING_VIA_BOL for an advertising invoice.",
        },
    },
    "offers": {
        "description": "An offer the seller lists on bol.com for a product.",
        "docs_url": f"{_DOCS}v11/functional/offer-api/offer-api.html",
        "columns": {
            "offerId": "Unique identifier of the offer.",
            "ean": "EAN of the product the offer is for.",
            "reference": "The seller's own reference for the offer.",
            "lastModifiedDateTime": "When the offer last changed. Used for incremental sync.",
        },
    },
}
