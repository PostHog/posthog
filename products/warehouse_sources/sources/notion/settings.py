from dataclasses import dataclass
from typing import Literal, Optional

from products.warehouse_sources.sources.sdk import IncrementalField

# Notion search and query endpoints cap page_size at 100.
NOTION_PAGE_SIZE = 100

StreamType = Literal[
    "search",
    "users",
    "blocks",
    "comments",
    "permission_groups",
    "permission_group_members",
    "user_credit_usage",
    "agent_credit_usage",
]


@dataclass(frozen=False)
class NotionEndpointConfig:
    name: str
    stream_type: StreamType
    # Field to partition by. Must be stable (immutable) - Notion's created_time fits;
    # last_edited_time changes on every edit so it is unsuitable.
    partition_key: Optional[str] = None
    # For "search" streams: the Notion object type to filter to ("page" or "data_source").
    # From API version 2025-09-03 onward the schema-bearing "database" tables are returned as
    # "data_source" objects, so the databases stream filters on "data_source".
    object_filter: Optional[str] = None
    primary_keys: tuple[str, ...] = ("id",)
    # Admin API endpoints only: the organization bot token scope the endpoint needs, and the workspace
    # list path that the stream pages through (the parent list for a fan-out stream).
    admin_scope: Optional[str] = None
    admin_path: Optional[str] = None


NOTION_ENDPOINTS: dict[str, NotionEndpointConfig] = {
    "pages": NotionEndpointConfig(
        name="pages",
        stream_type="search",
        object_filter="page",
        partition_key="created_time",
    ),
    "databases": NotionEndpointConfig(
        name="databases",
        stream_type="search",
        object_filter="data_source",
        partition_key="created_time",
    ),
    "users": NotionEndpointConfig(
        name="users",
        stream_type="users",
    ),
    "blocks": NotionEndpointConfig(
        name="blocks",
        stream_type="blocks",
        partition_key="created_time",
    ),
    "comments": NotionEndpointConfig(
        name="comments",
        stream_type="comments",
        partition_key="created_time",
    ),
    # Admin API endpoints: they need an organization bot token, and the organization must be on the Enterprise plan.
    "permission_groups": NotionEndpointConfig(
        name="permission_groups",
        stream_type="permission_groups",
        admin_scope="permission-group:read",
        admin_path="/v1/spaces/{workspace_id}/groups",
    ),
    "permission_group_members": NotionEndpointConfig(
        name="permission_group_members",
        stream_type="permission_group_members",
        # Membership rows have no id of their own, and a user can be in many groups.
        primary_keys=("group_id", "user_id"),
        admin_scope="permission-group:read",
        admin_path="/v1/spaces/{workspace_id}/groups",
    ),
    "user_credit_usage": NotionEndpointConfig(
        name="user_credit_usage",
        stream_type="user_credit_usage",
        admin_scope="user:read",
        admin_path="/v1/spaces/{workspace_id}/users/credit_usage",
    ),
    "agent_credit_usage": NotionEndpointConfig(
        name="agent_credit_usage",
        stream_type="agent_credit_usage",
        admin_scope="workflows:read",
        admin_path="/v1/spaces/{workspace_id}/agents/credit_usage",
    ),
}

ENDPOINTS = tuple(NOTION_ENDPOINTS.keys())

# Notion's search endpoint only sorts (not filters) by last_edited_time, so there is no
# server-side timestamp filter we can use for true incremental sync - all streams are full refresh.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {name: [] for name in NOTION_ENDPOINTS}
