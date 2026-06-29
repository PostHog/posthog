"""Canonical, documentation-sourced descriptions for Ramp endpoints and columns.

Sourced from the official Ramp Developer API reference (https://docs.ramp.com/developer-api/v1).
Keyed by the endpoint names in `settings.py` `RAMP_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Ramp table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "transactions": {
        "description": "A card transaction (purchase) made on a Ramp card.",
        "docs_url": "https://docs.ramp.com/developer-api/v1/api/transactions",
        "columns": {
            "id": "Unique identifier for the transaction.",
            "amount": "Transaction amount.",
            "currency_code": "Three-letter ISO currency code of the transaction.",
            "merchant_name": "Name of the merchant.",
            "merchant_id": "Identifier of the merchant.",
            "merchant_category_code": "Merchant category code (MCC) for the transaction.",
            "state": "State of the transaction (e.g. CLEARED, PENDING, DECLINED).",
            "card_id": "ID of the card used for the transaction.",
            "card_holder": "The cardholder who made the transaction.",
            "user_transaction_time": "Time at which the transaction was made by the user.",
            "sk_category_name": "Spend category assigned to the transaction.",
            "receipts": "Receipt IDs attached to the transaction.",
            "accounting_categories": "Accounting categories associated with the transaction.",
            "policy_violations": "Policy violations flagged on the transaction.",
            "memo": "Memo or note attached to the transaction.",
        },
    },
    "reimbursements": {
        "description": "An out-of-pocket expense reimbursement request in Ramp.",
        "docs_url": "https://docs.ramp.com/developer-api/v1/api/reimbursements",
        "columns": {
            "id": "Unique identifier for the reimbursement.",
            "amount": "Reimbursement amount.",
            "currency": "Currency code of the reimbursement.",
            "merchant": "Name of the merchant.",
            "transaction_date": "Date of the underlying expense.",
            "created_at": "Time at which the reimbursement was created.",
            "user_id": "ID of the user requesting the reimbursement.",
            "user_full_name": "Full name of the user requesting the reimbursement.",
            "direction": "Direction of the reimbursement (e.g. business owes employee).",
            "memo": "Memo or note describing the reimbursement.",
            "receipts": "Receipt IDs attached to the reimbursement.",
            "accounting_categories": "Accounting categories associated with the reimbursement.",
        },
    },
    "users": {
        "description": "A user (employee) in the Ramp organization.",
        "docs_url": "https://docs.ramp.com/developer-api/v1/api/users",
        "columns": {
            "id": "Unique identifier for the user.",
            "first_name": "The user's first name.",
            "last_name": "The user's last name.",
            "email": "The user's email address.",
            "role": "The user's role in the organization.",
            "status": "The user's account status (e.g. ACTIVE, INVITE_PENDING).",
            "department_id": "ID of the department the user belongs to.",
            "location_id": "ID of the user's location.",
            "manager_id": "ID of the user's manager.",
            "phone": "The user's phone number.",
            "is_manager": "Whether the user is a manager.",
        },
    },
    "cards": {
        "description": "A physical or virtual Ramp card issued to a user.",
        "docs_url": "https://docs.ramp.com/developer-api/v1/api/cards",
        "columns": {
            "id": "Unique identifier for the card.",
            "cardholder_id": "ID of the user the card is issued to.",
            "cardholder_name": "Name of the cardholder.",
            "display_name": "Display name of the card.",
            "last_four": "Last four digits of the card number.",
            "is_physical": "Whether the card is physical (true) or virtual (false).",
            "state": "State of the card (e.g. ACTIVE, SUSPENDED, TERMINATED).",
            "spending_restrictions": "Spending limits and restrictions configured on the card.",
        },
    },
    "departments": {
        "description": "A department defined in the Ramp organization.",
        "docs_url": "https://docs.ramp.com/developer-api/v1/api/departments",
        "columns": {
            "id": "Unique identifier for the department.",
            "name": "The department's name.",
        },
    },
}
