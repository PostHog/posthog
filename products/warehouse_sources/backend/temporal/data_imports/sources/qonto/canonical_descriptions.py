from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

DOCS = "https://docs.qonto.com/api-reference/business-api/"

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "bank_accounts": {
        "description": "Qonto bank accounts for the authenticated organization, including balances and account details.",
        "docs_url": DOCS
        + "accounts-organizations/organizations/retrieve-the-authenticated-organization-and-list-bank-accounts",
        "columns": {
            "id": "Unique bank account identifier.",
            "iban": "International bank account number.",
            "currency": "Currency of the bank account.",
            "balance": "Current account balance.",
            "authorized_balance": "Balance available for payments, including transactions in progress.",
            "status": "Account status: active or closed.",
        },
    },
    "transactions": {
        "description": "Transactions across Qonto bank accounts, including pending, declined, completed, and reversed transactions.",
        "docs_url": DOCS + "transactions-statements/transactions/list-transactions",
        "columns": {
            "id": "Unique transaction identifier.",
            "bank_account_id": "Identifier of the bank account that contains the transaction.",
            "amount_cents": "Transaction amount in the smallest currency unit.",
            "currency": "Transaction currency.",
            "side": "Direction of the transaction: credit or debit.",
            "updated_at": "Time of the last transaction update.",
            "settled_at": "Time when the transaction settled.",
            "label_ids": "Identifiers of labels assigned to the transaction.",
        },
    },
    "labels": {
        "description": "Labels that classify transactions for the authenticated organization.",
        "docs_url": DOCS + "accounts-organizations/labels/list-labels",
        "columns": {
            "id": "Unique label identifier.",
            "name": "Label name.",
            "parent_id": "Identifier of the parent label.",
        },
    },
    "memberships": {
        "description": "Users with access to the organization's Qonto account.",
        "docs_url": DOCS + "accounts-organizations/memberships/list-memberships",
        "columns": {"id": "Unique membership identifier.", "role": "Member's role in the organization."},
    },
    "transfers": {
        "description": "SEPA transfers for the authenticated organization.",
        "docs_url": DOCS + "payments-transfers/sepa-transfers/sepa-transfers/index",
        "columns": {
            "id": "Unique transfer identifier.",
            "status": "Current transfer status.",
            "updated_at": "Time of the last transfer update.",
            "beneficiary_id": "Identifier of the transfer beneficiary.",
        },
    },
}
