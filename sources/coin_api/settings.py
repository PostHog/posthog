from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# How a CoinAPI endpoint is shaped on the wire, which drives how the transport reads it:
# - "reference": a single bare JSON array of metadata rows (assets / exchanges / symbols).
# - "exchange_rate": an object `{asset_id_base, rates: [...]}` we flatten into one row per quote.
# - "timeseries": a time-windowed, paginated history walked forward via `time_start`.
EndpointKind = Literal["reference", "exchange_rate", "timeseries"]


@dataclass(frozen=True)
class CoinApiEndpointConfig:
    name: str
    path: str  # may contain `{symbol_id}` / `{base}` placeholders, resolved from config
    kind: EndpointKind
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable time field rows are partitioned by (timeseries only). Never an updated_at-style field.
    partition_key: Optional[str] = None
    # Time-series endpoints are scoped to a single market or metric the user configures on the source,
    # so they only sync once those fields are set. They're off by default to avoid surprising credit
    # spend. The symbol rides in the path where the endpoint has a `{symbol_id}` placeholder and in the
    # query string otherwise.
    requires_symbol: bool = False
    # Whether the endpoint needs a `metric_id` (from the metrics_listing table) to select a series.
    requires_metric: bool = False
    # Whether the endpoint needs a quote asset to pair with the configured exchange rate base asset.
    requires_quote_asset: bool = False
    # Aggregated history endpoints additionally need a `period_id` param (e.g. 1DAY).
    needs_period: bool = False
    # CoinAPI documents `time_end` as required on some history endpoints, and rejects the request
    # without it. The transport bounds those at the sync's start time.
    needs_time_end: bool = False
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
    # Every metric id CoinAPI supports, with its description. The lookup that makes the metric history
    # tables readable, and where a user finds the `metric_id` those tables are configured with.
    "metrics_listing": CoinApiEndpointConfig(
        name="metrics_listing",
        path="/v1/metrics/listing",
        kind="reference",
        primary_keys=["metric_id"],
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
    # Historical exchange rates between the configured base and quote assets, aggregated into the
    # configured period. Rows carry neither the assets nor the period, so all three are injected to
    # keep the primary key columns present.
    "exchange_rates_history": CoinApiEndpointConfig(
        name="exchange_rates_history",
        path="/v1/exchangerate/{base}/{quote}/history",
        kind="timeseries",
        primary_keys=["asset_id_base", "asset_id_quote", "period_id", "time_period_start"],
        incremental_fields=[_datetime_field("time_period_start")],
        partition_key="time_period_start",
        requires_quote_asset=True,
        needs_period=True,
        needs_time_end=True,
        should_sync_default=False,
    ),
    # Per-symbol derivative metrics (funding rate, open interest and the rest of the metrics_listing
    # catalogue) for the configured symbol. `period_id` is always sent: left off, CoinAPI returns raw
    # ticks in a different row shape, and the period-aggregated shape is what this primary key assumes.
    "metrics_symbol_history": CoinApiEndpointConfig(
        name="metrics_symbol_history",
        path="/v1/metrics/symbol/history",
        kind="timeseries",
        primary_keys=["symbol_id", "metric_id", "period_id", "time_period_start"],
        incremental_fields=[_datetime_field("time_period_start")],
        partition_key="time_period_start",
        requires_symbol=True,
        requires_metric=True,
        needs_period=True,
        should_sync_default=False,
    ),
    # Historical best bid/ask updates for the configured symbol. CoinAPI documents no unique id on a
    # quote, and its own example response repeats a row verbatim, so the whole row is the key —
    # identical updates carry no extra information and collapsing them keeps the merge key unique.
    "quotes_history": CoinApiEndpointConfig(
        name="quotes_history",
        path="/v1/quotes/{symbol_id}/history",
        kind="timeseries",
        primary_keys=[
            "symbol_id",
            "time_exchange",
            "time_coinapi",
            "ask_price",
            "ask_size",
            "bid_price",
            "bid_size",
        ],
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
