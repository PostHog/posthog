from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField


@dataclass
class FinageEndpointConfig:
    name: str
    # Finage path template. `{symbol}` is filled per symbol; aggregate paths additionally fill
    # `{multiplier}` / `{timespan}` / `{from_date}` / `{to_date}`.
    path: str
    primary_keys: list[str] = field(default_factory=lambda: ["symbol"])
    # Stable datetime column to partition on (only the aggregate bars have one). Never a value that
    # changes after a row is first written.
    partition_key: str | None = None
    # True for the historical OHLCV aggregate endpoint: returns a `results` array of bars windowed by
    # a date range in the path, rather than a single point-in-time object.
    is_aggregate: bool = False
    should_sync_default: bool = True


# US-stock scope for the initial release. Finage exposes the same path shapes for forex/crypto/indices
# (e.g. `/last/forex/{symbol}`, `/agg/crypto/{symbol}/...`), so adding other asset classes later is a
# matter of parameterizing the market segment.
#
# Paths and response shapes are taken from the public Finage docs (https://finage.co.uk/docs); they
# could not be curl-verified against the live API because that requires a paid key. The aggregate and
# quote shapes are well documented; `last_trade` (`/last/trade/stock/{symbol}` -> {symbol, price, size,
# timestamp}) is the least certain and should be confirmed once a key is available.
FINAGE_ENDPOINTS: dict[str, FinageEndpointConfig] = {
    "last_quote": FinageEndpointConfig(
        name="last_quote",
        path="/last/stock/{symbol}",
        primary_keys=["symbol"],
    ),
    "last_trade": FinageEndpointConfig(
        name="last_trade",
        path="/last/trade/stock/{symbol}",
        primary_keys=["symbol"],
    ),
    "aggregates": FinageEndpointConfig(
        name="aggregates",
        path="/agg/stock/{symbol}/{multiplier}/{timespan}/{from_date}/{to_date}",
        # The bar timestamp `t` is only unique within a symbol, so the symbol is part of the key —
        # otherwise fan-out rows from different symbols collide and every merge multi-matches them.
        primary_keys=["symbol", "t"],
        partition_key="date",
        is_aggregate=True,
    ),
}

ENDPOINTS = tuple(FINAGE_ENDPOINTS.keys())

# Finage has no cross-resource `updated_after` cursor. Quote/trade endpoints are point-in-time, and
# the aggregate endpoint fans out per symbol — concatenating per-symbol bar streams isn't globally
# ascending, so a single watermark can't be checkpointed safely. Every endpoint therefore ships full
# refresh, and there are no advertised incremental fields.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {name: [] for name in FINAGE_ENDPOINTS}
