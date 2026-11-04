from products.warehouse_sources.sources.sdk import IncrementalFieldType, incremental_field

API_VERSION = "v1"
BASE_URL = f"https://api.scrunchai.com/{API_VERSION}"
PAGE_SIZE = 100
AGENT_TRAFFIC_PAGE_SIZE = 10000
AGENT_TRAFFIC_HISTORY_DAYS = 365
AGENT_TRAFFIC_DIMENSIONS = ("date", "site", "path", "agent_source", "agent_type")
SITEMAP_METRICS = ("citations", "ai_referrals", "agent_traffic")

ENDPOINTS = {
    "brands": "brands",
    "prompts": "{brand_id}/prompts",
    "competitors": "brands/{brand_id}/competitors",
    "personas": "brands/{brand_id}/personas",
    "site_audit_score": "{brand_id}/audit-scores/site",
    "agent_traffic": "{brand_id}/sites/{site_id}/agent-traffic",
    "sitemap_page_metrics": "{brand_id}/sitemap/pages/{page_id}/metrics",
    "signals": "{brand_id}/signals",
    "responses": "{brand_id}/responses",
}
# Middle resources of the two-level fan-outs: they bind the second path id of their child.
FANOUT_PARENTS = {
    "agent_traffic": ("sites", "{brand_id}/sites", "site_id"),
    "sitemap_page_metrics": ("sitemap_pages", "{brand_id}/sitemap/pages", "page_id"),
}
INCREMENTAL_FIELDS = {
    "responses": [incremental_field("created_at")],
    "signals": [incremental_field("detected_for_date", IncrementalFieldType.Date)],
    "agent_traffic": [incremental_field("date", IncrementalFieldType.Date)],
}
PRIMARY_KEYS = {name: ["id"] if name == "brands" else ["brand_id", "id"] for name in ENDPOINTS} | {
    "site_audit_score": ["brand_id"],
    "agent_traffic": ["brand_id", "site_id", *AGENT_TRAFFIC_DIMENSIONS],
    "sitemap_page_metrics": ["brand_id", "page_id", "metric", "date", "platform"],
}

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
