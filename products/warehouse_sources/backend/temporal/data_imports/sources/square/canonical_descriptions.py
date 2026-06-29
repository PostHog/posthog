"""Canonical, documentation-sourced descriptions for Square endpoints and columns.

Sourced from the official Square API reference (https://developer.squareup.com/reference/square).
Keyed by the endpoint names in `settings.py` `SQUARE_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Square table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "payments": {
        "description": "A payment taken by the seller, representing a single attempt to collect money from a customer.",
        "docs_url": "https://developer.squareup.com/reference/square/payments-api/list-payments",
        "columns": {
            "id": "Unique identifier for the payment.",
            "created_at": "Time at which the payment was created.",
            "updated_at": "Time at which the payment was last updated.",
            "amount_money": "Amount of money the payment is for (amount in the smallest currency unit and currency code).",
            "total_money": "Total money charged, including tip and any adjustments.",
            "tip_money": "Tip amount included in the payment.",
            "app_fee_money": "Application fee taken from the payment, if any.",
            "status": "Status of the payment (e.g. APPROVED, PENDING, COMPLETED, CANCELED, FAILED).",
            "source_type": "How the payment was funded (e.g. CARD, CASH, EXTERNAL, BANK_ACCOUNT).",
            "card_details": "Details of the card used, if the payment was made by card.",
            "location_id": "ID of the location where the payment was taken.",
            "order_id": "ID of the order associated with the payment, if any.",
            "customer_id": "ID of the customer associated with the payment, if any.",
            "reference_id": "Optional external reference ID set by the seller.",
            "receipt_number": "Square-generated receipt number for the payment.",
            "receipt_url": "URL of the printable receipt for the payment.",
            "refunded_money": "Total amount refunded against this payment.",
            "version_token": "Opaque token identifying a specific version of the payment, used for optimistic concurrency.",
        },
    },
    "refunds": {
        "description": "A refund of all or part of a previously processed Square payment.",
        "docs_url": "https://developer.squareup.com/reference/square/refunds-api/list-payment-refunds",
        "columns": {
            "id": "Unique identifier for the refund.",
            "created_at": "Time at which the refund was created.",
            "updated_at": "Time at which the refund was last updated.",
            "amount_money": "Amount of money refunded (amount in the smallest currency unit and currency code).",
            "app_fee_money": "Application fee refunded, if any.",
            "status": "Status of the refund (e.g. PENDING, COMPLETED, REJECTED, FAILED).",
            "payment_id": "ID of the payment being refunded.",
            "order_id": "ID of the order associated with the refund, if any.",
            "location_id": "ID of the location where the refund was processed.",
            "reason": "Reason given for the refund.",
        },
    },
    "customers": {
        "description": "A customer profile in the seller's Square Customer Directory.",
        "docs_url": "https://developer.squareup.com/reference/square/customers-api/list-customers",
        "columns": {
            "id": "Unique identifier for the customer.",
            "created_at": "Time at which the customer profile was created.",
            "updated_at": "Time at which the customer profile was last updated.",
            "given_name": "The customer's given (first) name.",
            "family_name": "The customer's family (last) name.",
            "company_name": "The customer's company name.",
            "email_address": "The customer's email address.",
            "phone_number": "The customer's phone number.",
            "address": "The customer's mailing address.",
            "reference_id": "Optional external reference ID set by the seller.",
            "note": "Free-form note attached to the customer.",
            "creation_source": "How the customer profile was created (e.g. THIRD_PARTY, APPOINTMENTS, INVOICES).",
        },
    },
    "locations": {
        "description": "A business location (store) belonging to the Square seller account.",
        "docs_url": "https://developer.squareup.com/reference/square/locations-api/list-locations",
        "columns": {
            "id": "Unique identifier for the location.",
            "created_at": "Time at which the location was created.",
            "name": "The location's name.",
            "address": "The location's physical address.",
            "status": "Status of the location (ACTIVE or INACTIVE).",
            "timezone": "The location's time zone.",
            "currency": "Currency used by the location, as a three-letter ISO code.",
            "country": "Country the location is in, as a two-letter ISO code.",
            "business_name": "The seller's business name shown on receipts for this location.",
            "type": "The location's type (PHYSICAL or MOBILE).",
            "logo_url": "URL of the logo image shown on Square-generated receipts and invoices for the location.",
            "merchant_id": "ID of the merchant that owns the location.",
        },
    },
    "catalog": {
        "description": "A catalog object — an item, variation, category, tax, discount, or modifier in the seller's catalog.",
        "docs_url": "https://developer.squareup.com/reference/square/catalog-api/list-catalog",
        "columns": {
            "id": "Unique identifier for the catalog object.",
            "type": "The catalog object's type (e.g. ITEM, ITEM_VARIATION, CATEGORY, TAX, DISCOUNT, MODIFIER).",
            "updated_at": "Time at which the catalog object was last updated.",
            "version": "Version number used for optimistic concurrency.",
            "is_deleted": "Whether the catalog object has been deleted.",
            "present_at_all_locations": "Whether the object is available at all of the seller's locations.",
            "item_data": "Item details, present when type is ITEM (name, description, variations).",
            "item_variation_data": "Variation details, present when type is ITEM_VARIATION (price, SKU).",
            "category_data": "Category details, present when type is CATEGORY.",
        },
    },
}
