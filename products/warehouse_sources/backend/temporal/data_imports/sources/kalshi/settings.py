from dataclasses import field
from typing import Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@frozen
class KalshiEndpointConfig:
    name: str
    path: str
    data_key: str  # response wrapper key holding the array (e.g. "markets")
    primary_keys: list[str] = field(default_factory=lambda: ["ticker"])
    partition_key: Optional[str] = None  # stable creation-time field for datetime partitioning
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Only the trade, fill, and settlement endpoints expose a server-side time filter (`min_ts`), and
    # candlesticks take an explicit time window. Everything else accepts the param and silently ignores it, so those
    # endpoints are full-refresh only.
    supports_incremental: bool = False
    # Trades, fills, and settlements come back newest-first; every other endpoint is treated as ascending.
    newest_first: bool = False
    # `/series` returns the whole collection in one response with no `cursor` key.
    paginated: bool = True
    # Candlesticks are fetched per batch of markets, so rows arrive in no global time order.
    market_fan_out: bool = False
    # The weather index is served one city at a time, with no listing endpoint for the cities.
    city_fan_out: bool = False
    # Portfolio endpoints read the account's own data and need a signed API key.
    requires_auth: bool = False
    # Kalshi reads only subaccount 0 unless asked for another, or the rows do not say which
    # subaccount they belong to, so these endpoints are read once per subaccount.
    subaccount_fan_out: bool = False
    extra_params: dict[str, str] = field(default_factory=dict)
    page_size: int = 200


def _created_time_field() -> list[IncrementalField]:
    return [
        {
            "label": "created_time",
            "type": IncrementalFieldType.DateTime,
            "field": "created_time",
            "field_type": IncrementalFieldType.DateTime,
        }
    ]


def _settled_time_field() -> list[IncrementalField]:
    return [
        {
            "label": "settled_time",
            "type": IncrementalFieldType.DateTime,
            "field": "settled_time",
            "field_type": IncrementalFieldType.DateTime,
        }
    ]


def _end_period_ts_field() -> list[IncrementalField]:
    return [
        {
            "label": "end_period_ts",
            "type": IncrementalFieldType.Integer,
            "field": "end_period_ts",
            "field_type": IncrementalFieldType.Integer,
        }
    ]


def _weather_index_minute_field() -> list[IncrementalField]:
    return [
        {
            "label": "t",
            "type": IncrementalFieldType.Integer,
            "field": "t",
            "field_type": IncrementalFieldType.Integer,
        }
    ]


# Kalshi lists the configured index cities only in the 400 response for an unknown city.
WEATHER_INDEX_CITIES: tuple[str, ...] = (
    "miami",
    "dfw",
    "houston",
    "phl-delaware-valley",
    "puget-sound",
    "sf-bay",
    "greater-boston",
    "southeast-michigan",
    "kansas-city",
    "minneapolis-st-paul",
    "nyc",
    "chicago",
    "la-coastal",
)


KALSHI_ENDPOINTS: dict[str, KalshiEndpointConfig] = {
    # Every market ever listed, one row per contract. `updated_time` moves but there is no filter
    # for it, so this is a full refresh; partition on the stable `created_time`.
    "markets": KalshiEndpointConfig(
        name="markets",
        path="/markets",
        data_key="markets",
        primary_keys=["ticker"],
        partition_key="created_time",
        page_size=1000,
    ),
    # Events group related markets (one election, one game). Keyed on `event_ticker`; carries no
    # creation timestamp, so no partitioning.
    "events": KalshiEndpointConfig(
        name="events",
        path="/events",
        data_key="events",
        primary_keys=["event_ticker"],
        page_size=200,
    ),
    # Series are the recurring templates events are minted from. The endpoint returns all of them
    # in a single unpaginated response.
    "series": KalshiEndpointConfig(
        name="series",
        path="/series",
        data_key="series",
        primary_keys=["ticker"],
        paginated=False,
    ),
    # The one genuinely incremental stream: every public trade, append-only, filtered server-side
    # with `min_ts` and returned newest-first.
    "trades": KalshiEndpointConfig(
        name="trades",
        path="/markets/trades",
        data_key="trades",
        primary_keys=["trade_id"],
        partition_key="created_time",
        incremental_fields=_created_time_field(),
        supports_incremental=True,
        newest_first=True,
        page_size=1000,
    ),
    # Real-world happenings Kalshi ties markets to (a court date, a scheduled release).
    "milestones": KalshiEndpointConfig(
        name="milestones",
        path="/milestones",
        data_key="milestones",
        primary_keys=["id"],
        page_size=200,
    ),
    # Markets that settled before the historical cutoff move out of `/markets` into this archive.
    "historical_markets": KalshiEndpointConfig(
        name="historical_markets",
        path="/historical/markets",
        data_key="markets",
        primary_keys=["ticker"],
        partition_key="created_time",
        page_size=1000,
    ),
    # Trades filled before the historical cutoff. Like `/markets/trades`, it honours `min_ts` and
    # returns newest-first.
    "historical_trades": KalshiEndpointConfig(
        name="historical_trades",
        path="/historical/trades",
        data_key="trades",
        primary_keys=["trade_id"],
        partition_key="created_time",
        incremental_fields=_created_time_field(),
        supports_incremental=True,
        newest_first=True,
        page_size=1000,
    ),
    # Daily candlesticks for every live non-combo market, fetched in batches of tickers.
    "market_candlesticks": KalshiEndpointConfig(
        name="market_candlesticks",
        path="/markets/candlesticks",
        data_key="markets",
        primary_keys=["market_ticker", "end_period_ts"],
        incremental_fields=_end_period_ts_field(),
        supports_incremental=True,
        market_fan_out=True,
        page_size=1000,
    ),
    # Minute-resolution temperature index per city, filtered server-side with `from`/`to` (unix ms).
    # The API keeps only recent history, so incremental merge is what retains older minutes.
    "weather_index": KalshiEndpointConfig(
        name="weather_index",
        path="/live_data/weather/{city}",
        data_key="timeseries",
        primary_keys=["city", "t"],
        incremental_fields=_weather_index_minute_field(),
        supports_incremental=True,
        paginated=False,
        city_fan_out=True,
    ),
    # The account's own executions. `min_ts` filters on the fill time, and fills come back
    # newest-first like public trades.
    "fills": KalshiEndpointConfig(
        name="fills",
        path="/portfolio/fills",
        data_key="fills",
        primary_keys=["fill_id"],
        partition_key="created_time",
        incremental_fields=_created_time_field(),
        supports_incremental=True,
        newest_first=True,
        requires_auth=True,
        page_size=1000,
    ),
    # Fills before the historical cutoff, which `/portfolio/fills` no longer returns.
    "historical_fills": KalshiEndpointConfig(
        name="historical_fills",
        path="/historical/fills",
        data_key="fills",
        primary_keys=["fill_id"],
        partition_key="created_time",
        incremental_fields=_created_time_field(),
        supports_incremental=True,
        newest_first=True,
        requires_auth=True,
        page_size=1000,
    ),
    # Resting orders change status and fill counts in place, and the docs do not say which
    # timestamp `min_ts` filters on, so orders are a full refresh.
    "orders": KalshiEndpointConfig(
        name="orders",
        path="/portfolio/orders",
        data_key="orders",
        primary_keys=["order_id"],
        requires_auth=True,
        page_size=1000,
    ),
    # Canceled and executed orders archived before the historical cutoff.
    "historical_orders": KalshiEndpointConfig(
        name="historical_orders",
        path="/historical/orders",
        data_key="orders",
        primary_keys=["order_id"],
        requires_auth=True,
        page_size=1000,
    ),
    # One row per market position, settled or not, that is still in the live data set. Exposure and
    # realized P&L change on every fill, so this is a full refresh.
    "positions": KalshiEndpointConfig(
        name="positions",
        path="/portfolio/positions",
        data_key="market_positions",
        primary_keys=["subaccount_number", "ticker"],
        requires_auth=True,
        subaccount_fan_out=True,
        extra_params={"settlement_status": "all"},
        page_size=1000,
    ),
    # Settled positions after their event moves to the archive.
    "historical_positions": KalshiEndpointConfig(
        name="historical_positions",
        path="/historical/positions",
        data_key="market_positions",
        primary_keys=["subaccount_number", "ticker"],
        requires_auth=True,
        subaccount_fan_out=True,
        page_size=1000,
    ),
    # Payouts per settled market. A settlement carries only `settled_time`, which is what `min_ts`
    # filters on.
    "settlements": KalshiEndpointConfig(
        name="settlements",
        path="/portfolio/settlements",
        data_key="settlements",
        primary_keys=["subaccount_number", "ticker"],
        partition_key="settled_time",
        incremental_fields=_settled_time_field(),
        supports_incremental=True,
        newest_first=True,
        requires_auth=True,
        subaccount_fan_out=True,
        page_size=1000,
    ),
}

ENDPOINTS = tuple(KALSHI_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in KALSHI_ENDPOINTS.items()
}
