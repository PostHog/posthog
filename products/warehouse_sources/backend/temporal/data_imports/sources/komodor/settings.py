from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import Endpoint
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

API_DOCS_URL = "https://api.komodor.com/api/docs/index.html"
REGION_URLS = {"us": "https://api.komodor.com", "eu": "https://api.eu.komodor.com"}
PAGE_SIZE = 100
COST_ALLOCATION_PAGE_SIZE = 1000

# Issue and event searches accept at most 2 days per request and reach at most 7 days back.
SEARCH_WINDOW_SECONDS = 2 * 24 * 60 * 60
SEARCH_RETENTION_SECONDS = 7 * 24 * 60 * 60
# Keeps the first window inside the 7-day limit when our clock runs ahead of Komodor's.
SEARCH_RETENTION_MARGIN_SECONDS = 10 * 60
# Issues and events change status after they start, so each incremental run reads the last window again.
SEARCH_INCREMENTAL_OVERLAP_SECONDS = SEARCH_WINDOW_SECONDS


@frozen
class WindowedSearch:
    path: str
    data_selector: str
    types: tuple[str, ...]
    cursor_path: str
    pagination_field: str
    statuses: tuple[str, ...] | None = None


WINDOWED_SEARCHES: dict[str, WindowedSearch] = {
    "cluster_issues": WindowedSearch(
        path="clusters/issues/search",
        data_selector="data.issues",
        types=("availability", "failed-deploy", "node-issue", "pvc-issue", "workflow-issue"),
        cursor_path="meta.nextPage",
        pagination_field="page",
        statuses=("open", "closed"),
    ),
    "k8s_events": WindowedSearch(
        path="clusters/k8s-events/search",
        data_selector="data.events",
        types=("deploy", "node-terminated", "node-created"),
        cursor_path="meta.token",
        pagination_field="token",
    ),
}

ENDPOINTS: dict[str, Endpoint] = {
    "services": {"path": "services/search", "method": "POST", "data_selector": "data.services"},
    "jobs": {"path": "jobs/search", "method": "POST", "data_selector": "data.jobs"},
    "clusters": {"path": "clusters", "data_selector": "data.clusters"},
    "monitors": {"path": "realtime-monitors/config", "data_selector": "data.monitors"},
    **{
        name: {"path": search.path, "method": "POST", "data_selector": search.data_selector}
        for name, search in WINDOWED_SEARCHES.items()
    },
    "cost_allocation": {
        "path": "cost/allocation",
        "data_selector": "groupedCosts",
        "params": {"timeFrame": "Past_30_days", "groupBy": "komodorServiceName", "pageSize": COST_ALLOCATION_PAGE_SIZE},
    },
}

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: [incremental_field("startTime", IncrementalFieldType.Integer)] for name in WINDOWED_SEARCHES
}

PRIMARY_KEYS = {
    "services": ["cluster", "namespace", "kind", "service"],
    "jobs": ["cluster", "namespace", "kind", "name"],
    "clusters": ["name"],
    "monitors": ["id"],
    "cluster_issues": ["cluster", "type", "startTime", "link"],
    "k8s_events": ["cluster", "type", "startTime", "link"],
    "cost_allocation": ["komodorServiceId"],
}

AUTH_ERRORS = {
    "401 Client Error": "Komodor rejected the API key. Check your API key and selected region.",
    "403 Client Error": "Komodor denied access. Check your API key, selected region, and read permissions.",
}
