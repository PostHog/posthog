"""Canonical, documentation-sourced descriptions for Braintree endpoints and columns.

Sourced from the official Braintree GraphQL API reference (https://graphql.braintreepayments.com/).
Keyed by the endpoint names in `settings.py` `BRAINTREE_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Braintree table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "transactions": {
        "description": "A single attempt to move money — a sale or credit processed through Braintree.",
        "docs_url": "https://graphql.braintreepayments.com/reference/#object--Transaction",
        "columns": {
            "id": "Globally unique GraphQL identifier of the transaction.",
            "legacyId": "Legacy numeric/string transaction id from the classic Braintree API.",
            "createdAt": "Time at which the transaction was created.",
            "status": "Current status of the transaction (e.g. SETTLED, AUTHORIZED, SUBMITTED_FOR_SETTLEMENT, VOIDED).",
            "amount": "Monetary amount of the transaction, with value and currency code.",
            "orderId": "Merchant-supplied order identifier associated with the transaction.",
            "merchantAccountId": "Identifier of the merchant account the transaction was processed under.",
            "paymentMethodSnapshot": "Snapshot of the payment method used at the time of the transaction.",
        },
    },
    "refunds": {
        "description": "A refund returning funds from a settled transaction back to the customer.",
        "docs_url": "https://graphql.braintreepayments.com/reference/#object--Refund",
        "columns": {
            "id": "Globally unique GraphQL identifier of the refund.",
            "legacyId": "Legacy numeric/string refund id from the classic Braintree API.",
            "createdAt": "Time at which the refund was created.",
            "status": "Current status of the refund.",
            "amount": "Monetary amount refunded, with value and currency code.",
            "refundedTransaction": "The original transaction that was refunded.",
            "orderId": "Merchant-supplied order identifier associated with the refund.",
        },
    },
    "disputes": {
        "description": "A customer's challenge of a transaction with their bank (a chargeback) and its status.",
        "docs_url": "https://graphql.braintreepayments.com/reference/#object--Dispute",
        "columns": {
            "id": "Globally unique GraphQL identifier of the dispute.",
            "legacyId": "Legacy numeric/string dispute id from the classic Braintree API.",
            "createdAt": "Time at which the dispute was created in Braintree.",
            "receivedDate": "Date the dispute was received from the processor.",
            "status": "Current status of the dispute (e.g. OPEN, WON, LOST, ACCEPTED).",
            "type": "Type of dispute (e.g. CHARGEBACK, PRE_ARBITRATION, RETRIEVAL).",
            "caseNumber": "Case number assigned to the dispute by the processor.",
            "amountDisputed": "Monetary amount being disputed, with value and currency code.",
        },
    },
}
