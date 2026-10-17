from typing import Optional

from posthog.dataclasses import frozen

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
    limit: int = 250  # v2 list endpoints accept up to 250 results per page
    response_params: tuple[tuple[str, str], ...] = ()


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
        response_params=(("description-format", "plain"), ("include-icon", "true")),
    ),
    "pages": ConfluenceEndpointConfig(
        name="pages",
        path="/pages",
        partition_key="createdAt",
        response_params=(("body-format", "storage"),),
    ),
    "blogposts": ConfluenceEndpointConfig(
        name="blogposts",
        path="/blogposts",
        partition_key="createdAt",
        response_params=(("body-format", "storage"),),
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
        response_params=(("body-format", "storage"),),
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
        response_params=(("body-format", "storage"),),
    ),
    "inline_comments": ConfluenceEndpointConfig(
        name="inline_comments",
        path="/inline-comments",
        response_params=(("body-format", "storage"),),
    ),
}

ENDPOINTS = tuple(CONFLUENCE_ENDPOINTS.keys())

# No endpoint supports server-side incremental filtering (see note above), so no
# endpoint advertises incremental fields.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {name: [] for name in CONFLUENCE_ENDPOINTS}
