from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field

BASE_URL = "https://server.promptwatch.com/api"
PAGE_SIZE = 50
MAX_PAGES = 20
ENDPOINTS = ("prompts", "responses", "monitors", "tags", "topics", "personas")
PAGINATED_ENDPOINTS = {"prompts", "responses"}
INCREMENTAL_FIELDS = {"responses": [incremental_field("createdAt")]}
AUTH_ERROR = "Promptwatch rejected your API key. Check the key in Settings > API Keys."
PROJECT_ERROR = "Promptwatch denied access. Check your project ID and API key permissions."
QUOTA_ERROR = "Promptwatch reached its hourly API quota. Wait until the next UTC hour or upgrade your plan."
ROW_LIMIT_ERROR = (
    "Promptwatch exceeded the sync limit of 1,000 rows. Use a smaller project or a later response start date."
)
NON_RETRYABLE_ERRORS = {
    "401 Client Error": AUTH_ERROR,
    "403 Client Error": PROJECT_ERROR,
    "PROMPTWATCH_HOURLY_QUOTA": QUOTA_ERROR,
    "PROMPTWATCH_ROW_LIMIT": ROW_LIMIT_ERROR,
}
