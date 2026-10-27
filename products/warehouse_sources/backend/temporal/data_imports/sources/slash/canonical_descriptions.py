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
    "virtual_accounts": {
        "description": "Virtual accounts under each Slash account, including the primary account and closed accounts.",
        "docs_url": "https://docs.slash.com/api-reference/virtual-account-get",
        "columns": {
            "id": "Unique virtual account identifier, copied from the nested virtual account object.",
            "virtualAccount": "The virtual account, with its name, account ID, account type, and close time.",
            "balance": "Total balance of the virtual account, in cents.",
            "spend": "Total spend of the virtual account, in cents.",
            "commissionRule": "Commission rule applied to the virtual account, if any.",
        },
    },
    "card_groups": {
        "description": "Active card groups that share a spending constraint.",
        "docs_url": "https://docs.slash.com/api-reference/card-group-get",
        "columns": {
            "id": "Unique card group identifier.",
            "name": "Name of the card group.",
            "virtualAccountId": "Deprecated legacy virtual account association. Empty when none exists.",
            "spendingConstraint": "Spending rules that apply to the cards in the group.",
        },
    },
    "customers": {
        "description": "Billing recipients for invoices of the legal entity.",
        "docs_url": "https://docs.slash.com/api-reference/customer-get",
        "columns": {
            "id": "Unique customer identifier.",
            "name": "Display name of the customer.",
            "email": "Email address of the customer.",
            "phone": "Phone number of the customer.",
            "address": "Address of the customer.",
            "customMetadata": "Custom metadata associated with the customer.",
            "status": "Whether the customer is active or archived.",
        },
    },
    "account_balances": {
        "description": "Current balances of each Slash account. Charge card accounts have cash and credit balances.",
        "docs_url": "https://docs.slash.com/api-reference/account-balance-get",
        "columns": {
            "accountId": "Identifier of the account associated with the balance.",
            "type": "Balance type: cash, credit, or debit.",
            "available": "Amount in cents that is available to use immediately.",
            "posted": "Amount in cents posted to the balance. Pending transactions are not included.",
            "timestamp": "UTC time when Slash computed the balance.",
        },
    },
}
