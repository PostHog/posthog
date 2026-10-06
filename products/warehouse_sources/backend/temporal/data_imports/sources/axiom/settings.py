from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import Endpoint

API_VERSION = "v2"
BASE_URL = f"https://api.axiom.co/{API_VERSION}/"
PAGE_SIZE = 100
PRIMARY_KEYS = ["id"]

ENDPOINTS: dict[str, Endpoint] = {
    "datasets": {"path": "datasets", "paginator": "single_page"},
    "monitors": {"path": "monitors", "paginator": "single_page"},
    "annotations": {"path": "annotations", "paginator": "single_page"},
    "dashboards": {
        "path": "dashboards",
        "paginator": {"type": "offset", "limit": PAGE_SIZE, "total_path": None},
    },
    "saved_queries": {
        "path": "apl-starred-queries",
        "params": {"who": "all"},
        "paginator": {"type": "offset", "limit": PAGE_SIZE, "total_path": None},
    },
}

AUTH_ERRORS = {
    401: "Axiom rejected the token. Check that the token is valid and has not expired.",
    403: "Axiom denied access. Check the token permissions and the organization ID for personal access tokens.",
}
