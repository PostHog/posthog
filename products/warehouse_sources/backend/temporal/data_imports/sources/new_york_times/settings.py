from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass(frozen=False)
class NewYorkTimesEndpointConfig:
    name: str
    path: str
    # Dotted path in the JSON response to the row list. Snapshot endpoints (Most Popular, Top Stories)
    # nest their rows under "results"; Article Search and Archive nest them under "response" -> "docs".
    data_selector: str
    primary_keys: list[str] = field(default_factory=lambda: ["uri"])
    partition_key: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Only True where NYT exposes a genuine server-side timestamp filter (Article Search's begin_date).
    supports_incremental: bool = False
    # False where every incremental sync re-reads the watermark's whole month or edition. Append never
    # dedupes on the primary key, so those re-read rows would pile up as duplicates.
    supports_append: bool = True
    # True for Article Search, which pages via a `page` query param (10 results/page, capped at 100 pages).
    # Snapshot endpoints return a single fixed-size list with no pagination.
    paginated: bool = False
    # First-sync / full-refresh window for the paginated Article Search endpoint. NYT hard-caps Article
    # Search at 1000 results per query, so an unbounded pull is impossible — window it to a recent range
    # and let successive incremental syncs walk forward.
    default_lookback_days: Optional[int] = None
    should_sync_default: bool = True
    sort_mode: Optional[Literal["asc", "desc"]] = None


_PUB_DATE_INCREMENTAL: list[IncrementalField] = [
    {
        "label": "pub_date",
        "type": IncrementalFieldType.DateTime,
        "field": "pub_date",
        "field_type": IncrementalFieldType.DateTime,
    },
]

_PUBLISHED_DATETIME_INCREMENTAL: list[IncrementalField] = [
    {
        "label": "published_date",
        "type": IncrementalFieldType.DateTime,
        "field": "published_date",
        "field_type": IncrementalFieldType.DateTime,
    },
]

_PUBLISHED_DATE_INCREMENTAL: list[IncrementalField] = [
    {
        "label": "published_date",
        "type": IncrementalFieldType.Date,
        "field": "published_date",
        "field_type": IncrementalFieldType.Date,
    },
]


NEW_YORK_TIMES_ENDPOINTS: dict[str, NewYorkTimesEndpointConfig] = {
    # Article Search — the flagship NYT API. Server-side date windowing via begin_date (YYYYMMDD) plus
    # sort=oldest gives a genuine ascending incremental pull, deduped on the stable `_id`.
    "article_search": NewYorkTimesEndpointConfig(
        name="article_search",
        path="/svc/search/v2/articlesearch.json",
        data_selector="response.docs",
        primary_keys=["_id"],
        partition_key="pub_date",
        incremental_fields=_PUB_DATE_INCREMENTAL,
        supports_incremental=True,
        paginated=True,
        default_lookback_days=30,
        sort_mode="asc",
    ),
    # Archive — every article for one calendar month per request. The month in the path is the server-side
    # filter, so incremental syncs restart at the watermark's month. Responses can reach ~20 MB, so the
    # first sync and full refreshes cover a recent window instead of walking back to 1851. The order inside
    # a month is undocumented, so no sort_mode.
    "archive": NewYorkTimesEndpointConfig(
        name="archive",
        path="/svc/archive/v1/{year}/{month}.json",
        data_selector="response.docs",
        primary_keys=["_id"],
        partition_key="pub_date",
        incremental_fields=_PUB_DATE_INCREMENTAL,
        supports_incremental=True,
        supports_append=False,
        default_lookback_days=365,
        should_sync_default=False,
    ),
    # Times Newswire — newest-first feed of published items. The `{time-period}` path segment (hours back)
    # is the server-side filter; `url` is the item identity the API's own single-item lookup keys on.
    "times_wire": NewYorkTimesEndpointConfig(
        name="times_wire",
        path="/svc/news/v3/content/all/all/{time_period}.json",
        data_selector="results",
        primary_keys=["url"],
        partition_key="created_date",
        incremental_fields=_PUBLISHED_DATETIME_INCREMENTAL,
        supports_incremental=True,
        default_lookback_days=3,
    ),
    # Books best-seller lists — one row per book per list edition. The list catalog comes from
    # /lists/names.json; each edition is fetched by its published date, which is the server-side filter
    # incremental syncs walk back to the watermark.
    "books_best_sellers": NewYorkTimesEndpointConfig(
        name="books_best_sellers",
        path="/svc/books/v3/lists/{date}/{list}.json",
        data_selector="results.books",
        primary_keys=["list_name_encoded", "published_date", "rank"],
        partition_key="published_date",
        incremental_fields=_PUBLISHED_DATE_INCREMENTAL,
        supports_incremental=True,
        supports_append=False,
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
