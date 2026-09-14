from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField

# Canny exposes every resource through a POST `/list` endpoint. v1 endpoints use skip/limit
# offset pagination with a `hasMore` flag; v2 endpoints (users, companies, comments) use cursor
# pagination with a `cursor` string and a `hasNextPage` flag. The secret API key is sent as the
# `apiKey` POST body parameter for both. There is no server-side updated-since filter on any list
# endpoint, so every stream is full refresh only (see source.py / canny.py).

# Vendor API version labels. v1 is the long-standing wire; v2 is Canny's newer cursor-paginated
# implementation, offered so far only for the endpoints that set `v2_path` below.
CANNY_API_VERSION_V1 = "v1"
CANNY_API_VERSION_V2 = "v2"


@dataclass(frozen=False)
class CannyEndpointConfig:
    # v1 path under the API base (https://canny.io/api), with skip/limit offset pagination.
    path: str
    # Top-level key in the v1 JSON response holding the array of records.
    data_key: str
    # Whether the endpoint supports skip/limit pagination. `boards/list` returns
    # every board in one response with no pagination params or `hasMore` flag.
    paginated: bool = True
    # Stable creation timestamp present on every Canny object — safe to partition on
    # because it never changes after a record is created (unlike a `lastSaved` field).
    partition_key: Optional[str] = "created"
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # v2 cursor-paginated variant, where Canny offers one. When the resolved source pin is v2 and
    # these are set, the endpoint requests the v2 path with cursor pagination; otherwise it stays on
    # the v1 skip/limit path. Both are kept so the table set is identical across versions.
    v2_path: Optional[str] = None
    # Top-level key in the v2 JSON response holding the array of records. Canny keys this per
    # endpoint: `users/list` and `companies/list` keep their named `users`/`companies` keys, while
    # `comments/list` nests records under the generic `items`.
    v2_data_key: Optional[str] = None


CANNY_ENDPOINTS: dict[str, CannyEndpointConfig] = {
    "boards": CannyEndpointConfig(path="/v1/boards/list", data_key="boards", paginated=False),
    "categories": CannyEndpointConfig(path="/v1/categories/list", data_key="categories"),
    # Changelog entries live under the `entries` list endpoint.
    "changelog_entries": CannyEndpointConfig(path="/v1/entries/list", data_key="entries"),
    "comments": CannyEndpointConfig(
        path="/v1/comments/list", data_key="comments", v2_path="/v2/comments/list", v2_data_key="items"
    ),
    "companies": CannyEndpointConfig(
        path="/v1/companies/list", data_key="companies", v2_path="/v2/companies/list", v2_data_key="companies"
    ),
    "posts": CannyEndpointConfig(path="/v1/posts/list", data_key="posts"),
    "status_changes": CannyEndpointConfig(path="/v1/status_changes/list", data_key="statusChanges"),
    "tags": CannyEndpointConfig(path="/v1/tags/list", data_key="tags"),
    "users": CannyEndpointConfig(
        path="/v1/users/list", data_key="users", v2_path="/v2/users/list", v2_data_key="users"
    ),
    "votes": CannyEndpointConfig(path="/v1/votes/list", data_key="votes"),
}

ENDPOINTS = tuple(CANNY_ENDPOINTS.keys())

# No endpoint exposes a server-side updated-since filter, so no stream is incremental.
# Kept for parity with other sources and for the (empty) per-endpoint advertised options.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {name: [] for name in CANNY_ENDPOINTS}
