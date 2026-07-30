from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "chart_transactions": {
        "description": "General-ledger transactions (ChartTransaction records) - Campfire's GL transaction log and the recommended endpoint for row-level GL data. Each transaction carries account, department, vendor, entity, and journal/date metadata.",
        "docs_url": "https://docs.campfire.ai/api-reference/core-accounting/list-chart-transactions",
        "columns": {
            "id": "Unique identifier for the GL transaction.",
            "amount": "Amount in the consolidated currency (the root entity's currency).",
            "amount_book": "Amount in the currency of the entity the transaction belongs to.",
            "amount_native": "Amount in the currency the transaction was originally created in.",
            "posted_at": "The transaction date; determines which accounting period the transaction falls in.",
            "vendor": "ID of the linked Campfire Vendor object.",
            "vendor_name": "Name of the linked Campfire Vendor object.",
            "merchant_name": "Free-text merchant name stored directly on the transaction; not linked to any Campfire object.",
            "account": "The Campfire ChartAccount (GL account) the transaction is posted to.",
            "entity": "The Campfire ChartEntity ID the transaction belongs to.",
            "last_modified_at": "Timestamp of the last modification to the transaction.",
        },
    },
    "journal_entries": {
        "description": "Journal entries with their transactions, account information, vendor and department details, tag associations, attachments, and exchange rate data for multi-currency entries.",
        "docs_url": "https://docs.campfire.ai/api-reference/core-accounting/list-journal-entries",
        "columns": {
            "id": "Unique identifier for the journal entry.",
            "date": "The journal entry date, which determines the accounting period.",
            "created_at": "Timestamp when the journal entry was created.",
            "last_modified_at": "Timestamp of the last modification to the journal entry.",
        },
    },
    "invoices": {
        "description": "Accounts receivable invoices, including line items, payment status, client and entity relationships, and totals.",
        "docs_url": "https://docs.campfire.ai/api-reference/accounts-receivable/list-invoices",
        "columns": {
            "id": "Unique identifier for the invoice.",
            "invoice_date": "The invoice date.",
            "created_at": "Timestamp when the invoice was created.",
            "last_modified_at": "Timestamp of the last modification to the invoice.",
        },
    },
    "invoice_payments": {
        "description": "Payments applied against accounts receivable invoices. Voided payments are included with voided_date set, so payments reversed after a previous sync can be detected.",
        "docs_url": "https://docs.campfire.ai/api-reference/accounts-receivable/list-invoice-payments",
        "columns": {
            "id": "Unique identifier for the invoice payment.",
            "amount": "Payment amount.",
            "currency": "Payment currency.",
            "payment_date": "Date the payment was applied.",
            "source": "Where the payment originated.",
            "source_id": "Identifier of the payment in its source system.",
            "voided_date": "Date the payment was voided, when it has been reversed.",
            "created_at": "Timestamp when the payment record was created.",
            "last_modified_at": "Timestamp of the last modification to the payment record.",
        },
    },
    "credit_memos": {
        "description": "Accounts receivable credit memos, including line items, application status (open, partially used, used, voided), and client relationships.",
        "docs_url": "https://docs.campfire.ai/api-reference/accounts-receivable/list-credit-memos",
        "columns": {
            "id": "Unique identifier for the credit memo.",
            "credit_memo_date": "The credit memo date.",
            "created_at": "Timestamp when the credit memo was created.",
            "last_modified_at": "Timestamp of the last modification to the credit memo.",
        },
    },
    "bills": {
        "description": "Accounts payable bills with vendor, entity, currency, aging, and payment status information, including calculated totals, amounts paid, and amounts due.",
        "docs_url": "https://docs.campfire.ai/api-reference/accounts-payable/list-accounting-bills",
        "columns": {
            "id": "Unique identifier for the bill.",
            "last_modified_at": "Timestamp of the last modification to the bill.",
        },
    },
    "bill_payments": {
        "description": "Payments applied against accounts payable bills. Voided payments are included with voided_date set, so payments reversed after a previous sync can be detected.",
        "docs_url": "https://docs.campfire.ai/api-reference/accounts-payable/list-bill-payments",
        "columns": {
            "id": "Unique identifier for the bill payment.",
            "bill_id": "ID of the bill the payment was applied to.",
            "bill_number": "Number of the bill the payment was applied to.",
            "amount": "Payment amount.",
            "currency": "Payment currency.",
            "payment_date": "Date the payment was applied.",
            "source": "Where the payment originated.",
            "source_id": "Identifier of the payment in its source system.",
            "voided_date": "Date the payment was voided, when it has been reversed.",
            "created_at": "Timestamp when the payment record was created.",
            "last_modified_at": "Timestamp of the last modification to the payment record.",
        },
    },
    "debit_memos": {
        "description": "Accounts payable debit memos, including line items, status, and vendor relationships.",
        "docs_url": "https://docs.campfire.ai/api-reference/accounts-payable/list-debit-memos",
        "columns": {
            "id": "Unique identifier for the debit memo.",
            "debit_memo_date": "The debit memo date.",
            "created_at": "Timestamp when the debit memo was created.",
            "last_modified_at": "Timestamp of the last modification to the debit memo.",
        },
    },
    "bank_accounts": {
        "description": "Bank accounts with balances, currency, institution details, and their mapping to chart of accounts types.",
        "docs_url": "https://docs.campfire.ai/api-reference/cash-management/list-bank-accounts",
        "columns": {
            "id": "Unique identifier for the bank account.",
            "created_at": "Timestamp when the bank account record was created.",
            "last_modified_at": "Timestamp of the last modification to the bank account record.",
        },
    },
    "bank_transactions": {
        "description": "Bank transactions from connected bank accounts.",
        "docs_url": "https://docs.campfire.ai/api-reference/cash-management/list-bank-transactions",
        "columns": {
            "id": "Unique identifier for the bank transaction.",
            "posted_at": "Date the transaction posted at the bank.",
            "created_at": "Timestamp when the bank transaction record was created.",
            "last_modified_at": "Timestamp of the last modification to the bank transaction record.",
        },
    },
    "vendors": {
        "description": "Vendors and customers, including contact details, parent vendor metadata, and the full lineage of ancestor vendors so parent/child relationships can be reconstructed.",
        "docs_url": "https://docs.campfire.ai/api-reference/company-objects/list-vendors",
        "columns": {
            "id": "Unique identifier for the vendor.",
            "name": "Vendor or customer name.",
            "vendor_type": "Whether the record is a vendor or a customer.",
            "parent_name": "Name of the parent vendor, when the vendor has one.",
            "created_at": "Timestamp when the vendor record was created.",
            "last_modified_at": "Timestamp of the last modification to the vendor record.",
        },
    },
    "departments": {
        "description": "Departments, including parent department metadata so parent/child relationships can be reconstructed.",
        "docs_url": "https://docs.campfire.ai/api-reference/company-objects/list-departments",
        "columns": {
            "id": "Unique identifier for the department.",
            "created_at": "Timestamp when the department record was created.",
            "last_modified_at": "Timestamp of the last modification to the department record.",
        },
    },
    "chart_of_accounts": {
        "description": "The chart of accounts (GL accounts). Each account includes metadata about its parent account and its full lineage, so parent/child account relationships can be reconstructed.",
        "docs_url": "https://docs.campfire.ai/api-reference/company-objects/list-chart-of-accounts",
        "columns": {
            "id": "Unique identifier for the GL account.",
            "created_at": "Timestamp when the account record was created.",
            "last_modified_at": "Timestamp of the last modification to the account record.",
        },
    },
    "contracts": {
        "description": "Revenue recognition contracts.",
        "docs_url": "https://docs.campfire.ai/api-reference/revenue-recognition/list-contracts",
        "columns": {
            "id": "Unique identifier for the contract.",
            "start_date": "Contract start date.",
            "created_at": "Timestamp when the contract record was created.",
            "last_modified_at": "Timestamp of the last modification to the contract record.",
        },
    },
    "revenue_transactions": {
        "description": "Revenue transactions used for revenue recognition.",
        "docs_url": "https://docs.campfire.ai/api-reference/revenue-recognition/list-revenue-transactions",
        "columns": {
            "id": "Unique identifier for the revenue transaction.",
            "transaction_date": "The revenue transaction date.",
            "created_at": "Timestamp when the revenue transaction record was created.",
            "last_modified_at": "Timestamp of the last modification to the revenue transaction record.",
        },
    },
}
