from typing import TypedDict

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalFieldType

BASE_URL = "https://api.peec.ai/customer"
PAGE_SIZE = 1000


class PeecAIEndpoint(TypedDict):
    path: str
    params: dict[str, str]
    total_path: str | None


ENDPOINTS: dict[str, PeecAIEndpoint] = {
    "chats": {
        "path": "chats",
        "params": {"include_archived_prompts": "true", "sort": "asc"},
        "total_path": "total_count",
    },
    "prompts": {"path": "prompts", "params": {"is_archived": "false"}, "total_path": "total_count"},
    "archived_prompts": {"path": "prompts", "params": {"is_archived": "true"}, "total_path": "total_count"},
    "brands": {"path": "brands", "params": {}, "total_path": "total_count"},
    "topics": {"path": "topics", "params": {}, "total_path": "total_count"},
    "tags": {"path": "tags", "params": {}, "total_path": "total_count"},
    "model_channels": {"path": "model-channels", "params": {}, "total_path": None},
}

INCREMENTAL_FIELDS = {"chats": [incremental_field("date", IncrementalFieldType.Date)]}

AUTH_ERRORS = {
    400: "Peec AI rejected the request. Check your API key, project ID, and start date.",
    401: "Your Peec AI API key is invalid. Create a new key and reconnect.",
    403: "Peec AI denied access. Check that your key can read this project and your plan includes API access.",
}
