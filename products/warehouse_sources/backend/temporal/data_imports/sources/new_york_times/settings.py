from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class NewYorkTimesEndpointConfig:
    name: str
    path: str
    # Key in the JSON response holding the row list. Snapshot endpoints (Most Popular, Top Stories)
    # nest their rows under "results"; Article Search nests them under "response" -> "docs".
    data_selector: str
    primary_keys: list[str] = field(default_factory=lambda: ["uri"])
    partition_key: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Only True where NYT exposes a genuine server-side timestamp filter (Article Search's begin_date).
    supports_incremental: bool = False
    # True for Article Search, which pages via a `page` query param (10 results/page, capped at 100 pages).
    # Snapshot endpoints return a single fixed-size list with no pagination.
    paginated: bool = False
    # First-sync / full-refresh window for the paginated Article Search endpoint. NYT hard-caps Article
    # Search at 1000 results per query, so an unbounded pull is impossible — window it to a recent range
    # and let successive incremental syncs walk forward.
    default_lookback_days: Optional[int] = None
    should_sync_default: bool = True


_PUB_DATE_INCREMENTAL: list[IncrementalField] = [
    {
        "label": "pub_date",
        "type": IncrementalFieldType.DateTime,
        "field": "pub_date",
        "field_type": IncrementalFieldType.DateTime,
    },
]


NEW_YORK_TIMES_ENDPOINTS: dict[str, NewYorkTimesEndpointConfig] = {
    # Article Search — the flagship NYT API. Server-side date windowing via begin_date (YYYYMMDD) plus
    # sort=oldest gives a genuine ascending incremental pull, deduped on the stable `_id`.
    "article_search": NewYorkTimesEndpointConfig(
        name="article_search",
        path="/svc/search/v2/articlesearch.json",
        data_selector="docs",
        primary_keys=["_id"],
        partition_key="pub_date",
        incremental_fields=_PUB_DATE_INCREMENTAL,
        supports_incremental=True,
        paginated=True,
        default_lookback_days=30,
    ),
    # Most Popular — point-in-time snapshots (most viewed/emailed/shared over the last 7 days). No
    # server-side updated-since cursor, so these are full refresh; merge dedupes on `uri`.
    "most_popular_viewed": NewYorkTimesEndpointConfig(
        name="most_popular_viewed",
        path="/svc/mostpopular/v2/viewed/7.json",
        data_selector="results",
        primary_keys=["uri"],
        partition_key="published_date",
    ),
    "most_popular_emailed": NewYorkTimesEndpointConfig(
        name="most_popular_emailed",
        path="/svc/mostpopular/v2/emailed/7.json",
        data_selector="results",
        primary_keys=["uri"],
        partition_key="published_date",
    ),
    "most_popular_shared": NewYorkTimesEndpointConfig(
        name="most_popular_shared",
        path="/svc/mostpopular/v2/shared/7.json",
        data_selector="results",
        primary_keys=["uri"],
        partition_key="published_date",
    ),
    # Top Stories — a snapshot of the current stories on the home section. Full refresh; `created_date`
    # is stable so it's the partition key (never `updated_date`).
    "top_stories": NewYorkTimesEndpointConfig(
        name="top_stories",
        path="/svc/topstories/v2/home.json",
        data_selector="results",
        primary_keys=["uri"],
        partition_key="created_date",
    ),
}

ENDPOINTS = tuple(NEW_YORK_TIMES_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in NEW_YORK_TIMES_ENDPOINTS.items()
}
