from dataclasses import field
from typing import Any, Literal, Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField

PaginationStyle = Literal["keyset", "offset", "cursor"]

GAMMA_BASE_URL = "https://gamma-api.polymarket.com"
DATA_API_BASE_URL = "https://data-api.polymarket.com"


@frozen
class PolymarketEndpointConfig:
    name: str
    path: str
    pagination: PaginationStyle
    base_url: str = GAMMA_BASE_URL
    # Wrapper key holding the array on the keyset and cursor endpoints. The offset endpoints
    # return a bare JSON array, so they select nothing.
    data_key: Optional[str] = None
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    partition_key: Optional[str] = None
    page_size: int = 500
    params: dict[str, Any] = field(default_factory=dict)


# Gamma exposes no server-side filter on `createdAt` or `updatedAt`, so every table is full
# refresh. `start_date_min` looks like a candidate but filters the market's trading window rather
# than when the row was written, and a backdated window would silently drop rows from a sync.
POLYMARKET_ENDPOINTS: dict[str, PolymarketEndpointConfig] = {
    # Events group the markets that resolve one real-world question.
    "events": PolymarketEndpointConfig(
        name="events",
        path="/events/keyset",
        pagination="keyset",
        data_key="events",
        partition_key="createdAt",
    ),
    # One row per tradeable outcome, with prices, liquidity, and resolution state.
    "markets": PolymarketEndpointConfig(
        name="markets",
        path="/markets/keyset",
        pagination="keyset",
        data_key="markets",
        partition_key="createdAt",
    ),
    # Recurring groupings that events belong to, for example a weekly fixture.
    "series": PolymarketEndpointConfig(
        name="series",
        path="/series",
        pagination="offset",
        partition_key="createdAt",
    ),
    # The taxonomy applied to events and markets.
    "tags": PolymarketEndpointConfig(
        name="tags",
        path="/tags",
        pagination="offset",
        partition_key="createdAt",
    ),
    # The top winning positions by realized profit, read from the Data API. The board holds at most
    # 500 rows per window, so `time_period=all` keeps the all-time board rather than one day's.
    # One position can be won by many wallets, so the wallet is part of the key.
    "biggest_winners": PolymarketEndpointConfig(
        name="biggest_winners",
        path="/v2/biggest-winners",
        pagination="cursor",
        base_url=DATA_API_BASE_URL,
        data_key="data",
        primary_keys=["position_id", "user_id"],
        page_size=1000,
        params={"time_period": "all"},
    ),
}

ENDPOINTS = tuple(POLYMARKET_ENDPOINTS.keys())

# No endpoint advertises incremental, so every table syncs full refresh.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {name: [] for name in POLYMARKET_ENDPOINTS}
