from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalFieldType

BASE_URL = "https://server.promptwatch.com/api"
PAGE_SIZE = 50
MAX_PAGES = 20
ENDPOINTS = (
    "prompts",
    "responses",
    "monitors",
    "tags",
    "topics",
    "personas",
    "models",
    "brands",
    "grouped_citations",
    "visitor_trends",
)
PAGINATED_ENDPOINTS = {"prompts", "responses", "brands", "grouped_citations"}
CREATED_AT_SORTED_ENDPOINTS = {"prompts", "responses"}
# Ranked by citation count, so the page cap keeps the most cited URLs instead of failing the sync.
CAPPED_ENDPOINTS = {"grouped_citations"}
PATHS = {"grouped_citations": "citations/grouped", "visitor_trends": "analytics/visitors/trend"}
DATA_SELECTORS = {"monitors": "$", "grouped_citations": "data", "visitor_trends": "$"}
EXTRA_PARAMS: dict[str, dict[str, str]] = {
    "models": {"includeDeprecated": "true"},
    "grouped_citations": {"sortBy": "count", "sortOrder": "desc"},
}
PRIMARY_KEYS = {"grouped_citations": ["urlId"], "visitor_trends": ["date", "referrer"]}
INCREMENTAL_FIELDS = {
    "responses": [incremental_field("createdAt")],
    "visitor_trends": [incremental_field("date", IncrementalFieldType.Date)],
}
MERGE_ONLY_ENDPOINTS = {"responses", "visitor_trends"}
# The API rejects date ranges longer than these.
CITATION_WINDOW_DAYS = 92
VISITOR_WINDOW_DAYS = 60
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
