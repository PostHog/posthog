BASE_URL = "https://api.intacct.com/ia/api/v1/"
TOKEN_URL = f"{BASE_URL}oauth2/token"
PAGE_SIZE = 100

ENDPOINTS = {
    "Customers": "accounts-receivable/customer",
    "Vendors": "accounts-payable/vendor",
    "Invoices": "accounts-receivable/invoice",
    "Bills": "accounts-payable/bill",
    "GLAccounts": "general-ledger/account",
    "JournalEntries": "general-ledger/journal-entry",
}
