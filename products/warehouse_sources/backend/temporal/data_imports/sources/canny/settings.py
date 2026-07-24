from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField

# Canny exposes every resource through a POST `/list` endpoint with skip/limit
# offset pagination and a `hasMore` flag in the body. The secret API key is sent as
# the `apiKey` POST body parameter. There is no server-side updated-since filter on
# any list endpoint, so every stream is full refresh only (see source.py / canny.py).


@dataclass
class CannyEndpointConfig:
    # Path under the API base (https://canny.io/api). Canny still serves every
    # resource we sync from its v1 list endpoints.
    path: str
    # Top-level key in the JSON response holding the array of records.
    data_key: str
    # Whether the endpoint supports skip/limit pagination. `boards/list` returns
    # every board in one response with no pagination params or `hasMore` flag.
    paginated: bool = True
    # Stable creation timestamp present on every Canny object — safe to partition on
    # because it never changes after a record is created (unlike a `lastSaved` field).
    partition_key: Optional[str] = "created"
    primary_keys: list[str] = field(default_factory=lambda: ["id"])


CANNY_ENDPOINTS: dict[str, CannyEndpointConfig] = {
    "boards": CannyEndpointConfig(path="/v1/boards/list", data_key="boards", paginated=False),
    "categories": CannyEndpointConfig(path="/v1/categories/list", data_key="categories"),
    # Changelog entries live under the `entries` list endpoint.
    "changelog_entries": CannyEndpointConfig(path="/v1/entries/list", data_key="entries"),
    "comments": CannyEndpointConfig(path="/v1/comments/list", data_key="comments"),
    "companies": CannyEndpointConfig(path="/v1/companies/list", data_key="companies"),
    "posts": CannyEndpointConfig(path="/v1/posts/list", data_key="posts"),
    "status_changes": CannyEndpointConfig(path="/v1/status_changes/list", data_key="statusChanges"),
    "tags": CannyEndpointConfig(path="/v1/tags/list", data_key="tags"),
    "users": CannyEndpointConfig(path="/v1/users/list", data_key="users"),
    "votes": CannyEndpointConfig(path="/v1/votes/list", data_key="votes"),
}

ENDPOINTS = tuple(CANNY_ENDPOINTS.keys())

# No endpoint exposes a server-side updated-since filter, so no stream is incremental.
# Kept for parity with other sources and for the (empty) per-endpoint advertised options.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {name: [] for name in CANNY_ENDPOINTS}
