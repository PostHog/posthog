from dataclasses import dataclass, field
from typing import Literal, Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# CoinMarketCap caps `limit` at 5000 records per page across its list endpoints.
# A larger page size means fewer HTTP calls (kinder to the per-minute rate limit);
# the monthly credit cost is per data point, so it's unaffected by page size.
PAGE_SIZE = 5000

# Coins per `id=` request on the endpoints that take an explicit id list. CoinMarketCap bills
# metadata at 1 credit per 250 records returned, so batching on that boundary is the cheapest
# whole multiple. The historical endpoints bill per data point instead, where a smaller batch
# only keeps each response (and the memory it lands in) manageable.
METADATA_BATCH_SIZE = 250
HISTORICAL_BATCH_SIZE = 20

# Per-coin history is billed per data point, so the coin universe has to be bounded: asking for
# a year of daily candles across every listed coin would spend a month of credits in one sync.
# The highest-ranked coins by market cap are what these tables get used for.
HISTORICAL_COIN_LIMIT = 100

# Same bound for the per-exchange history, taken from the top of the volume ranking. There are far
# fewer exchanges than coins, so this covers most of the venues anyone reports on.
HISTORICAL_EXCHANGE_LIMIT = 100

# How deep the daily ranked snapshot goes. listings/historical bills per 100 cryptocurrencies per
# day requested, so the rank depth and the day window together set what a sync costs.
LISTINGS_HISTORICAL_RANK_LIMIT = 100

# How far back a historical request reaches when there is no watermark to start from. One year
# of daily points is the longest window every paid plan tier serves, so a first sync doesn't
# fail outright on the entry plans.
HISTORICAL_BACKFILL_DAYS = 365

# CoinMarketCap's documented ceiling for `count`. Passed on every windowed request so the API
# doesn't fall back to its 10-item default when `time_start` is ignored for a given plan.
HISTORICAL_MAX_COUNT = 10000


@dataclass
class CoinMarketCapEndpointConfig:
    name: str
    # Path on https://pro-api.coinmarketcap.com (e.g. "/v1/cryptocurrency/map").
    path: str
    # JSONPath to the list of records in the response body. Every CoinMarketCap
    # endpoint we sync wraps its collection under the top-level "data" key.
    data_selector: str = "data"
    # Stable created-style datetime field to partition by, or None to skip
    # partitioning. Only set where the field is reliably present on every row.
    partition_key: Optional[str] = None
    # Extra query params merged into every request for this endpoint (e.g. a
    # stable `sort` field for deterministic offset pagination).
    extra_params: dict[str, str] = field(default_factory=dict)


# CoinMarketCap's REST API wraps each collection under a top-level "data" key and
# shares 1-based `start`/`limit` offset pagination across list endpoints. All of
# these are "latest"/"map" snapshots with no server-side timestamp filter, so they
# are full refresh only (see INCREMENTAL_FIELDS below).
COINMARKETCAP_ENDPOINTS: dict[str, CoinMarketCapEndpointConfig] = {
    # Static-ish map of every active cryptocurrency tracked by CoinMarketCap.
    "cryptocurrency_map": CoinMarketCapEndpointConfig(
        name="cryptocurrency_map",
        path="/v1/cryptocurrency/map",
        partition_key="first_historical_data",
        # `sort=id` gives a stable order so offset pages don't skip/duplicate rows
        # as the listing shifts during a sync.
        extra_params={"sort": "id"},
    ),
    # Latest market data (price, market cap, volume, supply) for all active coins.
    "listings_latest": CoinMarketCapEndpointConfig(
        name="listings_latest",
        path="/v1/cryptocurrency/listings/latest",
        partition_key="date_added",
        # `date_added` is a stable per-coin field; sorting by it keeps offset
        # pagination deterministic (the default `market_cap` reorders mid-sync).
        extra_params={"sort": "date_added", "sort_dir": "asc"},
    ),
    # All cryptocurrency categories (DeFi, NFTs, etc.) with aggregate market data.
    "categories": CoinMarketCapEndpointConfig(
        name="categories",
        path="/v1/cryptocurrency/categories",
    ),
    # All fiat currencies CoinMarketCap supports for quote conversions.
    "fiat_map": CoinMarketCapEndpointConfig(
        name="fiat_map",
        path="/v1/fiat/map",
        extra_params={"sort": "id"},
    ),
    # All exchanges tracked by CoinMarketCap (availability depends on plan tier).
    "exchange_map": CoinMarketCapEndpointConfig(
        name="exchange_map",
        path="/v1/exchange/map",
        extra_params={"sort": "id"},
    ),
    # Latest volume, liquidity and ranking per exchange. exchange_map carries no metrics.
    "exchange_listings_latest": CoinMarketCapEndpointConfig(
        name="exchange_listings_latest",
        path="/v1/exchange/listings/latest",
        # This endpoint's `sort` enum has no id option, and every other choice except `name` is a
        # metric that reorders mid-sync and would make offset pages skip or repeat exchanges.
        extra_params={
            "sort": "name",
            "sort_dir": "asc",
            "aux": "num_market_pairs,traffic_score,rank,exchange_score,effective_liquidity_24h,date_launched,fiats",
        },
    ),
}

# How a response body turns into rows.
# "object_map": `data` maps an id to one record, which is the row.
# "per_coin_quotes": `data` maps an id to a record holding a `quotes` array; each quote becomes
#   a row carrying the coin's identity fields.
# "quote_list": `data` is a single object whose `quotes` array is the whole table.
RowShape = Literal["object_map", "per_coin_quotes", "quote_list"]

# Where the ids for an `id=` param come from.
# "map": every id in /v1/cryptocurrency/map.
# "top_by_market_cap": the HISTORICAL_COIN_LIMIT highest-ranked coins in listings/latest.
# "exchange_map": every id in /v1/exchange/map.
# "top_exchanges_by_volume": the HISTORICAL_EXCHANGE_LIMIT highest-volume exchanges in
#   exchange/listings/latest.
CoinUniverse = Literal["map", "top_by_market_cap", "exchange_map", "top_exchanges_by_volume"]


@frozen
class CoinMarketCapBatchEndpointConfig:
    """An endpoint the source iterates itself instead of driving the offset paginator.

    These take no `start`/`limit`: the lookup and per-coin history endpoints are addressed by an
    explicit id list, and global metrics returns one series in a single response.
    """

    name: str
    path: str
    primary_keys: list[str]
    row_shape: RowShape
    # None for an endpoint that takes no ids at all.
    universe: Optional[CoinUniverse] = None
    batch_size: int = METADATA_BATCH_SIZE
    # Whether the endpoint takes a `time_start` history window.
    windowed: bool = False
    partition_key: Optional[str] = None
    extra_params: dict[str, str] = field(default_factory=dict)


COINMARKETCAP_BATCH_ENDPOINTS: dict[str, CoinMarketCapBatchEndpointConfig] = {
    # Static metadata (tags, platform, category, urls) resolving the ids in cryptocurrency_map.
    "cryptocurrency_info": CoinMarketCapBatchEndpointConfig(
        name="cryptocurrency_info",
        path="/v2/cryptocurrency/info",
        primary_keys=["id"],
        row_shape="object_map",
        universe="map",
        extra_params={
            "aux": "urls,logo,description,tags,platform,date_added,notice,status",
            # A coin delisted between the map walk and this request would otherwise fail the
            # whole batch rather than the one id.
            "skip_invalid": "true",
        },
    ),
    # Daily price, volume and market cap per coin.
    "quotes_historical": CoinMarketCapBatchEndpointConfig(
        name="quotes_historical",
        path="/v3/cryptocurrency/quotes/historical",
        primary_keys=["id", "timestamp"],
        row_shape="per_coin_quotes",
        universe="top_by_market_cap",
        batch_size=HISTORICAL_BATCH_SIZE,
        windowed=True,
        partition_key="timestamp",
        extra_params={
            "interval": "daily",
            "count": str(HISTORICAL_MAX_COUNT),
            "skip_invalid": "true",
            "aux": (
                "price,volume,market_cap,circulating_supply,total_supply,"
                "quote_timestamp,is_active,is_fiat,search_interval"
            ),
        },
    ),
    # Daily OHLCV candles plus market cap per coin.
    "ohlcv_historical": CoinMarketCapBatchEndpointConfig(
        name="ohlcv_historical",
        path="/v2/cryptocurrency/ohlcv/historical",
        primary_keys=["id", "time_open"],
        row_shape="per_coin_quotes",
        universe="top_by_market_cap",
        batch_size=HISTORICAL_BATCH_SIZE,
        windowed=True,
        partition_key="time_open",
        extra_params={
            "time_period": "daily",
            "interval": "daily",
            "count": str(HISTORICAL_MAX_COUNT),
            "skip_invalid": "true",
        },
    ),
    # Static metadata (launch date, logo, urls, fee docs) resolving the ids in exchange_map.
    "exchange_info": CoinMarketCapBatchEndpointConfig(
        name="exchange_info",
        path="/v1/exchange/info",
        primary_keys=["id"],
        row_shape="object_map",
        universe="exchange_map",
        extra_params={"aux": "urls,logo,description,date_launched,notice,status"},
    ),
    # Daily traded volume and market pair count per exchange.
    "exchange_quotes_historical": CoinMarketCapBatchEndpointConfig(
        name="exchange_quotes_historical",
        path="/v1/exchange/quotes/historical",
        primary_keys=["id", "timestamp"],
        row_shape="per_coin_quotes",
        universe="top_exchanges_by_volume",
        batch_size=HISTORICAL_BATCH_SIZE,
        windowed=True,
        partition_key="timestamp",
        extra_params={
            "interval": "daily",
            "count": str(HISTORICAL_MAX_COUNT),
        },
    ),
    # Total market cap, BTC/ETH dominance and altcoin market cap over time.
    "global_metrics_quotes_historical": CoinMarketCapBatchEndpointConfig(
        name="global_metrics_quotes_historical",
        path="/v1/global-metrics/quotes/historical",
        primary_keys=["timestamp"],
        row_shape="quote_list",
        windowed=True,
        partition_key="timestamp",
        extra_params={
            "interval": "daily",
            "count": str(HISTORICAL_MAX_COUNT),
            "aux": (
                "btc_dominance,eth_dominance,active_cryptocurrencies,active_exchanges,"
                "active_market_pairs,total_volume_24h,total_volume_24h_reported,"
                "altcoin_market_cap,altcoin_volume_24h,altcoin_volume_24h_reported,search_interval"
            ),
        },
    ),
}


@frozen
class CoinMarketCapSnapshotEndpointConfig:
    """An endpoint returning one ranked snapshot per UTC day, addressed by a `date` param.

    The source walks the days itself, one request each, and pages the ranking down to `limit`.
    """

    name: str
    path: str
    primary_keys: list[str]
    # Field stamped onto every row with the UTC day the snapshot was requested for. The response
    # carries no such field, and `last_updated` repeats across days for a coin that has stopped
    # trading, so two days of rows would otherwise collapse into one on merge.
    date_field: str
    limit: int
    partition_key: Optional[str] = None
    extra_params: dict[str, str] = field(default_factory=dict)


COINMARKETCAP_SNAPSHOT_ENDPOINTS: dict[str, CoinMarketCapSnapshotEndpointConfig] = {
    # Daily ranked snapshot of the market, so rank changes can be read back without polling
    # listings/latest.
    "listings_historical": CoinMarketCapSnapshotEndpointConfig(
        name="listings_historical",
        path="/v1/cryptocurrency/listings/historical",
        primary_keys=["id", "snapshot_date"],
        date_field="snapshot_date",
        limit=LISTINGS_HISTORICAL_RANK_LIMIT,
        partition_key="snapshot_date",
        extra_params={
            "sort": "cmc_rank",
            "sort_dir": "asc",
            "aux": "platform,tags,date_added,circulating_supply,total_supply,max_supply,cmc_rank,num_market_pairs",
        },
    ),
}

ENDPOINTS = (
    *COINMARKETCAP_ENDPOINTS.keys(),
    *COINMARKETCAP_BATCH_ENDPOINTS.keys(),
    *COINMARKETCAP_SNAPSHOT_ENDPOINTS.keys(),
)

# Only the two tables whose rows form one global series over time sync incrementally, because the
# single watermark the pipeline hands a source is exactly the right lower bound for both: global
# metrics filters on `time_start`, and the daily ranked snapshot walks days from the watermark.
#
# The "latest"/"map" endpoints reflect current state with no `since`-style filter, so an
# "incremental" sync would re-fetch every page anyway. The per-coin and per-exchange historical
# endpoints do take `time_start`, but their universe is the top of a ranking and that ranking
# churns: driving `time_start` off a watermark shared by every entity would give one that enters
# the universe later only the history since that watermark, and nothing would ever fill the gap.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "global_metrics_quotes_historical": [
        {
            "label": "timestamp",
            "type": IncrementalFieldType.DateTime,
            "field": "timestamp",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    "listings_historical": [
        {
            "label": "snapshot_date",
            "type": IncrementalFieldType.Date,
            "field": "snapshot_date",
            "field_type": IncrementalFieldType.Date,
        }
    ],
}
