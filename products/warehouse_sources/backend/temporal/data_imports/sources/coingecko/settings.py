from dataclasses import field
from datetime import date

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField

# The endpoints that fan out over the configured coin list rather than being fetched once, named so
# the fan-out and row-shaping paths reference them without repeating the string.
TICKERS_ENDPOINT = "coins_tickers"
MARKET_CHART_ENDPOINT = "coins_market_chart"
OHLC_ENDPOINT = "coins_ohlc"

# Top-level endpoints whose body has to be reshaped into rows rather than being a row list already,
# named so the row builders and the routing in coingecko.py reference them without repeating the
# string.
EXCHANGE_RATES_ENDPOINT = "exchange_rates"
GLOBAL_MARKET_CAP_CHART_ENDPOINT = "global_market_cap_chart"

# /global/market_cap_chart takes a relative `days` window from a fixed enum rather than a from/to
# range. `days=1` is served at hourly granularity and every larger value at daily, so 1 is left out:
# a shorter window would return hourly points that don't line up with the daily rows already synced.
GLOBAL_CHART_DAYS_OPTIONS = ("7", "14", "30", "90", "180", "365", "max")

# /coins/{id}/tickers is fixed at 100 items per page, unlike the 250 the other list endpoints take.
TICKERS_PAGE_SIZE = 100

# Days per request for the timeseries endpoints. /coins/{id}/ohlc/range caps a daily-interval
# request at 180 candles; market_chart/range publishes no cap, so it reuses the same window rather
# than guessing a larger one.
CHART_WINDOW_DAYS = 180

# Each coin costs a request per page (tickers) or per date window (timeseries), so an unbounded
# coin list can burn a whole month of credits in one sync. CoinGecko lists far more coins than a
# sync can walk, so the coin list is a deliberate pick rather than a slice of the whole catalog.
MAX_COINS = 25

# How far back the timeseries endpoints reach on a first sync when no start date is set. The Demo
# plan only serves the past 365 days, so this default is the most history every plan can fetch.
DEFAULT_HISTORY_DAYS = 365

# Floor for any configured start date, including one stored before this floor existed. CoinGecko's
# granular history begins in early 2018, so an earlier date buys no rows while fanning out into an
# unbounded number of empty request windows and Redis checkpoints.
MINIMUM_START_DATE = date(2018, 1, 1)


@frozen
class CoinGeckoEndpointConfig:
    name: str
    path: str
    # Per-endpoint primary keys. CoinGecko ids are globally unique within a resource type, so a
    # single id column is enough for the catalog/snapshot endpoints we expose.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Whether the endpoint supports page/per_page pagination. Reference endpoints (e.g. /coins/list)
    # return the whole collection in one response and ignore pagination params.
    paginated: bool = False
    # Page size. None means the source default (250). Some endpoints cap it lower (e.g. /insights
    # allows at most 20), so it is overridable per endpoint. Sent as `per_page` where the endpoint
    # takes it; /coins/{id}/tickers has no such parameter, so there it only tells the paginator how
    # wide a full page is.
    page_size: int | None = None
    # Hard cap on the page number to request, for endpoints the API refuses to page past
    # (e.g. /insights rejects page > 20). None means walk until a short/empty page.
    max_pages: int | None = None
    # Extra static query params (e.g. vs_currency for /coins/markets).
    extra_params: dict[str, str] = field(default_factory=dict)
    should_sync_default: bool = True
    # jsonpath to the rows inside the response envelope. None means the body is a bare array.
    data_selector: str | None = None
    # Whether ``path`` carries a ``{coin_id}`` placeholder, making the endpoint a fan-out over the
    # configured coin list instead of a single top-level fetch.
    per_coin: bool = False
    # Date-range size per request for the timeseries endpoints, so a long backfill is split into
    # windows the API accepts. None for the snapshot endpoints.
    window_days: int | None = None
    # Timestamp column the timeseries endpoints are keyed, partitioned and filtered on.
    date_field: str | None = None
    # Whether CoinGecko serves the endpoint only to paid plans. A Demo key gets a 401 back, so these
    # endpoints are gated on the configured plan rather than offered to everyone.
    pro_only: bool = False


COINGECKO_ENDPOINTS: dict[str, CoinGeckoEndpointConfig] = {
    # Full catalog of every coin tracked by CoinGecko (id/symbol/name). Reference data, one response.
    "coins_list": CoinGeckoEndpointConfig(
        name="coins_list",
        path="/coins/list",
    ),
    # Market snapshot (price, market cap, volume, supply, ATH/ATL, ...) for every coin, in USD.
    # Paginated up to 250 per page. Snapshot data — full refresh only (no server-side updated filter).
    "coins_markets": CoinGeckoEndpointConfig(
        name="coins_markets",
        path="/coins/markets",
        paginated=True,
        extra_params={"vs_currency": "usd"},
    ),
    # Category market data (market cap, 24h volume, top coins, ...). Single response.
    "coins_categories": CoinGeckoEndpointConfig(
        name="coins_categories",
        path="/coins/categories",
    ),
    # Reference list of category id/name pairs. Single response.
    "coins_categories_list": CoinGeckoEndpointConfig(
        name="coins_categories_list",
        path="/coins/categories/list",
        primary_keys=["category_id"],
    ),
    # Exchange metadata (name, country, trust score, 24h BTC volume, ...). Paginated.
    "exchanges": CoinGeckoEndpointConfig(
        name="exchanges",
        path="/exchanges",
        paginated=True,
    ),
    # Reference list of exchange id/name pairs. Single response.
    "exchanges_list": CoinGeckoEndpointConfig(
        name="exchanges_list",
        path="/exchanges/list",
    ),
    # Blockchain platforms (Ethereum, Solana, ...) coins can live on. Single response.
    "asset_platforms": CoinGeckoEndpointConfig(
        name="asset_platforms",
        path="/asset_platforms",
    ),
    # Latest coin insights published on CoinGecko (Pro/Enterprise). Paginated, but the API caps both
    # per_page and page at 20. Insight rows carry no id, so key on title + posted_at.
    "insights": CoinGeckoEndpointConfig(
        name="insights",
        path="/insights",
        paginated=True,
        page_size=20,
        max_pages=20,
        primary_keys=["title", "posted_at"],
    ),
    # Market pairs for a coin across centralized and decentralized exchanges, which is the join
    # between the coins and exchanges we already sync. Paginated at a fixed 100 per page, wrapped in a
    # ``tickers`` envelope. A ticker carries no id, so key on the coin, the exchange and the pair.
    TICKERS_ENDPOINT: CoinGeckoEndpointConfig(
        name=TICKERS_ENDPOINT,
        path="/coins/{coin_id}/tickers",
        per_coin=True,
        paginated=True,
        page_size=TICKERS_PAGE_SIZE,
        data_selector="tickers",
        primary_keys=["coin_id", "market_identifier", "base", "target"],
        should_sync_default=False,
    ),
    # Daily price, market cap and volume history per coin, in USD. Fetched in date windows, so the
    # `from`/`to` filter makes this a genuinely incremental endpoint.
    MARKET_CHART_ENDPOINT: CoinGeckoEndpointConfig(
        name=MARKET_CHART_ENDPOINT,
        path="/coins/{coin_id}/market_chart/range",
        per_coin=True,
        window_days=CHART_WINDOW_DAYS,
        date_field="timestamp",
        primary_keys=["coin_id", "timestamp"],
        # Without `interval` the API picks granularity from the window length, so a shorter
        # incremental window would return hourly points that don't line up with the daily ones
        # already synced. Pin it so every window returns the same grain.
        extra_params={"vs_currency": "usd", "interval": "daily"},
        should_sync_default=False,
    ),
    # Daily OHLC candles per coin, in USD. Requires a Pro key on the Analyst plan or above.
    OHLC_ENDPOINT: CoinGeckoEndpointConfig(
        name=OHLC_ENDPOINT,
        path="/coins/{coin_id}/ohlc/range",
        per_coin=True,
        window_days=CHART_WINDOW_DAYS,
        date_field="timestamp",
        primary_keys=["coin_id", "timestamp"],
        # `interval` is required here, and `daily` is what the 180-day window above is sized for.
        extra_params={"vs_currency": "usd", "interval": "daily"},
        should_sync_default=False,
    ),
    # Market-wide totals: active coins, exchange count, total market cap and volume per currency,
    # and per-coin market cap dominance. One object under a `data` envelope, so one row per sync.
    "global_market_data": CoinGeckoEndpointConfig(
        name="global_market_data",
        path="/global",
        data_selector="data",
        primary_keys=["updated_at"],
    ),
    # Historical market-wide market cap and volume, which is the timeseries behind global_market_data.
    # Two parallel [timestamp, value] series under a `market_cap_chart` envelope, zipped into one row
    # per timestamp. Requires a Pro key on the Analyst plan or above.
    GLOBAL_MARKET_CAP_CHART_ENDPOINT: CoinGeckoEndpointConfig(
        name=GLOBAL_MARKET_CAP_CHART_ENDPOINT,
        path="/global/market_cap_chart",
        data_selector="market_cap_chart",
        date_field="timestamp",
        primary_keys=["timestamp"],
        extra_params={"vs_currency": "usd"},
        pro_only=True,
    ),
    # BTC-to-currency rates, which normalise the BTC-denominated columns on the derivatives and
    # exchanges tables into any other currency. One object keyed by currency code under a `rates`
    # envelope, flattened into a row per currency.
    EXCHANGE_RATES_ENDPOINT: CoinGeckoEndpointConfig(
        name=EXCHANGE_RATES_ENDPOINT,
        path="/exchange_rates",
        data_selector="rates",
    ),
    # Derivatives venues with open interest, 24h volume and contract counts. Paginated.
    "derivatives_exchanges": CoinGeckoEndpointConfig(
        name="derivatives_exchanges",
        path="/derivatives/exchanges",
        paginated=True,
    ),
    # Every perpetual and futures contract across those venues, with price, funding rate, open
    # interest and 24h volume. One bare array with no pagination params. A ticker carries no id, so
    # key on the venue and the contract symbol.
    "derivatives_tickers": CoinGeckoEndpointConfig(
        name="derivatives_tickers",
        path="/derivatives",
        primary_keys=["market", "symbol"],
    ),
    # NFT collections with floor price, market cap and 24h volume. Paginated. Requires a Pro key on
    # the Analyst plan or above.
    "nfts_markets": CoinGeckoEndpointConfig(
        name="nfts_markets",
        path="/nfts/markets",
        paginated=True,
        pro_only=True,
    ),
}

ENDPOINTS = tuple(COINGECKO_ENDPOINTS.keys())

# Only the timeseries endpoints take a server-side date filter. Every catalog and snapshot endpoint
# exposes no updated_after/since parameter, so those stay full refresh with an empty candidate list.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: [incremental_field(config.date_field)] if config.date_field else []
    for name, config in COINGECKO_ENDPOINTS.items()
}

# The timeseries endpoints re-read the window holding the last synced day, so the still-moving
# current day is restated instead of frozen at whatever it was first imported as. Append would
# write a second row for every day in that overlap, so merge is the only valid incremental mode.
MERGE_ONLY_ENDPOINTS = tuple(name for name, config in COINGECKO_ENDPOINTS.items() if config.date_field)

# The per-coin endpoints can only sync once coin IDs are configured, so they start disabled rather
# than queueing a sync that can only fail.
SHOULD_SYNC_DEFAULT = {name: config.should_sync_default for name, config in COINGECKO_ENDPOINTS.items()}

PER_COIN_ENDPOINTS = tuple(name for name, config in COINGECKO_ENDPOINTS.items() if config.per_coin)

# Endpoints a Demo key can't reach at all, so they are offered only to a source configured with a
# Pro key rather than queueing a sync that can only 401.
PRO_ONLY_ENDPOINTS = tuple(name for name, config in COINGECKO_ENDPOINTS.items() if config.pro_only)
