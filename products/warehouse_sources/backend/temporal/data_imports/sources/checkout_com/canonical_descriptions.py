"""Canonical, documentation-sourced descriptions for Checkout.com endpoints and columns.

Sourced from the official Checkout.com API reference (https://api-reference.checkout.com/).
Keyed by the endpoint names in `checkout_com.py` `ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Checkout.com table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "disputes": {
        "description": "A dispute (chargeback) raised by a cardholder against a Checkout.com payment.",
        "docs_url": "https://api-reference.checkout.com/#tag/Disputes",
        "columns": {
            "id": "Unique identifier for the dispute.",
            "category": "Category of the dispute (e.g. fraudulent, product_service_not_received).",
            "status": "Current status of the dispute (e.g. evidence_required, evidence_under_review, won, lost).",
            "amount": "Disputed amount, in the smallest currency unit.",
            "currency": "Three-letter ISO currency code of the dispute.",
            "reason_code": "Card scheme reason code for the dispute.",
            "resolved_reason": "Reason the dispute was resolved, once resolved.",
            "payment_id": "Identifier of the payment that was disputed.",
            "payment_reference": "Reference of the disputed payment.",
            "payment_arn": "Acquirer reference number of the disputed payment.",
            "payment_method": "Payment method used for the disputed payment.",
            "received_on": "Time at which the dispute was received.",
            "last_update": "Time at which the dispute was last updated.",
            "evidence_required_by": "Deadline by which evidence must be submitted.",
        },
    },
}
