from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field

BASE_URL = "https://api.7shifts.com/v2/"
ENDPOINTS = ("locations", "departments", "roles", "users", "shifts", "time_punches")
DATE_ONLY_ENDPOINTS = frozenset({"locations", "departments", "roles", "users"})
INCREMENTAL_FIELDS = {name: [incremental_field("modified")] for name in ENDPOINTS}

AUTH_ERROR = "7shifts rejected the access token. Create a token in Settings > Developer Tools, then reconnect."
ACCESS_ERROR = "7shifts denied access. Check the company ID, token administrator, and your plan's API access."
COMPANY_ERROR = "Enter a positive numeric 7shifts company ID."
