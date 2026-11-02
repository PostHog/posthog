from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class NewsApiEndpointConfig:
    name: str
    path: str
    # Key in the JSON response body that holds the row list ("articles" or "sources").
    data_key: str
    primary_keys: list[str]
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable datetime field to partition by. `publishedAt` never changes once an article is
    # published, so it is safe for partitioning; `sources` has no timestamp so it is unpartitioned.
    partition_key: Optional[str] = None
    # True only where the API exposes a genuine server-side timestamp filter (`from`/`to` on
    # /v2/everything). Full-refresh endpoints leave this False.
    supports_incremental: bool = False
    # Whether the endpoint paginates via page/pageSize. /v2/top-headlines/sources returns the full
    # publisher list in one response.
    paginated: bool = True
    should_sync_default: bool = True


_PUBLISHED_AT_INCREMENTAL: list[IncrementalField] = [
    {
        "label": "publishedAt",
        "type": IncrementalFieldType.DateTime,
        "field": "publishedAt",
        "field_type": IncrementalFieldType.DateTime,
    },
]


NEWS_API_ENDPOINTS: dict[str, NewsApiEndpointConfig] = {
    # Full article search. `from`/`to` filter server-side on publishedAt, so this is the only
    # endpoint that supports incremental sync. NewsAPI caps reachable results per query window at
    # 100 (deep history requires narrowing the date window, not deep pagination), so incremental
    # syncs advance the `from` cursor on publishedAt each run.
    "everything": NewsApiEndpointConfig(
        name="everything",
        path="/v2/everything",
        data_key="articles",
        primary_keys=["url"],
        partition_key="publishedAt",
        supports_incremental=True,
        incremental_fields=_PUBLISHED_AT_INCREMENTAL,
    ),
    # Curated breaking-news headlines. No date filter is available, so full refresh only.
    "top_headlines": NewsApiEndpointConfig(
        name="top_headlines",
        path="/v2/top-headlines",
        data_key="articles",
        primary_keys=["url"],
        partition_key="publishedAt",
        supports_incremental=False,
    ),
    # The publisher catalog behind top-headlines. Small, static-ish list returned in one response.
    "sources": NewsApiEndpointConfig(
        name="sources",
        path="/v2/top-headlines/sources",
        data_key="sources",
        primary_keys=["id"],
        supports_incremental=False,
        paginated=False,
    ),
}

ENDPOINTS = tuple(NEWS_API_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in NEWS_API_ENDPOINTS.items()
}
