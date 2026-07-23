from dataclasses import dataclass, field
from typing import Any, Literal

from products.warehouse_sources.backend.types import IncrementalField

# Plunk caps both `limit` (cursor-paginated endpoints) and `pageSize` (page-number endpoints)
# at 100; larger values are silently clamped server-side.
DEFAULT_PAGE_SIZE = 100

# How a list endpoint paginates:
# - "cursor": `limit` + `cursor` query params; response is `{data, total, cursor, hasMore}`
#   where `cursor` is omitted on the last page.
# - "page": `page` + `pageSize` query params; response is `{data, total, page, pageSize, totalPages}`.
# - "single": the endpoint returns the whole collection as a bare JSON array in one response.
PaginationStyle = Literal["cursor", "page", "single"]


@dataclass
class PlunkEndpointConfig:
    name: str
    # Path under the API base URL (Plunk's data endpoints carry no version prefix).
    path: str
    pagination: PaginationStyle
    primary_key: str = "id"
    # Static query params for every request. Plunk's list endpoints accept an explicit
    # `sort=createdAt&dir=asc`, which keeps pagination stable while rows are inserted mid-sync.
    params: dict[str, Any] = field(default_factory=dict)
    # A STABLE datetime field to partition by — never one that mutates on update.
    partition_key: str | None = "createdAt"
    # The order rows actually arrive in given `params` (or the endpoint's fixed default order).
    sort_mode: Literal["asc", "desc"] = "asc"
    # Plunk exposes no server-side updated-since/created-after filter on any list endpoint
    # (verified against the API source), so every endpoint is full-refresh only.
    incremental_fields: list[IncrementalField] = field(default_factory=list)


PLUNK_ENDPOINTS: dict[str, PlunkEndpointConfig] = {
    "contacts": PlunkEndpointConfig(
        name="contacts",
        path="/contacts",
        pagination="cursor",
        params={"limit": DEFAULT_PAGE_SIZE, "sort": "createdAt", "dir": "asc"},
    ),
    "campaigns": PlunkEndpointConfig(
        name="campaigns",
        path="/campaigns",
        pagination="page",
        params={"pageSize": DEFAULT_PAGE_SIZE, "sort": "createdAt", "dir": "asc"},
    ),
    "templates": PlunkEndpointConfig(
        name="templates",
        path="/templates",
        pagination="page",
        params={"pageSize": DEFAULT_PAGE_SIZE, "sort": "createdAt", "dir": "asc"},
    ),
    # Returns every segment as a bare JSON array (newest first), so there is nothing to
    # paginate or partition — projects hold at most a handful of segments.
    "segments": PlunkEndpointConfig(
        name="segments",
        path="/segments",
        pagination="single",
        partition_key=None,
        sort_mode="desc",
    ),
}

ENDPOINTS = tuple(PLUNK_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in PLUNK_ENDPOINTS.items()
}
