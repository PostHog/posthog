from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field

BASE_URL = "https://api.slash.com"

ENDPOINTS = {
    "accounts": "account",
    "transactions": "transaction",
    "cards": "card",
    "invoices": "invoice",
    "invoice_series": "invoice-series",
    "expense_reports": "expense-report",
    "contacts": "contact",
}

INCREMENTAL_FIELDS = {"transactions": [incremental_field("date")]}

AUTH_ERROR = "Slash rejected the API key. Check the key in your Slash dashboard."
PERMISSION_ERROR = "Your Slash key cannot access this resource. Check its permissions and the legal entity ID."
REQUEST_ERROR = "Slash rejected the request. User-scoped keys require a valid legal entity ID."
