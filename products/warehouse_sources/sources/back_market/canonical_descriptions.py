"""Back Market table descriptions. The API schema is at https://api.backmarket.dev/bundled_openapi.yaml."""

from products.warehouse_sources.sources.sdk import CanonicalDescriptions

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "orders": {
        "description": "A customer order placed on the Back Market marketplace, including its order lines.",
        "docs_url": "https://api.backmarket.dev/",
        "columns": {
            "order_id": "Unique identifier for the order.",
            "date_creation": "Time at which the order was created.",
            "date_modification": "Time at which the order was last modified.",
            "state": "The order's current status code.",
        },
    },
    "listings": {
        "description": "A product listing (offer) you have for sale on Back Market — its SKU, price, and stock.",
        "docs_url": "https://api.backmarket.dev/",
        "columns": {
            "listing_id": "Unique identifier for the listing.",
            "sku": "Your merchant SKU for the listed product.",
            "price": "The listing's current sale price.",
            "publication_state": "Whether the listing is published, unpublished, or paused.",
        },
    },
    "backbox_competitors": {
        "description": "A snapshot of Backbox competitors for each seller listing and market.",
        "docs_url": "https://api.backmarket.dev/bundled_openapi.yaml",
        "columns": {
            "_listings_id": "UUID of the seller listing used to request competitors.",
            "listing_id": "UUID of the competing listing.",
            "market": "Market of the Backbox.",
            "is_winning": "Whether the competitor wins the Backbox.",
            "price_to_win": "Price the competitor must set to win the Backbox.",
        },
    },
    "care_folders": {
        "description": "An after-sales case linked to an order line, with its status and activity dates.",
        "docs_url": "https://api.backmarket.dev/bundled_openapi.yaml",
        "columns": {
            "id": "Identifier of the Care Folder.",
            "orderline": "Identifier of the related order line.",
            "date_creation": "Time the Care Folder was created.",
            "date_modification": "Time the Care Folder was last modified.",
            "state": "Case status: 0 means open and 9 means closed.",
        },
    },
    "returns": {
        "description": "A product return shipment. Requires BackShip. Use full refresh to capture changes to older returns.",
        "docs_url": "https://api.backmarket.dev/bundled_openapi.yaml",
        "columns": {
            "shipment_id": "Identifier of the return shipment.",
            "order_id": "Identifier of the related order.",
            "orderline_id": "Identifier of the related order line.",
            "date_creation": "Time the return was created. Incremental sync only reads newly created returns.",
            "date_pickup": "Time the return was picked up.",
            "date_delivery": "Time the return was delivered.",
        },
    },
    "buyback_orders": {
        "description": "A trade-in purchase order, with its status, prices, and activity dates.",
        "docs_url": "https://api.backmarket.dev/bundled_openapi.yaml",
        "columns": {
            "order_public_id": "Public identifier of the BuyBack order.",
            "creation_date": "Time the BuyBack order was created.",
            "modification_date": "Time the BuyBack order was last modified.",
            "market": "Market where the BuyBack order was placed.",
        },
    },
}
