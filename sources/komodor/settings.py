from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import Endpoint

API_DOCS_URL = "https://api.komodor.com/api/docs/index.html"
REGION_URLS = {"us": "https://api.komodor.com", "eu": "https://api.eu.komodor.com"}
PAGE_SIZE = 100

ENDPOINTS: dict[str, Endpoint] = {
    "services": {"path": "services/search", "method": "POST", "data_selector": "data.services"},
    "jobs": {"path": "jobs/search", "method": "POST", "data_selector": "data.jobs"},
    "clusters": {"path": "clusters", "data_selector": "data.clusters"},
    "monitors": {"path": "realtime-monitors/config", "data_selector": "data.monitors"},
}

PRIMARY_KEYS = {
    "services": ["cluster", "namespace", "kind", "service"],
    "jobs": ["cluster", "namespace", "kind", "name"],
    "clusters": ["name"],
    "monitors": ["id"],
}

AUTH_ERRORS = {
    "401 Client Error": "Komodor rejected the API key. Check your API key and selected region.",
    "403 Client Error": "Komodor denied access. Check your API key, selected region, and read permissions.",
}
