from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SortMode
from products.warehouse_sources.backend.types import IncrementalField


@dataclass
class HyperspellEndpointConfig:
    name: str
    path: str
    # Response body key holding the row list (Hyperspell wraps every listing differently:
    # `items`, `documents`, `connections`, `integrations`).
    data_key: str
    primary_key: list[str]
    # Row arrival order where Hyperspell documents it ("newest first" on queries and context
    # documents), None where ordering is undocumented. Informational only today: every endpoint
    # is full-refresh, so no incremental watermark depends on it.
    sort_mode: Optional[SortMode] = None
    # Cursor-paginated endpoints take a `cursor` param and return `next_cursor` in the body.
    # Connections and integrations return the complete list in a single unpaginated response.
    paginated: bool = True
    # Hyperspell is inconsistent about the page-size param name: /memories/list and
    # /evaluate/queries take `size` (max 100), /entities and /context-documents take `limit`.
    size_param: str = "size"
    page_size: int = 100
    # Stable datetime field used for datetime partitioning, or None when the resource exposes
    # no immutable timestamp. We never partition on fields that move (e.g. updated_at,
    # last_modified_at) — only ones fixed at row creation.
    partition_key: Optional[str] = None
    # No Hyperspell list endpoint exposes a server-side updated-since/created-since filter
    # (memories only filter on source/collection/status/metadata), so every endpoint is
    # full-refresh only (empty incremental_fields).
    incremental_fields: list[IncrementalField] = field(default_factory=list)


HYPERSPELL_ENDPOINTS: dict[str, HyperspellEndpointConfig] = {
    "memories": HyperspellEndpointConfig(
        name="memories",
        path="/memories/list",
        data_key="items",
        # resource_id is only unique within its source provider (the read/update endpoints are
        # keyed by {source}/{resource_id}), so the composite key keeps rows unique table-wide.
        primary_key=["source", "resource_id"],
        # When Hyperspell first indexed the document — set once, never moves.
        partition_key="ingested_at",
    ),
    "connections": HyperspellEndpointConfig(
        name="connections",
        path="/connections/list",
        data_key="connections",
        primary_key=["id"],
        paginated=False,
    ),
    "integrations": HyperspellEndpointConfig(
        name="integrations",
        path="/integrations/list",
        data_key="integrations",
        primary_key=["id"],
        paginated=False,
    ),
    "entities": HyperspellEndpointConfig(
        name="entities",
        path="/entities",
        data_key="items",
        primary_key=["id"],
        size_param="limit",
        page_size=500,
        partition_key="created_at",
    ),
    "queries": HyperspellEndpointConfig(
        name="queries",
        path="/evaluate/queries",
        data_key="items",
        primary_key=["query_id"],
        sort_mode="desc",
        # `time` is when the query was issued; query log rows are immutable.
        partition_key="time",
    ),
    "context_documents": HyperspellEndpointConfig(
        name="context_documents",
        path="/context-documents",
        data_key="documents",
        primary_key=["document_id"],
        sort_mode="desc",
        size_param="limit",
        partition_key="created_at",
    ),
}

ENDPOINTS = tuple(HYPERSPELL_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in HYPERSPELL_ENDPOINTS.items()
}
