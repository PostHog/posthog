from dataclasses import dataclass, field
from enum import StrEnum

from products.warehouse_sources.backend.types import IncrementalField


class FinageEndpointKind(StrEnum):
    # A single current object per symbol.
    POINT_IN_TIME = "point_in_time"
    # A `results` array of OHLCV bars per symbol, windowed by a date range in the path.
    AGGREGATE = "aggregate"
    # A bare JSON array of one company's historical records, addressed by symbol.
    SYMBOL_HISTORY = "symbol_history"
    # A bare JSON array of market-wide events, windowed by required `from` / `to` query params.
    CALENDAR = "calendar"


# Statement endpoints report one row per fiscal period and default to annual, so both periods are
# requested to give the table the full filing history rather than only the yearly summary.
STATEMENT_PERIODS = ("annual", "quarter")


@dataclass
class FinageEndpointConfig:
    name: str
    # Finage path template. `{symbol}` is filled per symbol; aggregate paths additionally fill
    # `{multiplier}` / `{timespan}` / `{from_date}` / `{to_date}`.
    path: str
    kind: FinageEndpointKind
    primary_keys: list[str] = field(default_factory=lambda: ["symbol"])
    # Stable datetime column to partition on. Never a value that changes after a row is first written.
    partition_key: str | None = None
    # Fiscal periods to request separately. Empty for endpoints that take no `period` param.
    periods: tuple[str, ...] = ()
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
        kind=FinageEndpointKind.POINT_IN_TIME,
        primary_keys=["symbol"],
    ),
    "last_trade": FinageEndpointConfig(
        name="last_trade",
        path="/last/trade/stock/{symbol}",
        kind=FinageEndpointKind.POINT_IN_TIME,
        primary_keys=["symbol"],
    ),
    "aggregates": FinageEndpointConfig(
        name="aggregates",
        path="/agg/stock/{symbol}/{multiplier}/{timespan}/{from_date}/{to_date}",
        kind=FinageEndpointKind.AGGREGATE,
        # The bar timestamp `t` is only unique within a symbol, so the symbol is part of the key —
        # otherwise fan-out rows from different symbols collide and every merge multi-matches them.
        primary_keys=["symbol", "t"],
        partition_key="date",
    ),
    "historical_dividends": FinageEndpointConfig(
        name="historical_dividends",
        path="/fnd/historical-dividends/{symbol}",
        kind=FinageEndpointKind.SYMBOL_HISTORY,
        # The response carries no symbol, so the requested symbol is pinned onto every row and is
        # part of the key. `date` is the ex-dividend date, which is unique within a symbol.
        primary_keys=["symbol", "date"],
        partition_key="date",
    ),
    "historical_stock_splits": FinageEndpointConfig(
        name="historical_stock_splits",
        path="/fnd/historical-stock-splits/{symbol}",
        kind=FinageEndpointKind.SYMBOL_HISTORY,
        # Same shape as historical dividends: no symbol in the response, one event per date.
        primary_keys=["symbol", "date"],
        partition_key="date",
    ),
    "balance_sheet_statements": FinageEndpointConfig(
        name="balance_sheet_statements",
        path="/fnd/balance-sheet-statements/{symbol}",
        kind=FinageEndpointKind.SYMBOL_HISTORY,
        # A fiscal year ends on the same date as its closing quarter, so both statements carry the
        # same `date` for a symbol and only `period` separates them.
        primary_keys=["symbol", "date", "period"],
        partition_key="date",
        periods=STATEMENT_PERIODS,
    ),
    "cash_flow_statement": FinageEndpointConfig(
        name="cash_flow_statement",
        path="/fnd/cash-flow-statement/{symbol}",
        kind=FinageEndpointKind.SYMBOL_HISTORY,
        primary_keys=["symbol", "date", "period"],
        partition_key="date",
        periods=STATEMENT_PERIODS,
    ),
    # The two calendars cover every listed company rather than the configured symbols, so they are a
    # much larger table than the rest of the source and are left off by default.
    "dividend_calendar": FinageEndpointConfig(
        name="dividend_calendar",
        path="/fnd/dividend-calendar",
        kind=FinageEndpointKind.CALENDAR,
        primary_keys=["symbol", "date"],
        partition_key="date",
        should_sync_default=False,
    ),
    "stock_split_calendar": FinageEndpointConfig(
        name="stock_split_calendar",
        path="/fnd/stock-split-calendar",
        kind=FinageEndpointKind.CALENDAR,
        primary_keys=["symbol", "date"],
        partition_key="date",
        should_sync_default=False,
    ),
}

ENDPOINTS = tuple(FINAGE_ENDPOINTS.keys())

# Finage has no cross-resource `updated_after` cursor. Quote/trade endpoints are point-in-time, and
# the aggregate and fundamentals endpoints fan out per symbol, so concatenating the per-symbol streams
# isn't globally ascending and a single watermark can't be checkpointed safely. The two calendars filter
# on the event date, but they also list events that have been declared and not yet happened, so a
# watermark taken from the newest row lands in the future and skips events declared afterwards for an
# earlier date. Every endpoint therefore ships full refresh, and there are no advertised incremental
# fields.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {name: [] for name in FINAGE_ENDPOINTS}
