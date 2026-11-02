from dataclasses import field

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ResponseAction
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

PAGE_SIZE = 100
MAX_PAGES = 5
POSITION_HISTORY_DAYS = 7
REQUEST_INTERVAL_SECONDS = 1.0
DOCS_BASE = "https://api-docs.serpstat.com/docs/serpstat-public-api/"
SPEC_BASE = "https://raw.githubusercontent.com/SerpstatGlobal/serpstat-mcp-server-java/main/doc/openapi_spec/"
DOMAIN_ANALYSIS_DOCS_URL = SPEC_BASE + "Serpstat-Domain-Analysis-API.json"
BACKLINKS_DOCS_URL = SPEC_BASE + "Serpstat-Backlinks-API.json"
DEFAULT_SEARCH_ENGINE = "g_us"
# getDomainsHistory has no page parameter, so one request at the maximum size reads the whole history.
DOMAIN_HISTORY_PAGE_SIZE = 1000


@frozen
class SerpstatEndpoint:
    method: str
    primary_keys: tuple[str, ...]
    docs_url: str
    selector: str = "result.data"
    project_param: str | None = "project_id"
    domain_param: str | None = None
    search_engine: bool = False
    total_pages_path: str | None = None
    # For methods that return a row total instead of a page total: a short page is the last page.
    stop_on_short_page: bool = False
    size_param: str = "size"
    partition_key: str | None = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)

    @property
    def paginated(self) -> bool:
        return self.total_pages_path is not None or self.stop_on_short_page


ENDPOINTS = {
    "projects": SerpstatEndpoint(
        method="ProjectProcedure.getProjects",
        primary_keys=("project_id",),
        docs_url=DOCS_BASE + "3ezca25cnkqw5-get-projects",
        project_param=None,
        total_pages_path="result.summary_info.page_total",
        partition_key="created_at",
    ),
    "project_keywords": SerpstatEndpoint(
        method="RtApiProcedure.getProjectKeywords",
        primary_keys=("project_id", "id"),
        docs_url=DOCS_BASE + "c0a938de406c8-get-project-keywords",
        total_pages_path="result.summary_info.pages_count",
        partition_key="added",
    ),
    "project_regions": SerpstatEndpoint(
        method="RtApiSearchEngineProcedure.getProjectRegions",
        primary_keys=("project_id", "id"),
        docs_url=DOCS_BASE + "f57863602271e-get-project-regions",
        selector="result.regions",
        project_param="projectId",
    ),
    "project_tags": SerpstatEndpoint(
        method="RtApiProcedure.getProjectTags",
        primary_keys=("project_id", "tag_uuid"),
        docs_url=DOCS_BASE + "233a6b97f4943-get-project-tags",
    ),
    "project_positions": SerpstatEndpoint(
        method="RtApiProcedure.getProjectPositions",
        primary_keys=("project_id", "keyword_id"),
        docs_url=DOCS_BASE + "e78a1e5708d44-get-project-positions",
        total_pages_path="result.summary_info.pages_count",
        size_param="page_size",
        partition_key="added",
    ),
    "domain_info": SerpstatEndpoint(
        method="SerpstatDomainProcedure.getDomainsInfo",
        primary_keys=("domain",),
        docs_url=DOMAIN_ANALYSIS_DOCS_URL,
        project_param=None,
        domain_param="domains",
        search_engine=True,
    ),
    "domain_history": SerpstatEndpoint(
        method="SerpstatDomainProcedure.getDomainsHistory",
        primary_keys=("domain", "date"),
        docs_url=DOMAIN_ANALYSIS_DOCS_URL,
        project_param=None,
        domain_param="domain",
        search_engine=True,
        partition_key="date",
        incremental_fields=[incremental_field("date", IncrementalFieldType.Date)],
    ),
    "domain_keywords": SerpstatEndpoint(
        method="SerpstatDomainProcedure.getDomainKeywords",
        primary_keys=("domain", "keyword", "url"),
        docs_url=DOMAIN_ANALYSIS_DOCS_URL,
        project_param=None,
        domain_param="domain",
        search_engine=True,
        stop_on_short_page=True,
    ),
    "backlinks": SerpstatEndpoint(
        method="SerpstatBacklinksProcedure.getNewBacklinks",
        primary_keys=("url_from", "url_to", "link_type", "link_text"),
        docs_url=BACKLINKS_DOCS_URL,
        project_param=None,
        domain_param="query",
        stop_on_short_page=True,
    ),
}

AUTH_ERROR = "Serpstat authentication failed. Check your API token and API access for your plan."
QUOTA_ERROR = "Serpstat API credits are exhausted. Add credits or wait for your allowance to reset."
REQUEST_ERROR = "Serpstat rejected the request. Check your project ID, region ID, and API access."
DOMAIN_ERROR = "Enter a domain in the Serpstat source settings to sync the domain and backlink tables."

_RATE_LIMIT_RESPONSE_ACTIONS: list[ResponseAction] = [
    {"content": message, "action": "retry", "message": "Serpstat request rate exceeded. Try again later."}
    for message in ("Query frequency exceeded", "Too many queries")
]

RESPONSE_ACTIONS: list[ResponseAction] = [
    *_RATE_LIMIT_RESPONSE_ACTIONS,
    {"json_field": "error.code", "json_values": [429, -429], "action": "retry"},
    {"json_field": "error.code", "json_values": [500, -32603], "action": "retry"},
    {"status_code": 401, "action": "raise", "message": AUTH_ERROR},
    {"status_code": 402, "action": "raise", "message": QUOTA_ERROR},
    {"json_field": "error.code", "json_values": [-32012, 32012, 402], "action": "raise", "message": QUOTA_ERROR},
    {"content": "Not enough credits", "action": "raise", "message": QUOTA_ERROR},
    {"content": "Plan credit exceeded", "action": "raise", "message": QUOTA_ERROR},
    {"content": "Pricing plan credits exceeded", "action": "raise", "message": QUOTA_ERROR},
    {"json_field": "error.code", "json_values": [-32020, 401, 403], "action": "raise", "message": AUTH_ERROR},
    {"status_code": 403, "action": "raise", "message": AUTH_ERROR},
    {"content": "Invalid token", "action": "raise", "message": AUTH_ERROR},
    {"content": "Problems with authorization", "action": "raise", "message": AUTH_ERROR},
    {"content": "API not allowed for your plan", "action": "raise", "message": AUTH_ERROR},
    {"status_code": 400, "action": "raise", "message": REQUEST_ERROR},
    {"content": '"error"', "action": "raise", "message": REQUEST_ERROR},
]

# Serpstat answers "Data not found" when a domain or an incremental window has no rows.
DOMAIN_RESPONSE_ACTIONS: list[ResponseAction] = [
    {"json_field": "error.code", "json_values": [32017, -32017], "action": "ignore"},
    *RESPONSE_ACTIONS,
]
