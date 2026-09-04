"""Canonical, documentation-sourced descriptions for Reverb endpoints and columns.

Sourced from the official Reverb API reference (https://www.reverb-api.com/docs) and confirmed
against the live API. Keyed by the endpoint names in `settings.py` `REVERB_ENDPOINTS`, which match
the `ExternalDataSchema.name` of a synced Reverb table. Columns absent here fall back to LLM
enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "Orders": {
        "description": "An order placed with your Reverb shop, from a buyer's purchase through shipment.",
        "docs_url": "https://www.reverb-api.com/docs/retrieve-orders",
        "columns": {
            "order_number": "Unique identifier for the order.",
            "order_type": "How the order was placed, e.g. instant purchase or accepted offer.",
            "status": "The order's current fulfillment status, e.g. shipped, unpaid.",
            "title": "Title of the listing sold in this order.",
            "quantity": "Number of units sold in this order.",
            "product_id": "Identifier of the listing sold.",
            "order_bundle_id": "Identifier of the bundle this order belongs to, if it was bundled with others.",
            "buyer_id": "Identifier of the buyer.",
            "buyer_name": "Full name of the buyer.",
            "buyer_first_name": "First name of the buyer.",
            "buyer_last_name": "Last name of the buyer.",
            "amount_product": "Price of the product before tax and shipping.",
            "amount_product_subtotal": "Subtotal for the product line, before tax and shipping.",
            "shipping": "Shipping amount charged to the buyer.",
            "amount_tax": "Tax amount charged to the buyer.",
            "total": "Total amount of the order, including product, shipping, and tax.",
            "created_at": "Time at which the order was created.",
            "updated_at": "Time at which the order was last updated.",
            "paid_at": "Time at which the order was paid for.",
        },
    },
    "Listings": {
        "description": "A listing in your Reverb shop describing an item for sale.",
        "docs_url": "https://www.reverb-api.com/docs/updating-your-listing",
        "columns": {
            "id": "Unique identifier for the listing.",
            "title": "Title of the listing.",
            "make": "Manufacturer or brand of the item.",
            "model": "Model name of the item.",
            "finish": "Finish or color of the item.",
            "year": "Year, or year range, the item was made.",
            "description": "Full description of the listing, as HTML.",
            "condition": "The item's condition, e.g. new, excellent.",
            "state": "The listing's current lifecycle state, e.g. live, draft, ended.",
            "price": "Listed price of the item.",
            "buyer_price": "Price shown to buyers, including any buyer-side fees.",
            "inventory": "Number of units available.",
            "has_inventory": "Whether the listing tracks inventory count.",
            "offers_enabled": "Whether buyers can make offers on this listing.",
            "auction": "Whether this listing is an auction rather than a fixed-price sale.",
            "categories": "Categories the listing is filed under.",
            "listing_currency": "Currency the listing's price is denominated in.",
            "shop_id": "Identifier of the shop that owns the listing.",
            "shop_name": "Name of the shop that owns the listing.",
            "shipping": "Shipping rates and regions configured for the listing.",
            "us_outlet": "Whether the listing is part of Reverb's US outlet program.",
            "created_at": "Time at which the listing was created.",
            "published_at": "Time at which the listing was published live.",
        },
    },
    "Payouts": {
        "description": "A batch of earnings Reverb sent to your bank account, grouping one or more orders.",
        "docs_url": "https://www.reverb-api.com/docs/read-payouts",
        "columns": {
            "id": "Unique identifier for the payout, parsed from its line items link.",
            "total": "Total amount paid out.",
            "created_at": "Time at which the payout was created.",
            "updated_at": "Time at which the payout was last updated.",
        },
    },
}
