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
}
# Other list responses omit update timestamps, even when their endpoints accept update filters.
INCREMENTAL_FIELDS = {name: [incremental_field("LastUpdatedDateTime")] for name in ("leases", "applicants")}
AUTH_ERROR = "Buildium authentication failed. Check your API client ID and secret."
PERMISSION_ERROR = "Buildium denied access. Enable Open API and grant your API key View access to the selected data."
