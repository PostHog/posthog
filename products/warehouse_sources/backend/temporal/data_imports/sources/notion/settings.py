from dataclasses import dataclass
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField

# Notion search and query endpoints cap page_size at 100.
NOTION_PAGE_SIZE = 100

StreamType = Literal["search", "users", "blocks", "comments"]


@dataclass
class NotionEndpointConfig:
    name: str
    stream_type: StreamType
    # Field to partition by. Must be stable (immutable) - Notion's created_time fits;
    # last_edited_time changes on every edit so it is unsuitable.
    partition_key: Optional[str] = None
    # For "search" streams: the Notion object type to filter to ("page" or "data_source").
    # Under API version 2025-09-03 the schema-bearing "database" tables are returned as
    # "data_source" objects, so the databases stream filters on "data_source".
    object_filter: Optional[str] = None


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
}

ENDPOINTS = tuple(NOTION_ENDPOINTS.keys())

# Notion's search endpoint only sorts (not filters) by last_edited_time, so there is no
# server-side timestamp filter we can use for true incremental sync - all streams are full refresh.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {name: [] for name in NOTION_ENDPOINTS}
