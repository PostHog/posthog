import dataclasses
from typing import Any, Literal

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# StockData.org windows the price feeds server-side with `date_from` and the news feed and news stats
# time series with `published_after`, so those endpoints sync incrementally. The other endpoints
# document no date filter, so they are full refresh only.
_DATE_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "date",
        "type": IncrementalFieldType.DateTime,
        "field": "date",
        "field_type": IncrementalFieldType.DateTime,
    },
]
_PUBLISHED_AT_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "published_at",
        "type": IncrementalFieldType.DateTime,
        "field": "published_at",
        "field_type": IncrementalFieldType.DateTime,
    },
]


# StockData.org caps any paginated news result set at 20,000 records (limit × page); requesting
# beyond it can't return more rows, so pagination stops there and logs the truncation.
MAX_NEWS_RESULTS = 20_000


@dataclasses.dataclass(frozen=False)
class StockDataEndpointConfig:
    name: str
    path: str
    primary_keys: list[str]
    # Price endpoints require a `symbols` query param; news accepts it as an optional filter. Entity
    # search also requires it, because an unfiltered search pages through every listed entity.
    requires_symbols: bool = False
    accepts_symbols: bool = False
    # Empty list = full refresh only (no server-side date filter).
    incremental_fields: list[IncrementalField] = dataclasses.field(default_factory=list)
    # The server-side filter param the incremental watermark maps onto.
    incremental_param: Literal["date_from", "published_after"] | None = None
    # Stable datetime column for datetime partitioning (`date` / `published_at` never change).
    partition_key: str | None = None
    # Static request params (interval, sort). Kept declarative so transport branches stay minimal.
    params: dict[str, Any] = dataclasses.field(default_factory=dict)
    # EOD/intraday rows nest OHLCV under item["data"]; the transport flattens it into the row root.
    flatten_data: bool = False
    # News, entity search, and news sources paginate (page param, `meta.found`); the rest return one page.
    paginated: bool = False
    # Documented result-set cap for paginated endpoints; None when the vendor documents no cap.
    max_results: int | None = None
    # News stats time series rows arrive as `{date, data: [{key, ...}]}` buckets; the transport
    # explodes each bucket into one row per key.
    explode_buckets: bool = False
    # The order rows actually arrive in. News is newest-first and can't be flipped (sort_order is
    # only valid with the entity-score sorts); price feeds are requested with sort=asc and the news
    # stats time series with date_order=asc.
    sort_mode: Literal["asc", "desc"] = "asc"
    description: str | None = None


STOCKDATA_ENDPOINTS: dict[str, StockDataEndpointConfig] = {
    "news": StockDataEndpointConfig(
        name="news",
        path="/news/all",
        primary_keys=["uuid"],
        accepts_symbols=True,
        incremental_fields=_PUBLISHED_AT_INCREMENTAL_FIELDS,
        incremental_param="published_after",
        partition_key="published_at",
        params={"sort": "published_on"},
        paginated=True,
        max_results=MAX_NEWS_RESULTS,
        sort_mode="desc",
        description="Financial and market news articles with per-entity sentiment scores. Optionally filtered to the configured symbols. Incremental on published_at.",
    ),
    "quote": StockDataEndpointConfig(
        name="quote",
        path="/data/quote",
        primary_keys=["ticker"],
        requires_symbols=True,
        description="Latest price and trading-day snapshot per symbol (one row per symbol). Requires symbols. Full refresh.",
    ),
    "eod": StockDataEndpointConfig(
        name="eod",
        path="/data/eod",
        primary_keys=["ticker", "date"],
        requires_symbols=True,
        incremental_fields=_DATE_INCREMENTAL_FIELDS,
        incremental_param="date_from",
        partition_key="date",
        params={"sort": "asc", "interval": "day"},
        flatten_data=True,
        description="End-of-day (daily OHLCV) stock prices per symbol. Requires symbols. Incremental on date.",
    ),
    "intraday": StockDataEndpointConfig(
        name="intraday",
        path="/data/intraday",
        primary_keys=["ticker", "date"],
        requires_symbols=True,
        incremental_fields=_DATE_INCREMENTAL_FIELDS,
        incremental_param="date_from",
        partition_key="date",
        # The hour interval allows a 180-day request window (minute allows only 7 days), which
        # suits scheduled warehouse syncs far better.
        params={"sort": "asc", "interval": "hour"},
        flatten_data=True,
        description="Intraday (hourly OHLCV) stock prices per symbol. Requires symbols. Incremental on date.",
    ),
    "dividends": StockDataEndpointConfig(
        name="dividends",
        path="/data/dividends",
        primary_keys=["ticker", "date"],
        requires_symbols=True,
        partition_key="date",
        description="Historical dividend payouts per symbol. Requires symbols and a Standard or higher StockData.org plan. Full refresh.",
    ),
    "splits": StockDataEndpointConfig(
        name="splits",
        path="/data/splits",
        primary_keys=["ticker", "date"],
        requires_symbols=True,
        partition_key="date",
        description="Historical stock splits per symbol. Requires symbols and a Standard or higher StockData.org plan. Full refresh.",
    ),
    "entity_search": StockDataEndpointConfig(
        name="entity_search",
        path="/entity/search",
        primary_keys=["symbol"],
        requires_symbols=True,
        paginated=True,
        description="Entity metadata (name, type, industry, exchange, country) for the configured symbols. Requires symbols. Full refresh.",
    ),
    "news_sources": StockDataEndpointConfig(
        name="news_sources",
        path="/news/sources",
        primary_keys=["source_id"],
        paginated=True,
        description="News source feeds (source ID, domain, language) that the news table draws from. The API returns 50 sources per request, so a full sync takes about one request per 50 sources. Full refresh.",
    ),
    "news_stats_intraday": StockDataEndpointConfig(
        name="news_stats_intraday",
        path="/news/stats/intraday",
        primary_keys=["date", "key"],
        accepts_symbols=True,
        incremental_fields=_DATE_INCREMENTAL_FIELDS,
        incremental_param="published_after",
        partition_key="date",
        params={"interval": "day", "group_by": "symbol", "date_order": "asc"},
        explode_buckets=True,
        description="Daily news volume and average sentiment per symbol. Optionally filtered to the configured symbols. Requires a Standard or higher StockData.org plan. Incremental on date.",
    ),
    "news_stats_aggregation": StockDataEndpointConfig(
        name="news_stats_aggregation",
        path="/news/stats/aggregation",
        primary_keys=["key"],
        accepts_symbols=True,
        params={"group_by": "symbol"},
        description="News volume and average sentiment per symbol, aggregated over one time frame. Optionally filtered to the configured symbols. Requires a Standard or higher StockData.org plan. Full refresh.",
    ),
}

ENDPOINTS = tuple(STOCKDATA_ENDPOINTS.keys())
