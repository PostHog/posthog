from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField


@dataclass(frozen=True)
class ConfluenceEndpointConfig:
    name: str
    path: str  # Path relative to the v2 API base, e.g. "/pages"
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Stable, immutable datetime field used for partitioning. Confluence's v2
    # objects expose `createdAt` at the top level (never use a mutable field
    # like the nested version timestamp). `None` for resources that don't carry
    # a top-level creation timestamp (labels, comments).
    partition_key: Optional[str] = None
    limit: int = 250  # v2 list endpoints accept up to 250 results per page
    # Set for child resources listed per parent content item (e.g. permissions per page).
    fanout: Optional[DependentEndpointConfig] = None

    @property
    def page_size(self) -> int:
        return self.limit

    @property
    def incremental_fields(self) -> list[IncrementalField]:
        return []

    @property
    def default_incremental_field(self) -> Optional[str]:
        return None


def _permissions_fanout(parent_name: str, parent_id_column: str) -> DependentEndpointConfig:
    return DependentEndpointConfig(
        parent_name=parent_name,
        resolve_param="id",
        resolve_field="id",
        include_from_parent=["id"],
        parent_field_renames={"id": parent_id_column},
        # A page or blog post deleted between the parent listing and its permissions fetch 404s.
        child_response_actions=[{"status_code": 404, "action": "ignore"}],
    )


# Confluence Cloud REST API v2 list endpoints. All use cursor-based pagination
# (`_links.next`). Endpoints with a `fanout` are listed once per parent content item.
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
    # Direct read/update restrictions per content item. Databases, whiteboards and folders expose the
    # same endpoint but have no list endpoint to fan out from. Entries carry no id, so the key is the
    # content item plus the (operation, principal) pair.
    "page_permissions": ConfluenceEndpointConfig(
        name="page_permissions",
        path="/pages/{id}/permissions",
        primary_keys=["pageId", "operation", "principalType", "principalId"],
        fanout=_permissions_fanout("pages", "pageId"),
    ),
    "blogpost_permissions": ConfluenceEndpointConfig(
        name="blogpost_permissions",
        path="/blogposts/{id}/permissions",
        primary_keys=["blogPostId", "operation", "principalType", "principalId"],
        fanout=_permissions_fanout("blogposts", "blogPostId"),
    ),
}

# Permission tables make one request per page or blog post, so they are opt-in.
SHOULD_SYNC_DEFAULT: dict[str, bool] = {"page_permissions": False, "blogpost_permissions": False}

ENDPOINTS = tuple(CONFLUENCE_ENDPOINTS.keys())

# No endpoint supports server-side incremental filtering (see note above), so no
# endpoint advertises incremental fields.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {name: [] for name in CONFLUENCE_ENDPOINTS}
