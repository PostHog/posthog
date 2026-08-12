from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class NewsDataEndpointConfig:
    name: str
    path: str
    incremental_fields: list[IncrementalField]
    primary_keys: list[str] = field(default_factory=lambda: ["article_id"])
    # Stable datetime field used both for partitioning and (where the endpoint supports a
    # server-side date filter) as the incremental cursor. Publish date never changes, so it's a
    # safe partition key. None disables partitioning (e.g. the sources catalog has no timestamp).
    partition_key: Optional[str] = None
    # True only for endpoints that accept the `from_date`/`to_date` query params (verified against
    # the live API: rejected on /latest, accepted on /archive and /crypto). Drives whether the
    # endpoint can sync incrementally via a genuine server-side timestamp filter.
    supports_date_filter: bool = False
    # /sources returns the full catalog in a single response and rejects the `page` param, so
    # cursor pagination is skipped for it.
    supports_pagination: bool = True
    # First incremental sync floor: instead of crawling the entire (up to 7-year) archive, the very
    # first sync only pulls the trailing N days. Later syncs advance from the stored watermark.
    default_lookback_days: Optional[int] = None
    # NewsData returns results newest-first and exposes no sort control, so date-filtered endpoints
    # sync in descending order (the pipeline commits the incremental watermark only once the run
    # completes — safe for a newest-first API).
    sort_mode: Literal["asc", "desc"] = "asc"
    should_sync_default: bool = True


def _pub_date_incremental_fields() -> list[IncrementalField]:
    return [
        {
            "label": "pubDate",
            "type": IncrementalFieldType.DateTime,
            "field": "pubDate",
            "field_type": IncrementalFieldType.DateTime,
        },
    ]


NEWSDATA_ENDPOINTS: dict[str, NewsDataEndpointConfig] = {
    # Real-time news from the last 48 hours. No server-side date filter, so full refresh only.
    "latest": NewsDataEndpointConfig(
        name="latest",
        path="/latest",
        partition_key="pubDate",
        incremental_fields=[],
    ),
    # Historical news (up to 7 years). `from_date`/`to_date` filter server-side, enabling incremental.
    "archive": NewsDataEndpointConfig(
        name="archive",
        path="/archive",
        partition_key="pubDate",
        supports_date_filter=True,
        default_lookback_days=30,
        sort_mode="desc",
        incremental_fields=_pub_date_incremental_fields(),
    ),
    # Crypto-specific news. Same date-filter/pagination shape as archive.
    "crypto": NewsDataEndpointConfig(
        name="crypto",
        path="/crypto",
        partition_key="pubDate",
        supports_date_filter=True,
        default_lookback_days=30,
        sort_mode="desc",
        incremental_fields=_pub_date_incremental_fields(),
    ),
    # Catalog of available news sources. Single-response, no pagination or date filter.
    "sources": NewsDataEndpointConfig(
        name="sources",
        path="/sources",
        primary_keys=["id"],
        supports_pagination=False,
        incremental_fields=[],
    ),
}

ENDPOINTS = tuple(NEWSDATA_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in NEWSDATA_ENDPOINTS.items()
}
