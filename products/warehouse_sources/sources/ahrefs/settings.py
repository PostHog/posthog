from typing import TypedDict

API_BASE_URL = "https://api.ahrefs.com/v3"
MAX_PAGE_ROWS = 100


class EndpointSettings(TypedDict):
    path: str
    data_selector: str
    primary_keys: list[str]
    params: dict[str, str | int]
    description: str


ENDPOINTS: dict[str, EndpointSettings] = {
    "site_audit_health_scores": {
        "path": "site-audit/projects",
        "data_selector": "healthscores",
        "primary_keys": ["project_id"],
        "params": {},
        "description": "Health score and crawl totals for the selected Site Audit project.",
    },
    "site_audit_issues": {
        "path": "site-audit/issues",
        "data_selector": "issues",
        "primary_keys": ["project_id", "issue_id"],
        "params": {},
        "description": "Issue summaries from the latest crawl of the selected Site Audit project.",
    },
    "site_audit_pages": {
        "path": "site-audit/page-explorer",
        "data_selector": "pages",
        "primary_keys": ["project_id", "url"],
        "params": {
            "select": "url,http_code,title,depth,is_html",
            "limit": MAX_PAGE_ROWS,
            "order_by": "url:asc",
        },
        "description": f"The first {MAX_PAGE_ROWS} crawled URLs, ordered by URL. Requires verified project ownership.",
    },
}

AUTH_ERROR = "Ahrefs authentication failed. Check your API key in Account settings > API keys."
ACCESS_ERROR = "Ahrefs denied access. Check your plan, project access, and verified ownership for page data."
QUOTA_ERROR = "Ahrefs API units are exhausted. Increase your API key or workspace limit, or wait for renewal."

NON_RETRYABLE_ERRORS: dict[str, str | None] = {
    "ahrefs_invalid_api_key": AUTH_ERROR,
    "ahrefs_access_denied": ACCESS_ERROR,
    "ahrefs_quota_exceeded": QUOTA_ERROR,
    "401 Client Error": AUTH_ERROR,
    "403 Client Error": ACCESS_ERROR,
    "402 Client Error": QUOTA_ERROR,
}
