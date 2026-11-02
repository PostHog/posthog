from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import Endpoint

BASE_URL = "https://api.getdx.com/"

ENDPOINTS: dict[str, Endpoint] = {
    "snapshots": {"path": "snapshots.list", "data_selector": "snapshots", "paginator": "single_page"},
    "teams": {"path": "teams.list", "data_selector": "teams", "paginator": "single_page"},
    "users": {
        "path": "users.list",
        "data_selector": "users",
        "params": {"page_size": 100, "page": 1},
        "paginator": {"type": "cursor", "cursor_path": "next_page", "cursor_param": "page"},
    },
    "team_audit_events": {
        "path": "teams.auditTrail",
        "data_selector": "events",
        "paginator": {"type": "cursor", "cursor_path": "response_metadata.next_cursor", "cursor_param": "cursor"},
    },
    "scorecards": {
        "path": "scorecards.list",
        "data_selector": "scorecards",
        "params": {"limit": 50, "include_unpublished": "true"},
        "paginator": {"type": "cursor", "cursor_path": "response_metadata.next_cursor", "cursor_param": "cursor"},
    },
}

PRIMARY_KEYS = ["id"]
