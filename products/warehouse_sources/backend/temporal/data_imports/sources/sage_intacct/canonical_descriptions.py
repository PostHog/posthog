from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

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
}
