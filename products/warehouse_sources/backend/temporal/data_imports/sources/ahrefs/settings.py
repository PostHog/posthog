from typing import Any, Literal, NotRequired, TypedDict

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

API_BASE_URL = "https://api.ahrefs.com/v3"
MAX_PAGE_ROWS = 100
MAX_BACKLINK_ROWS = 1000
MAX_KEYWORD_ROWS = 1000
MAX_REFDOMAIN_ROWS = 1000
# Matches the largest Rank Tracker plan's tracked keyword allowance; the endpoint is free.
MAX_RANK_TRACKER_ROWS = 10000
# History rows cost API units and plans cap how far back history goes, so a first sync reads a bounded window.
HISTORY_DAYS = 180
# Link intersect requests accept at most 20 competitors.
MAX_COMPETITORS = 20
MAX_WEB_PAGE_ROWS = 1000
TOP_DOMAINS_COUNT = 1_000_000
TOP_DOMAINS_PAGE_ROWS = 100_000
# Each day costs 3 requests and at least 150 API units, so a first sync reads only the last week.
SITE_METRICS_FIRST_SYNC_DAYS = 7
# Longer than the longest sync frequency, so a scheduled sync leaves no day out.
SITE_METRICS_MAX_SYNC_DAYS = 31

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

ORGANIC_KEYWORD_FIELDS = (
    "keyword",
    "keyword_country",
    "language",
    "best_position",
    "best_position_url",
    "best_position_kind",
    "volume",
    "sum_traffic",
    "cpc",
    "serp_features",
    "is_branded",
    "is_commercial",
    "is_informational",
    "is_navigational",
    "is_transactional",
    "last_update",
)

REFDOMAIN_FIELDS = (
    "domain",
    "domain_rating",
    "links_to_target",
    "dofollow_links",
    "is_root_domain",
    "is_spam",
    "positions_source_domain",
    "first_seen",
    "last_seen",
)

RANK_TRACKER_FIELDS = (
    "keyword",
    "country",
    "location",
    "language",
    "position",
    "url",
    "best_position_kind",
    "traffic",
    "volume",
    "keyword_difficulty",
    "cost_per_click",
    "serp_features",
    "tags",
    "keyword_is_frozen",
    "serp_updated",
    "created_at",
)


class DailyReport(TypedDict):
    path: str
    data_selector: str
    target_params: list[str]
    # Response field to row column.
    columns: dict[str, str]


SITE_METRICS_REPORTS: list[DailyReport] = [
    {
        "path": "site-explorer/domain-rating",
        "data_selector": "domain_rating",
        "target_params": ["target"],
        "columns": {"domain_rating": "domain_rating", "ahrefs_rank": "ahrefs_rank"},
    },
    {
        "path": "site-explorer/backlinks-stats",
        "data_selector": "metrics",
        "target_params": ["target", "mode", "protocol"],
        "columns": {"live": "live_backlinks", "live_refdomains": "live_refdomains"},
    },
    {
        "path": "site-explorer/metrics",
        "data_selector": "metrics",
        "target_params": ["target", "mode", "protocol"],
        "columns": {
            "org_keywords": "org_keywords",
            "org_keywords_1_3": "org_keywords_1_3",
            "org_traffic": "org_traffic",
            "org_cost": "org_cost",
        },
    },
]


class EndpointSettings(TypedDict):
    # Tables built from more than one report have no single path or data selector.
    path: NotRequired[str]
    data_selector: NotRequired[str]
    primary_keys: list[str]
    params: dict[str, str | int]
    description: str
    # Account-level tables don't take the configured Site Audit project.
    project_scoped: NotRequired[bool]
    # Site Explorer reports query the selected project's target with these parameters.
    target_params: NotRequired[list[str]]
    history: NotRequired[bool]
    # POST reports take their parameters as a JSON body instead of the query string.
    body: NotRequired[dict[str, Any]]
    # Reports that need more inputs than the project's target, or more than one request.
    kind: NotRequired[Literal["link_intersect", "brand_radar", "top_domains"]]
    # Snapshot reports require the report date; each sync reads today's state.
    snapshot_date: NotRequired[bool]
    # Rank Tracker reports one device per request, so the table reads each and tags rows with it.
    devices: NotRequired[list[str]]
    # Each sync adds one row per day, merged from these reports for that date.
    daily_reports: NotRequired[list[DailyReport]]


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
    "site_metrics_daily": {
        "primary_keys": ["project_id", "date"],
        "params": {},
        "description": (
            "Daily Domain Rating, Ahrefs Rank, live backlink and referring domain totals, and organic "
            "keyword and traffic totals of the selected project's target."
        ),
        "daily_reports": SITE_METRICS_REPORTS,
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
    "link_intersect_refdomains": {
        "path": "competitive-analysis/link-intersect-refdomains",
        "data_selector": "referring-domains",
        "primary_keys": ["project_id", "domain"],
        "params": {},
        "body": {
            "select": ["domain", "domain_rating", "intersect", "links_to_target"],
            "order_by": ["intersect:desc", "domain_rating:desc"],
            "limit": MAX_BACKLINK_ROWS,
        },
        "description": (
            f"Up to {MAX_BACKLINK_ROWS} referring domains that link to the selected project's target "
            "or its competitors in Ahrefs, most shared first."
        ),
        "kind": "link_intersect",
    },
    "link_intersect_refpages": {
        "path": "competitive-analysis/link-intersect-refpages",
        "data_selector": "referring-pages",
        "primary_keys": ["project_id", "url"],
        "params": {},
        "body": {
            "select": ["url", "title", "domain_rating", "url_rating", "intersect", "links_to_target"],
            "order_by": ["intersect:desc", "domain_rating:desc"],
            "limit": MAX_BACKLINK_ROWS,
        },
        "description": (
            f"Up to {MAX_BACKLINK_ROWS} referring pages that link to the selected project's target "
            "or its competitors in Ahrefs, most shared first."
        ),
        "kind": "link_intersect",
    },
    "brand_radar_web_pages": {
        "path": "brand-radar/web-pages",
        "data_selector": "pages",
        "primary_keys": ["project_id", "report_id", "url"],
        "params": {},
        "body": {
            "select": ["url", "title", "content", "domain_rating", "referring_domains", "traffic", "traffic_value"],
            "order_by": "traffic",
            "limit": MAX_WEB_PAGE_ROWS,
        },
        "description": (
            f"Up to {MAX_WEB_PAGE_ROWS} web pages with the most traffic that mention the brands "
            "in each Brand Radar report linked to the selected project."
        ),
        "kind": "brand_radar",
    },
    "domain_rating_top_domains": {
        "path": "public/domain-rating-top-domains",
        "data_selector": "domains",
        "primary_keys": ["domain"],
        "params": {},
        "description": "The top 1 million domains ranked by Ahrefs Domain Rating. Free to sync.",
        "project_scoped": False,
        "kind": "top_domains",
    },
    "organic_keywords": {
        "path": "site-explorer/organic-keywords",
        "data_selector": "keywords",
        "primary_keys": ["project_id", "keyword", "keyword_country"],
        "params": {
            "select": ",".join(ORGANIC_KEYWORD_FIELDS),
            "limit": MAX_KEYWORD_ROWS,
            "order_by": "sum_traffic:desc",
        },
        "description": (
            f"Up to {MAX_KEYWORD_ROWS} keywords the selected project's target ranks for in organic search, "
            "highest traffic first."
        ),
        "target_params": ["target", "mode", "protocol"],
        "snapshot_date": True,
    },
    "referring_domains": {
        "path": "site-explorer/refdomains",
        "data_selector": "refdomains",
        "primary_keys": ["project_id", "domain"],
        "params": {
            "select": ",".join(REFDOMAIN_FIELDS),
            "limit": MAX_REFDOMAIN_ROWS,
            "order_by": "domain_rating:desc",
            "history": "live",
        },
        "description": (
            f"Up to {MAX_REFDOMAIN_ROWS} domains with live links to the selected project's target, "
            "highest Domain Rating first."
        ),
        "target_params": ["target", "mode", "protocol"],
    },
    "rank_tracker_overview": {
        "path": "rank-tracker/overview",
        "data_selector": "overviews",
        "primary_keys": ["project_id", "device", "keyword", "country", "location", "language"],
        "params": {
            "select": ",".join(RANK_TRACKER_FIELDS),
            "limit": MAX_RANK_TRACKER_ROWS,
            "order_by": "keyword:asc",
        },
        "description": "Current desktop and mobile rankings of the keywords tracked in the project's Rank Tracker.",
        "snapshot_date": True,
        "devices": ["desktop", "mobile"],
    },
}

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: [incremental_field("date", IncrementalFieldType.Date)]
    for name, endpoint in ENDPOINTS.items()
    if endpoint.get("history") or endpoint.get("daily_reports")
}

AUTH_ERROR = "Ahrefs authentication failed. Check your API key in Account settings > API keys."
ACCESS_ERROR = "Ahrefs denied access. Check your plan, project access, and verified ownership for page data."
QUOTA_ERROR = "Ahrefs API units are exhausted. Increase your API key or workspace limit, or wait for renewal."
# The units renew each period, so the schema stays enabled and keeps retrying. Disabling it would
# leave the sync off after the units come back.
QUOTA_RETRY_ERROR = (
    "Your Ahrefs API units ran out, so this sync can't finish. It tries again on its own and works again "
    "once you raise your API key or workspace unit limit, or the units renew."
)
PROJECT_NOT_FOUND_ERROR = (
    "Ahrefs returned no target for the Site Audit project. Check the project ID and that the project has a target URL."
)

NON_RETRYABLE_ERRORS: dict[str, str | None] = {
    "ahrefs_invalid_api_key": AUTH_ERROR,
    "ahrefs_access_denied": ACCESS_ERROR,
    "ahrefs_project_not_found": PROJECT_NOT_FOUND_ERROR,
    "401 Client Error": AUTH_ERROR,
    "403 Client Error": ACCESS_ERROR,
}

RETRYABLE_QUOTA_ERRORS: frozenset[str] = frozenset({"ahrefs_quota_exceeded", "402 Client Error"})

CREDENTIAL_ERRORS: dict[str, str | None] = {**NON_RETRYABLE_ERRORS, "ahrefs_quota_exceeded": QUOTA_ERROR}
