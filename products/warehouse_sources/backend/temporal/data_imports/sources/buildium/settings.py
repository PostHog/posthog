from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field

BASE_URL = "https://api.buildium.com"
PAGE_SIZE = 1000
ENDPOINTS = {
    "rental_properties": "rentals",
    "rental_units": "rentals/units",
    "leases": "leases",
    "tenants": "leases/tenants",
    "rental_owners": "rentals/owners",
    "vendors": "vendors",
    "bills": "bills",
    "general_ledger_accounts": "glaccounts",
    "work_orders": "workorders",
    "applicants": "applicants",
    "bank_accounts": "bankaccounts",
    "general_ledger_transactions": "generalledger/transactions",
    "lease_transactions": "leases/{leaseId}/transactions",
    "lease_outstanding_balances": "leases/outstandingbalances",
}
# Other list responses omit update timestamps, even when their endpoints accept update filters.
INCREMENTAL_FIELDS = {
    name: [incremental_field("LastUpdatedDateTime")] for name in ("leases", "applicants", "general_ledger_transactions")
}
PRIMARY_KEYS = {
    "lease_transactions": ["_leases_Id", "Id"],
    "lease_outstanding_balances": ["LeaseId"],
}
ORDER_BY = {"lease_outstanding_balances": "LeaseId asc"}
# The full account number is not needed for analysis, and the masked AccountNumber column stays.
EXCLUDED_COLUMNS = {"bank_accounts": ("AccountNumberUnmasked",)}
# Endpoints that need a parent id or required filters are probed through the list they depend on.
CREDENTIAL_PROBE_PATHS = {"lease_transactions": "leases", "general_ledger_transactions": "glaccounts"}

LEASE_TRANSACTIONS_PARENT = "leases"
GL_ACCOUNTS_PATH = "glaccounts"
# Buildium rejects query strings over 4096 characters, and each repeated glaccountids value takes
# up to 24 characters, so larger charts of accounts are requested in batches.
GL_ACCOUNT_BATCH_SIZE = 150
# The transactions endpoint requires a date range. These bounds cover every transaction date.
GL_TRANSACTIONS_START_DATE = "1900-01-01"
GL_TRANSACTIONS_END_DATE = "2099-12-31"

AUTH_ERROR = "Buildium authentication failed. Check your API client ID and secret."
PERMISSION_ERROR = "Buildium denied access. Enable Open API and grant your API key View access to the selected data."
