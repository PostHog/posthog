from dataclasses import dataclass
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Notion search and query endpoints cap page_size at 100.
NOTION_PAGE_SIZE = 100

StreamType = Literal["search", "users", "blocks", "comments", "database_rows"]


@dataclass
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
    # Whether this stream supports incremental sync. Only `database_rows` can: its query endpoint
    # accepts a `last_edited_time` server-side filter, which the search endpoint the other streams
    # use does not.
    supports_incremental: bool = False


# The one stream that can sync incrementally. The data-source query endpoint filters server-side on
# `last_edited_time`, so a row that changed since the last run is re-read and merged on `id`.
_LAST_EDITED_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "last_edited_time",
        "type": IncrementalFieldType.DateTime,
        "field": "last_edited_time",
        "field_type": IncrementalFieldType.DateTime,
    },
]


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
    "database_rows": NotionEndpointConfig(
        name="database_rows",
        stream_type="database_rows",
        partition_key="created_time",
        supports_incremental=True,
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

# Notion's search endpoint only sorts (not filters) by last_edited_time, so the search-backed streams
# (pages, databases, users, blocks, comments) are full refresh. Only `database_rows` reads through the
# data-source query endpoint, which does accept a `last_edited_time` filter, so it syncs incrementally.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: list(_LAST_EDITED_INCREMENTAL_FIELDS) if config.supports_incremental else []
    for name, config in NOTION_ENDPOINTS.items()
}
