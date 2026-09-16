"""Canonical, documentation-sourced descriptions for Faire External API v2 endpoints and columns.

Keyed by the endpoint names in `settings.py` `FAIRE_ENDPOINTS`, which match the `ExternalDataSchema.name`
of a synced Faire table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "Orders": {
        "description": "A wholesale order placed by a retailer against your Faire brand.",
        "docs_url": "https://developers.faire.com/docs",
        "columns": {
            "id": "Unique identifier for the order.",
            "display_id": "Human-readable order number shown in the Faire brand portal.",
            "created_at": "Time at which the order was created.",
            "updated_at": "Time at which the order was last updated.",
            "state": "Current fulfillment state of the order (e.g. NEW, PROCESSING, DELIVERED).",
            "retailer_id": "Identifier of the retailer that placed the order.",
            "source": "Where the order originated (e.g. the Faire marketplace).",
            "ship_after": "Earliest date the order is allowed to ship.",
            "expected_ship_date": "Date the brand expects to ship the order.",
            "requested_ship_date": "Ship date requested by the retailer.",
            "processing_at": "Time at which the order moved into the processing state.",
            "payment_initiated_at": "Time at which payment for the order was initiated.",
            "estimated_payout_at": "Estimated date the brand will be paid out for the order.",
            "original_order_id": "Identifier of the original order, if this order is a reorder or split.",
            "is_free_shipping": "Whether the order qualifies for free shipping.",
            "is_fulfilled_by_faire": "Whether Faire handles fulfillment for this order.",
            "purchase_order_number": "Retailer-provided purchase order number, if any.",
            "notes": "Free-text notes attached to the order.",
        },
    },
    "Products": {
        "description": "A product listed by your Faire brand, including its variants and merchandising details.",
        "docs_url": "https://developers.faire.com/docs",
        "columns": {
            "id": "Unique identifier for the product.",
            "brand_id": "Identifier of the brand the product belongs to.",
            "name": "The product's display name.",
            "description": "Full product description.",
            "short_description": "Short product description shown in listings.",
            "created_at": "Time at which the product was created.",
            "updated_at": "Time at which the product was last updated.",
            "sale_state": "Whether the product is for sale or sales are paused.",
            "lifecycle_state": "Publication state of the product (draft, published, unpublished, deleted).",
            "variants": "The product's purchasable variants, including SKU, price, and available quantity.",
            "unit_multiplier": "Number of units contained in a single sellable unit of the product.",
            "minimum_order_quantity": "Minimum quantity of the product a retailer must order.",
            "made_in_country": "Country the product is manufactured in.",
        },
    },
    "Brand": {
        "description": "Your Faire brand's profile.",
        "docs_url": "https://developers.faire.com/docs",
        "columns": {
            "brand_id": "Unique identifier for the brand.",
            "name": "The brand's display name.",
            "currency": "Currency the brand sells in.",
            "locale": "The brand's configured locale.",
        },
    },
}
