from typing import Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SortMode
from products.warehouse_sources.backend.types import IncrementalField


@frozen
class ConfluenceEndpointConfig:
    name: str
    path: str  # Path relative to the v2 API base, e.g. "/pages"
    primary_key: str = "id"
    # Stable, immutable datetime field used for partitioning. Confluence's v2
    # objects expose `createdAt` at the top level (never use a mutable field
    # like the nested version timestamp). `None` for resources that don't carry
    # a top-level creation timestamp (labels, comments).
    partition_key: Optional[str] = None
    updated_at_path: tuple[str, ...] | None = None
    sort_mode: SortMode = "asc"
    limit: int = 250  # v2 list endpoints accept up to 250 results per page


# Confluence Cloud REST API v2 top-level list endpoints. All use cursor-based
# pagination (`_links.next`) and require no parent context to enumerate.
CONFLUENCE_ENDPOINTS: dict[str, ConfluenceEndpointConfig] = {
    "spaces": ConfluenceEndpointConfig(
        name="spaces",
        path="/spaces",
        partition_key="createdAt",
    ),
    "pages": ConfluenceEndpointConfig(
        name="pages",
        path="/pages",
        partition_key="createdAt",
        updated_at_path=("version", "createdAt"),
        sort_mode="desc",
    ),
    "blogposts": ConfluenceEndpointConfig(
        name="blogposts",
        path="/blogposts",
        partition_key="createdAt",
        updated_at_path=("version", "createdAt"),
        sort_mode="desc",
    ),
    "attachments": ConfluenceEndpointConfig(
        name="attachments",
        path="/attachments",
        partition_key="createdAt",
        updated_at_path=("version", "createdAt"),
        sort_mode="desc",
    ),
    "tasks": ConfluenceEndpointConfig(
        name="tasks",
        path="/tasks",
        partition_key="createdAt",
    ),
    # Labels and comments don't carry a top-level creation timestamp, so they
    # have no stable partition key.
    "labels": ConfluenceEndpointConfig(
        name="labels",
        path="/labels",
    ),
    "footer_comments": ConfluenceEndpointConfig(
        name="footer_comments",
        path="/footer-comments",
        updated_at_path=("version", "createdAt"),
        sort_mode="desc",
    ),
    "inline_comments": ConfluenceEndpointConfig(
        name="inline_comments",
        path="/inline-comments",
        updated_at_path=("version", "createdAt"),
        sort_mode="desc",
    ),
}

ENDPOINTS = tuple(CONFLUENCE_ENDPOINTS.keys())

UPDATED_AT_FIELD = incremental_field("updated_at", label="Updated at")

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: [UPDATED_AT_FIELD] if config.updated_at_path else [] for name, config in CONFLUENCE_ENDPOINTS.items()
}
