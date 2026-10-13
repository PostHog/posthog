"""Canonical descriptions for Back Market endpoints and columns.

The official docs portal (https://api.backmarket.dev/) renders as a JS single-page app we
couldn't fetch, so only fields corroborated against a working third-party seller integration are
described here. Everything else falls back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

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
}
