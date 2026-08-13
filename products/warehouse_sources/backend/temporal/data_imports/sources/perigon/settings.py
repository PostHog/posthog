from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class PerigonEndpointConfig:
    name: str
    path: str
    # JSON key holding the row list in the response wrapper (`articles`, `results`, or `data`).
    data_selector: str
    primary_keys: list[str]
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Query param for the server-side lower-bound timestamp filter, when the endpoint has one.
    incremental_param: Optional[str] = None
    # `sortBy` value used on incremental runs so pagination walks the cursor field.
    incremental_sort_by: Optional[str] = None
    # `sortBy` value used on full-refresh runs for stable page boundaries; None = API default.
    full_refresh_sort_by: Optional[str] = None
    # Stable creation-style field used to partition the Delta table. Never an `updatedAt`
    # style field — those rewrite partitions on every sync.
    partition_key: Optional[str] = None
    sort_mode: Literal["asc", "desc"] = "asc"


_ARTICLE_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "pubDate",
        "type": IncrementalFieldType.DateTime,
        "field": "pubDate",
        "field_type": IncrementalFieldType.DateTime,
    },
]

_STORY_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "updatedAt",
        "type": IncrementalFieldType.DateTime,
        "field": "updatedAt",
        "field_type": IncrementalFieldType.DateTime,
    },
]


PERIGON_ENDPOINTS: dict[str, PerigonEndpointConfig] = {
    # News articles. `from` filters on publication date and `sortBy=reverseDate` is the
    # documented ascending-publication-date sort, so the incremental watermark advances
    # safely batch by batch.
    "articles": PerigonEndpointConfig(
        name="articles",
        path="/v1/articles/all",
        data_selector="articles",
        primary_keys=["articleId"],
        incremental_fields=_ARTICLE_INCREMENTAL_FIELDS,
        incremental_param="from",
        incremental_sort_by="reverseDate",
        # addDate ascending = insertion order, so rows added mid-sync append after the
        # current page instead of shifting earlier page boundaries.
        full_refresh_sort_by="reverseAddDate",
        partition_key="pubDate",
        sort_mode="asc",
    ),
    # Story clusters. `updatedFrom` filters on the cluster's last-update time, which also
    # catches clusters that gained new articles. Perigon documents no ascending sort for
    # stories, so the sort is the cursor field newest-first and sort_mode is "desc" (the
    # watermark is only finalized at the end of the sync).
    "stories": PerigonEndpointConfig(
        name="stories",
        path="/v1/stories/all",
        data_selector="results",
        primary_keys=["id"],
        incremental_fields=_STORY_INCREMENTAL_FIELDS,
        incremental_param="updatedFrom",
        incremental_sort_by="updatedAt",
        full_refresh_sort_by="createdAt",
        partition_key="createdAt",
        sort_mode="desc",
    ),
    # Reference datasets below have no verified server-side timestamp filter, so they sync
    # as full refresh only.
    "journalists": PerigonEndpointConfig(
        name="journalists",
        path="/v1/journalists/all",
        data_selector="results",
        primary_keys=["id"],
    ),
    "sources": PerigonEndpointConfig(
        name="sources",
        path="/v1/sources/all",
        data_selector="results",
        primary_keys=["id"],
    ),
    "people": PerigonEndpointConfig(
        name="people",
        path="/v1/people/all",
        data_selector="results",
        primary_keys=["wikidataId"],
    ),
    "companies": PerigonEndpointConfig(
        name="companies",
        path="/v1/companies/all",
        data_selector="results",
        primary_keys=["id"],
    ),
    "topics": PerigonEndpointConfig(
        name="topics",
        path="/v1/topics/all",
        data_selector="data",
        primary_keys=["id"],
    ),
}

ENDPOINTS = tuple(PERIGON_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in PERIGON_ENDPOINTS.items()
}
