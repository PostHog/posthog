from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "accounts": {
        "description": "Slash bank accounts accessible to the API key.",
        "docs_url": "https://docs.slash.com/api-reference/account-get",
        "columns": {
            "id": "Unique account identifier.",
            "name": "Account name.",
            "status": "Whether the account is open or closed.",
            "createdAt": "Time when the account was created.",
            "type": "Whether the account is a debit or charge card account.",
        },
    },
    "transactions": {
        "description": "Transactions across Slash accounts, including card payments, transfers, and fees.",
        "docs_url": "https://docs.slash.com/api-reference/transaction-get",
        "columns": {
            "id": "Unique transaction identifier.",
            "date": "Posting time in UTC. Pending and failed transactions use their creation time.",
            "amountCents": "Amount in US cents. Negative amounts are debits; positive amounts are credits.",
            "status": "Whether the transaction is pending, posted, or failed.",
            "accountId": "Identifier of the account associated with the transaction.",
            "authorizedAt": "Authorization time in UTC, available for card transactions only.",
        },
    },
    "cards": {
        "description": "Physical and virtual cards accessible to the API key.",
        "docs_url": "https://docs.slash.com/api-reference/card-get",
        "columns": {
            "id": "Unique card identifier.",
            "accountId": "Identifier of the account associated with the card.",
            "last4": "Last four digits of the card number.",
            "isPhysical": "Whether a physical card was issued.",
            "createdAt": "Time when the card was created.",
        },
    },
    "invoices": {
        "description": "Invoices for the legal entity, with their details and receiving account information.",
        "docs_url": "https://docs.slash.com/api-reference/invoice-get",
        "columns": {
            "id": "Unique invoice identifier, copied from invoice.id.",
            "invoice": "Invoice record, including its identifier and status.",
            "invoiceDetails": "Details associated with the invoice.",
            "invoiceAccount": "Receiving account information for the invoice.",
        },
    },
    "invoice_series": {
        "description": "Recurring invoice configurations for the legal entity.",
        "docs_url": "https://docs.slash.com/api-reference/invoice-series-get",
        "columns": {
            "id": "Unique invoice series identifier.",
            "recurrenceRule": "Rule that controls how often invoices are created.",
            "paymentTermsDays": "Number of days allowed for payment.",
            "nextScheduledDate": "Date of the next scheduled invoice, if one exists.",
        },
    },
    "expense_reports": {
        "description": "Expense reports submitted for reimbursement, with merchant and review information.",
        "docs_url": "https://docs.slash.com/api-reference/expense-report-get",
        "columns": {
            "id": "Unique expense report identifier.",
            "merchant": "Merchant associated with the expense.",
            "submittedByUser": "User who submitted the report.",
            "review": "Review decision, if the report was reviewed.",
        },
    },
    "contacts": {
        "description": "Counterparties for the legal entity, including customers and vendors.",
        "docs_url": "https://docs.slash.com/api-reference/contact-get",
        "columns": {
            "id": "Unique contact identifier.",
            "name": "Display name of the contact.",
            "recipientEmail": "Email address of the recipient.",
            "archivedAt": "Time when the contact was archived. Empty for active contacts.",
        },
    },
}
