from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field

BASE_URL = "https://ywe3crmpll.execute-api.us-east-2.amazonaws.com/stage/"
API_DOCS_URL = "https://documenter.getpostman.com/view/35988189/2sA3XLEjFd"
PAGE_SIZE = 100

ENDPOINTS = {
    "customers": "customers",
    "jobs": "jobs",
    "estimates": "estimates",
    "invoices": "invoices",
    "payments": "payments",
    "projects": "projects",
}
INCREMENTAL_FIELDS = {name: [incremental_field("updated_at")] for name in ENDPOINTS}
PRIMARY_KEYS = ["id"]
AUTH_ERROR = "FieldPulse rejected the API key. Contact support@fieldpulse.com to check that your key is active."
