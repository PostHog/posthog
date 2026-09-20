from dataclasses import dataclass, field
from typing import Any, Literal, Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField

# v2 list endpoints accept up to 250 results per page and page with a cursor in `_links.next`.
V2_MAX_PAGE_SIZE = 250
# Users, groups and content analytics exist only on the older v1 API, which pages with
# `start`/`limit` and caps a page at 200.
V1_MAX_PAGE_SIZE = 200

_PAGE_VERSIONS_FANOUT = DependentEndpointConfig(
    parent_name="pages",
    resolve_param="id",
    resolve_field="id",
    include_from_parent=["id"],
    parent_field_renames={"id": "pageId"},
)

_BLOGPOST_VERSIONS_FANOUT = DependentEndpointConfig(
    parent_name="blogposts",
    resolve_param="id",
    resolve_field="id",
    include_from_parent=["id"],
    parent_field_renames={"id": "blogpostId"},
)

_GROUP_MEMBERS_FANOUT = DependentEndpointConfig(
    parent_name="groups",
    resolve_param="groupId",
    resolve_field="id",
    include_from_parent=["id"],
    parent_field_renames={"id": "groupId"},
)

_PAGE_ANALYTICS_FANOUT = DependentEndpointConfig(
    parent_name="pages",
    resolve_param="contentId",
    resolve_field="id",
    include_from_parent=["id"],
    parent_field_renames={"id": "pageId"},
    # The analytics endpoints take no page-size param, so the parent's own limit is set here
    # rather than through the shared `page_size_param`, which applies to both sides.
    parent_params={"limit": V2_MAX_PAGE_SIZE},
    # A page trashed between the listing and this fetch answers 404; skip that page rather
    # than failing the whole sync.
    child_response_actions=[{"status_code": 404, "action": "ignore"}],
)


@dataclass
class ConfluenceEndpointConfig:
    name: str
    path: str  # Site-relative path, e.g. "/wiki/api/v2/pages" (v2) or "/wiki/rest/api/group" (v1)
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Stable, immutable datetime field used for partitioning. Confluence's v2
    # objects expose `createdAt` at the top level (never use a mutable field
    # like the nested version timestamp). `None` for resources that don't carry
    # a top-level creation timestamp (labels, comments, users, groups).
    partition_key: Optional[str] = None
    page_size: int = V2_MAX_PAGE_SIZE
    params: dict[str, Any] = field(default_factory=dict)
    # Collection endpoints on both APIs wrap their rows in `results`.
    data_selector: Optional[str] = "results"
    # Which Confluence API the path belongs to. It selects the paginator: v2 follows the cursor
    # in `_links.next`, v1 walks `start`/`limit`.
    api: Literal["v1", "v2"] = "v2"
    # The endpoint answers with one object rather than a collection, so there is nothing to
    # paginate and the whole body is the row.
    single_object: bool = False
    fanout: Optional[DependentEndpointConfig] = None
    # Required by the shared fan-out helper's endpoint protocol. No Confluence endpoint has a
    # server-side timestamp filter, so both stay empty — see the note below.
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: Optional[str] = None


# Confluence Cloud endpoints, keyed by the schema name of the table they produce.
#
# We intentionally ship every endpoint as full-refresh: neither API exposes a server-side
# timestamp filter (there is no `since` / `modified_after` / `created-date>=` query param), so an
# "incremental" sync would still page through the entire collection every run. Per the
# implementing-warehouse-sources guidance we only advertise incremental when a genuine
# server-side filter exists, so all endpoints here are full refresh.
CONFLUENCE_ENDPOINTS: dict[str, ConfluenceEndpointConfig] = {
    "spaces": ConfluenceEndpointConfig(
        name="spaces",
        path="/wiki/api/v2/spaces",
        partition_key="createdAt",
    ),
    "pages": ConfluenceEndpointConfig(
        name="pages",
        path="/wiki/api/v2/pages",
        partition_key="createdAt",
    ),
    "blogposts": ConfluenceEndpointConfig(
        name="blogposts",
        path="/wiki/api/v2/blogposts",
        partition_key="createdAt",
    ),
    "attachments": ConfluenceEndpointConfig(
        name="attachments",
        path="/wiki/api/v2/attachments",
        partition_key="createdAt",
    ),
    "tasks": ConfluenceEndpointConfig(
        name="tasks",
        path="/wiki/api/v2/tasks",
        partition_key="createdAt",
    ),
    # Labels and comments don't carry a top-level creation timestamp, so they
    # have no stable partition key.
    "labels": ConfluenceEndpointConfig(
        name="labels",
        path="/wiki/api/v2/labels",
    ),
    "footer_comments": ConfluenceEndpointConfig(
        name="footer_comments",
        path="/wiki/api/v2/footer-comments",
    ),
    "inline_comments": ConfluenceEndpointConfig(
        name="inline_comments",
        path="/wiki/api/v2/inline-comments",
    ),
    "page_versions": ConfluenceEndpointConfig(
        name="page_versions",
        path="/wiki/api/v2/pages/{id}/versions",
        # A version number only counts within its page, so the page id is part of the key.
        primary_keys=["pageId", "number"],
        partition_key="createdAt",
        fanout=_PAGE_VERSIONS_FANOUT,
    ),
    "blogpost_versions": ConfluenceEndpointConfig(
        name="blogpost_versions",
        path="/wiki/api/v2/blogposts/{id}/versions",
        primary_keys=["blogpostId", "number"],
        partition_key="createdAt",
        fanout=_BLOGPOST_VERSIONS_FANOUT,
    ),
    # `cql=type=user` is the documented way to list the directory; it returns up to 10,000
    # users. Each search result wraps the user it matched, so the rows are read out of
    # `results[*].user` to give a table of users rather than of search hits.
    "users": ConfluenceEndpointConfig(
        name="users",
        path="/wiki/rest/api/search/user",
        primary_keys=["accountId"],
        page_size=V1_MAX_PAGE_SIZE,
        params={"cql": "type=user"},
        data_selector="results[*].user",
        api="v1",
    ),
    "groups": ConfluenceEndpointConfig(
        name="groups",
        path="/wiki/rest/api/group",
        page_size=V1_MAX_PAGE_SIZE,
        api="v1",
    ),
    "group_members": ConfluenceEndpointConfig(
        name="group_members",
        path="/wiki/rest/api/group/{groupId}/membersByGroupId",
        # A user appears once per group they belong to, so neither column is unique alone.
        primary_keys=["groupId", "accountId"],
        page_size=V1_MAX_PAGE_SIZE,
        api="v1",
        fanout=_GROUP_MEMBERS_FANOUT,
    ),
    "page_views": ConfluenceEndpointConfig(
        name="page_views",
        path="/wiki/rest/api/analytics/content/{contentId}/views",
        primary_keys=["pageId"],
        data_selector=None,
        api="v1",
        single_object=True,
        fanout=_PAGE_ANALYTICS_FANOUT,
    ),
    "page_viewers": ConfluenceEndpointConfig(
        name="page_viewers",
        path="/wiki/rest/api/analytics/content/{contentId}/viewers",
        primary_keys=["pageId"],
        data_selector=None,
        api="v1",
        single_object=True,
        fanout=_PAGE_ANALYTICS_FANOUT,
    ),
}

ENDPOINTS = tuple(CONFLUENCE_ENDPOINTS.keys())

# No endpoint supports server-side incremental filtering (see note above), so no
# endpoint advertises incremental fields.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {name: [] for name in CONFLUENCE_ENDPOINTS}
