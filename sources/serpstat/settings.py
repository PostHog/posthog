from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ResponseAction

PAGE_SIZE = 100
MAX_PAGES = 5
POSITION_HISTORY_DAYS = 7
REQUEST_INTERVAL_SECONDS = 1.0
DOCS_BASE = "https://api-docs.serpstat.com/docs/serpstat-public-api/"


@frozen
class SerpstatEndpoint:
    method: str
    primary_keys: tuple[str, ...]
    docs_slug: str
    selector: str = "result.data"
    project_param: str | None = "project_id"
    total_pages_path: str | None = None
    size_param: str = "size"
    partition_key: str | None = None


ENDPOINTS = {
    "projects": SerpstatEndpoint(
        method="ProjectProcedure.getProjects",
        primary_keys=("project_id",),
        docs_slug="3ezca25cnkqw5-get-projects",
        project_param=None,
        total_pages_path="result.summary_info.page_total",
        partition_key="created_at",
    ),
    "project_keywords": SerpstatEndpoint(
        method="RtApiProcedure.getProjectKeywords",
        primary_keys=("project_id", "id"),
        docs_slug="c0a938de406c8-get-project-keywords",
        total_pages_path="result.summary_info.pages_count",
        partition_key="added",
    ),
    "project_regions": SerpstatEndpoint(
        method="RtApiSearchEngineProcedure.getProjectRegions",
        primary_keys=("project_id", "id"),
        docs_slug="f57863602271e-get-project-regions",
        selector="result.regions",
        project_param="projectId",
    ),
    "project_tags": SerpstatEndpoint(
        method="RtApiProcedure.getProjectTags",
        primary_keys=("project_id", "tag_uuid"),
        docs_slug="233a6b97f4943-get-project-tags",
    ),
    "project_positions": SerpstatEndpoint(
        method="RtApiProcedure.getProjectPositions",
        primary_keys=("project_id", "keyword_id"),
        docs_slug="e78a1e5708d44-get-project-positions",
        total_pages_path="result.summary_info.pages_count",
        size_param="page_size",
        partition_key="added",
    ),
}

AUTH_ERROR = "Serpstat authentication failed. Check your API token and API access for your plan."
QUOTA_ERROR = "Serpstat API credits are exhausted. Add credits or wait for your allowance to reset."
REQUEST_ERROR = "Serpstat rejected the request. Check your project ID, region ID, and API access."

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
