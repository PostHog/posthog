BASE_URL = "https://api.intacct.com/ia/api/v1/"
TOKEN_URL = f"{BASE_URL}oauth2/token"
PAGE_SIZE = 100
QUERY_ROWS_PAGE_SIZE = 1000

ENDPOINTS = {
    "Customers": "accounts-receivable/customer",
    "Vendors": "accounts-payable/vendor",
    "Invoices": "accounts-receivable/invoice",
    "Bills": "accounts-payable/bill",
    "GLAccounts": "general-ledger/account",
    "JournalEntries": "general-ledger/journal-entry",
    "JournalEntryLines": "general-ledger/journal-entry-line",
    "InvoiceLines": "accounts-receivable/invoice-line",
    "BillLines": "accounts-payable/bill-line",
    "ARPayments": "accounts-receivable/payment",
    "APPayments": "accounts-payable/payment",
    "Locations": "company-config/location",
    "Departments": "company-config/department",
    "GLBudgets": "general-ledger/budget",
}

# High-volume objects read every field from the query service instead of one detail request per key.
QUERY_ROWS_OBJECTS = frozenset(
    {
        "general-ledger/journal-entry-line",
        "accounts-receivable/invoice-line",
        "accounts-payable/bill-line",
        "accounts-receivable/payment",
        "accounts-payable/payment",
    }
)
