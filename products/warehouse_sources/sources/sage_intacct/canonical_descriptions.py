from products.warehouse_sources.sources.sdk import CanonicalDescriptions

_COMMON_COLUMNS = {
    "key": "The system-assigned key for the Sage Intacct record.",
    "id": "The identifier for the Sage Intacct record.",
    "href": "The API path for this record.",
}

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "Customers": {
        "description": "A customer that buys goods or services from the company.",
        "docs_url": "https://developer.sage.com/intacct/apis/intacct/1/intacct-openapi",
        "columns": _COMMON_COLUMNS,
    },
    "Vendors": {
        "description": "A vendor that supplies goods or services to the company.",
        "docs_url": "https://developer.sage.com/intacct/apis/intacct/1/intacct-openapi",
        "columns": _COMMON_COLUMNS,
    },
    "Invoices": {
        "description": "An accounts receivable invoice that records charges to a customer.",
        "docs_url": "https://developer.sage.com/intacct/apis/intacct/1/intacct-openapi",
        "columns": _COMMON_COLUMNS,
    },
    "Bills": {
        "description": "An accounts payable bill that records charges from a vendor.",
        "docs_url": "https://developer.sage.com/intacct/apis/intacct/1/intacct-openapi",
        "columns": _COMMON_COLUMNS,
    },
    "GLAccounts": {
        "description": "A general ledger account in the company chart of accounts.",
        "docs_url": "https://developer.sage.com/intacct/apis/intacct/1/intacct-openapi",
        "columns": _COMMON_COLUMNS,
    },
    "JournalEntries": {
        "description": "A journal entry that records a transaction in the general ledger.",
        "docs_url": "https://developer.sage.com/intacct/apis/intacct/1/intacct-openapi",
        "columns": _COMMON_COLUMNS,
    },
    "JournalEntryLines": {
        "description": "A debit or credit line on a general ledger journal entry, with its account and dimensions.",
        "docs_url": "https://developer.sage.com/intacct/apis/intacct/1/intacct-openapi",
        "columns": _COMMON_COLUMNS,
    },
    "InvoiceLines": {
        "description": "A line item on an accounts receivable invoice.",
        "docs_url": "https://developer.sage.com/intacct/apis/intacct/1/intacct-openapi",
        "columns": _COMMON_COLUMNS,
    },
    "BillLines": {
        "description": "A line item on an accounts payable bill.",
        "docs_url": "https://developer.sage.com/intacct/apis/intacct/1/intacct-openapi",
        "columns": _COMMON_COLUMNS,
    },
    "ARPayments": {
        "description": "A payment received from a customer and applied to accounts receivable invoices.",
        "docs_url": "https://developer.sage.com/intacct/apis/intacct/1/intacct-openapi",
        "columns": _COMMON_COLUMNS,
    },
    "APPayments": {
        "description": "A payment made to a vendor and applied to accounts payable bills.",
        "docs_url": "https://developer.sage.com/intacct/apis/intacct/1/intacct-openapi",
        "columns": _COMMON_COLUMNS,
    },
    "Locations": {
        "description": "A location dimension value that can be assigned to transactions and lines.",
        "docs_url": "https://developer.sage.com/intacct/apis/intacct/1/intacct-openapi",
        "columns": _COMMON_COLUMNS,
    },
    "Departments": {
        "description": "A department dimension value that can be assigned to transactions and lines.",
        "docs_url": "https://developer.sage.com/intacct/apis/intacct/1/intacct-openapi",
        "columns": _COMMON_COLUMNS,
    },
    "GLBudgets": {
        "description": "A general ledger budget, with its budget lines per account, period and dimension.",
        "docs_url": "https://developer.sage.com/intacct/apis/intacct/1/intacct-openapi",
        "columns": {**_COMMON_COLUMNS, "lines": "The budget lines, each with an account, reporting period and amount."},
    },
}
