from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField


@dataclass
class CoinGeckoEndpointConfig:
    name: str
    path: str
    # Per-endpoint primary keys. CoinGecko ids are globally unique within a resource type, so a
    # single id column is enough for the catalog/snapshot endpoints we expose.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Whether the endpoint supports page/per_page pagination. Reference endpoints (e.g. /coins/list)
    # return the whole collection in one response and ignore pagination params.
    paginated: bool = False
    # Extra static query params (e.g. vs_currency for /coins/markets).
    extra_params: dict[str, str] = field(default_factory=dict)
    should_sync_default: bool = True


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
}

ENDPOINTS = tuple(COINGECKO_ENDPOINTS.keys())

# CoinGecko's catalog/snapshot endpoints expose no server-side updated_after/since filter, so every
# exposed endpoint is full refresh only. The map is kept (empty) to mirror the other sources' shape
# and make adding a server-side-filterable endpoint later an additive change.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {name: [] for name in COINGECKO_ENDPOINTS}
