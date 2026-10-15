from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource

BASE_URL = "https://open.acast.com/rest/"

ENDPOINTS: dict[str, EndpointResource] = {
    "shows": {
        "name": "shows",
        "endpoint": {"path": "shows"},
    },
    "episodes": {
        "name": "episodes",
        "include_from_parent": ["_id"],
        "endpoint": {
            "path": "shows/{show_id}/episodes",
            "params": {"show_id": {"type": "resolve", "resource": "shows", "field": "_id"}},
        },
    },
}

PRIMARY_KEYS = {"shows": ["_id"], "episodes": ["show_id", "_id"]}

AUTH_ERROR = "Acast rejected the API key. Contact Acast Customer Success to check or replace the key."
PERMISSION_ERROR = "Acast denied access. Ask Acast Customer Success to check the shows assigned to your API key."
