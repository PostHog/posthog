from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# GNews returns at most 100 articles per request and caps any single query at 1000 articles
# regardless of pagination (https://gnews.io/docs/v4). Page size is the paid-plan maximum;
# free plans silently return fewer, which the paginator handles as a short final page.
PAGE_SIZE = 100
MAX_ARTICLES_PER_QUERY = 1000

# GNews sorts by publish time newest-first when `sortby=publishedAt`; there is no ascending
# option, so every list endpoint emits rows in descending order (see gnews.py).
_PUBLISHED_AT_INCREMENTAL: list[IncrementalField] = [
    {
        "label": "publishedAt",
        "type": IncrementalFieldType.DateTime,
        "field": "publishedAt",
        "field_type": IncrementalFieldType.DateTime,
    },
]


@dataclass
class GNewsEndpointConfig:
    name: str
    path: str
    incremental_fields: list[IncrementalField]
    # Stable publish timestamp — an article's publishedAt never changes, so it's safe for both
    # the incremental cursor and partitioning.
    partition_key: Optional[str] = "publishedAt"
    sort_mode: Literal["asc", "desc"] = "desc"
    # GNews articles carry no stable id, but a URL uniquely identifies an article across the
    # whole table, so it's the natural primary key for dedup on merge.
    primary_keys: list[str] = field(default_factory=lambda: ["url"])
    should_sync_default: bool = True


GNEWS_ENDPOINTS: dict[str, GNewsEndpointConfig] = {
    # Keyword search across worldwide sources, driven by the configured `query`.
    "articles": GNewsEndpointConfig(
        name="articles",
        path="/search",
        incremental_fields=_PUBLISHED_AT_INCREMENTAL,
    ),
    # Breaking news for the configured `category` (defaults to general).
    "top_headlines": GNewsEndpointConfig(
        name="top_headlines",
        path="/top-headlines",
        incremental_fields=_PUBLISHED_AT_INCREMENTAL,
    ),
}

ENDPOINTS = tuple(GNEWS_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in GNEWS_ENDPOINTS.items()
}
