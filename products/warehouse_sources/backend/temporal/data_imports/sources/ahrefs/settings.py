from typing import NotRequired, TypedDict

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

API_BASE_URL = "https://api.ahrefs.com/v3"
MAX_PAGE_ROWS = 100
MAX_BACKLINK_ROWS = 1000
# History rows cost API units and plans cap how far back history goes, so a first sync reads a bounded window.
HISTORY_DAYS = 180

BACKLINK_FIELDS = (
    "url_from",
    "url_to",
    "anchor",
    "title",
    "link_type",
    "http_code",
    "domain_rating_source",
    "url_rating_source",
    "is_dofollow",
    "is_nofollow",
    "is_ugc",
    "is_sponsored",
    "is_content",
    "is_new",
    "is_spam",
    "name_source",
    "root_name_source",
    "links_external",
    "first_seen",
    "first_seen_link",
    "last_visited",
)


class EndpointSettings(TypedDict):
    path: str
    data_selector: str
    primary_keys: list[str]
    params: dict[str, str | int]
    description: str
    # Account-level tables don't take the configured Site Audit project.
    project_scoped: NotRequired[bool]
    # Site Explorer reports query the selected project's target with these parameters.
    target_params: NotRequired[list[str]]
    history: NotRequired[bool]


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
    "projects": {
        "path": "management/projects",
        "data_selector": "projects",
        "primary_keys": ["project_id"],
        "params": {},
        "description": "Every project in the Ahrefs workspace, with its target URL, scope, and protocol.",
        "project_scoped": False,
    },
    "domain_rating_history": {
        "path": "site-explorer/domain-rating-history",
        "data_selector": "domain_ratings",
        "primary_keys": ["project_id", "date"],
        "params": {"history_grouping": "monthly"},
        "description": "Monthly Domain Rating of the selected project's target.",
        "target_params": ["target"],
        "history": True,
    },
    "metrics_history": {
        "path": "site-explorer/metrics-history",
        "data_selector": "metrics",
        "primary_keys": ["project_id", "date"],
        "params": {
            "select": "date,org_traffic,org_cost,paid_traffic,paid_cost",
            "history_grouping": "monthly",
        },
        "description": "Monthly organic and paid search traffic and traffic value of the selected project's target.",
        "target_params": ["target", "mode", "protocol"],
        "history": True,
    },
    "backlinks": {
        "path": "site-explorer/all-backlinks",
        "data_selector": "backlinks",
        "primary_keys": ["project_id", "url_from", "url_to"],
        "params": {
            "select": ",".join(BACKLINK_FIELDS),
            "limit": MAX_BACKLINK_ROWS,
            "order_by": "domain_rating_source:desc",
            "history": "live",
            "aggregation": "similar_links",
        },
        "description": (
            f"Up to {MAX_BACKLINK_ROWS} live backlinks to the selected project's target, "
            "strongest referring domains first."
        ),
        "target_params": ["target", "mode", "protocol"],
    },
}

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: [incremental_field("date", IncrementalFieldType.Date)]
    for name, endpoint in ENDPOINTS.items()
    if endpoint.get("history")
}

AUTH_ERROR = "Ahrefs authentication failed. Check your API key in Account settings > API keys."
ACCESS_ERROR = "Ahrefs denied access. Check your plan, project access, and verified ownership for page data."
QUOTA_ERROR = "Ahrefs API units are exhausted. Increase your API key or workspace limit, or wait for renewal."
PROJECT_NOT_FOUND_ERROR = (
    "Ahrefs returned no target for the Site Audit project. Check the project ID and that the project has a target URL."
)

NON_RETRYABLE_ERRORS: dict[str, str | None] = {
    "ahrefs_invalid_api_key": AUTH_ERROR,
    "ahrefs_access_denied": ACCESS_ERROR,
    "ahrefs_quota_exceeded": QUOTA_ERROR,
    "ahrefs_project_not_found": PROJECT_NOT_FOUND_ERROR,
    "401 Client Error": AUTH_ERROR,
    "403 Client Error": ACCESS_ERROR,
    "402 Client Error": QUOTA_ERROR,
}
