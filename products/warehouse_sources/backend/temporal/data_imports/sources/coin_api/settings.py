from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# How a CoinAPI endpoint is shaped on the wire, which drives how the transport reads it:
# - "reference": a single bare JSON array of metadata rows (assets / exchanges / symbols).
# - "exchange_rate": an object `{asset_id_base, rates: [...]}` we flatten into one row per quote.
# - "timeseries": a time-windowed, paginated history walked forward via `time_start`.
EndpointKind = Literal["reference", "exchange_rate", "timeseries"]


@dataclass
class CoinApiEndpointConfig:
    name: str
    path: str  # may contain `{symbol_id}` / `{base}` placeholders, resolved from config
    kind: EndpointKind
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable time field rows are partitioned by (timeseries only). Never an updated_at-style field.
    partition_key: Optional[str] = None
    # Time-series endpoints are scoped to a single symbol passed in the path, so they only sync when
    # the user has configured a `symbol_id`. They're off by default to avoid surprising credit spend.
    requires_symbol: bool = False
    # OHLCV history additionally needs a `period_id` aggregation param (e.g. 1DAY).
    needs_period: bool = False
    should_sync_default: bool = True


def _datetime_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


COIN_API_ENDPOINTS: dict[str, CoinApiEndpointConfig] = {
    # Reference metadata. Full collections returned in a single response; full refresh only — CoinAPI
    # exposes no server-side "modified since" filter on these.
    "assets": CoinApiEndpointConfig(
        name="assets",
        path="/v1/assets",
        kind="reference",
        primary_keys=["asset_id"],
    ),
    "exchanges": CoinApiEndpointConfig(
        name="exchanges",
        path="/v1/exchanges",
        kind="reference",
        primary_keys=["exchange_id"],
    ),
    "symbols": CoinApiEndpointConfig(
        name="symbols",
        path="/v1/symbols",
        kind="reference",
        primary_keys=["symbol_id"],
    ),
    # Current exchange rates from the configured base asset to every other asset. A point-in-time
    # snapshot — full refresh only. `asset_id_base` is injected per row from the configured base.
    "exchange_rates": CoinApiEndpointConfig(
        name="exchange_rates",
        path="/v1/exchangerate/{base}",
        kind="exchange_rate",
        primary_keys=["asset_id_base", "asset_id_quote"],
    ),
    # OHLCV candles for the configured symbol/period. Incremental on `time_period_start`; periods are
    # immutable once closed, so the [symbol_id, period_id, time_period_start] key is stable and unique.
    "ohlcv_history": CoinApiEndpointConfig(
        name="ohlcv_history",
        path="/v1/ohlcv/{symbol_id}/history",
        kind="timeseries",
        primary_keys=["symbol_id", "period_id", "time_period_start"],
        incremental_fields=[_datetime_field("time_period_start")],
        partition_key="time_period_start",
        requires_symbol=True,
        needs_period=True,
        should_sync_default=False,
    ),
    # Individual trades for the configured symbol. Each trade carries a globally-unique `uuid`, so
    # re-fetching the `time_start` boundary on resume dedupes cleanly on merge. Incremental on
    # `time_exchange` (the trade's exchange timestamp, which never changes).
    "trades_history": CoinApiEndpointConfig(
        name="trades_history",
        path="/v1/trades/{symbol_id}/history",
        kind="timeseries",
        primary_keys=["uuid"],
        incremental_fields=[_datetime_field("time_exchange"), _datetime_field("time_coinapi")],
        partition_key="time_exchange",
        requires_symbol=True,
        should_sync_default=False,
    ),
}

ENDPOINTS = tuple(COIN_API_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in COIN_API_ENDPOINTS.items()
}
