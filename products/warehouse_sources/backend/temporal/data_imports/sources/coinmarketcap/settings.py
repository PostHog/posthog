from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField

# CoinMarketCap caps `limit` at 5000 records per page across its list endpoints.
# A larger page size means fewer HTTP calls (kinder to the per-minute rate limit);
# the monthly credit cost is per data point, so it's unaffected by page size.
PAGE_SIZE = 5000


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
}

ENDPOINTS = tuple(COINMARKETCAP_ENDPOINTS.keys())

# Full refresh only. CoinMarketCap's "latest"/"map" endpoints reflect current state
# with no `since`/`updated_after`-style server-side filter, so an "incremental" sync
# would re-fetch every page anyway. Historical endpoints expose `time_start`/`time_end`
# windows, but they're gated behind higher paid tiers, so they aren't synced here.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
