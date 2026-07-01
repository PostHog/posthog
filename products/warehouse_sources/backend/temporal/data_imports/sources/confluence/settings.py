from dataclasses import dataclass
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField


@dataclass
class ConfluenceEndpointConfig:
    name: str
    path: str  # Path relative to the v2 API base, e.g. "/pages"
    primary_key: str = "id"
    # Stable, immutable datetime field used for partitioning. Confluence's v2
    # objects expose `createdAt` at the top level (never use a mutable field
    # like the nested version timestamp). `None` for resources that don't carry
    # a top-level creation timestamp (labels, comments).
    partition_key: Optional[str] = None
    limit: int = 250  # v2 list endpoints accept up to 250 results per page


# Confluence Cloud REST API v2 top-level list endpoints. All use cursor-based
# pagination (`_links.next`) and require no parent context to enumerate.
#
# We intentionally ship every endpoint as full-refresh: the v2 list endpoints
# expose a `sort` parameter but NO server-side timestamp filter (there is no
# `since` / `modified_after` / `created-date>=` query param), so an "incremental"
# sync would still page through the entire collection every run. Per the
# implementing-warehouse-sources guidance we only advertise incremental when a
# genuine server-side filter exists, so all endpoints here are full refresh.
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
    ),
    "blogposts": ConfluenceEndpointConfig(
        name="blogposts",
        path="/blogposts",
        partition_key="createdAt",
    ),
    "attachments": ConfluenceEndpointConfig(
        name="attachments",
        path="/attachments",
        partition_key="createdAt",
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
    ),
    "inline_comments": ConfluenceEndpointConfig(
        name="inline_comments",
        path="/inline-comments",
    ),
}

ENDPOINTS = tuple(CONFLUENCE_ENDPOINTS.keys())

# No endpoint supports server-side incremental filtering (see note above), so no
# endpoint advertises incremental fields.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {name: [] for name in CONFLUENCE_ENDPOINTS}
