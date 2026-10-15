from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field

API_VERSION = "v1"
BASE_URL = f"https://api.scrunchai.com/{API_VERSION}"
PAGE_SIZE = 100

ENDPOINTS = {
    "brands": "brands",
    "prompts": "{brand_id}/prompts",
    "competitors": "brands/{brand_id}/competitors",
    "personas": "brands/{brand_id}/personas",
    "responses": "{brand_id}/responses",
}
INCREMENTAL_FIELDS = {"responses": [incremental_field("created_at")]}
PRIMARY_KEYS = {name: ["id"] if name == "brands" else ["brand_id", "id"] for name in ENDPOINTS}

AUTH_ERROR = "Scrunch rejected the API key. Check the key in your organization's API Keys menu."
PERMISSION_ERROR = (
    "Scrunch denied access. Check the key's brand access and Query scope. "
    "API access requires an Agency or Enterprise plan, or an override from Scrunch."
)
NON_RETRYABLE_ERRORS: dict[str, str | None] = {
    "401 Client Error": AUTH_ERROR,
    "403 Client Error": PERMISSION_ERROR,
    "402 Client Error": PERMISSION_ERROR,
}
