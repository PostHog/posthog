from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field

API_DOCS_URL = "https://docs.soda.io/reference/soda-apis/rest-api"
REGIONS = {"eu": "https://cloud.soda.io", "us": "https://cloud.us.soda.io"}
ENDPOINTS = ("datasets", "checks", "incidents")
PRIMARY_KEYS = ["id"]
PAGE_SIZE = 100

# Creation filters on checks and incidents would miss later result and status changes.
INCREMENTAL_FIELDS = {"datasets": [incremental_field("lastUpdated")]}

AUTH_ERROR = "Soda Cloud rejected the API keys. Check the key ID, key secret, and region."
PERMISSION_ERROR = "Soda Cloud denied access. Check that the API key owner has View dataset permission."
REGION_ERROR = "Select Europe or United States as the Soda Cloud region."
