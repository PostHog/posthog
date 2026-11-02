from dataclasses import field
from enum import StrEnum

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField


class FinageEndpointKind(StrEnum):
    # A single current object per symbol.
    POINT_IN_TIME = "point_in_time"
    # A `results` array of OHLCV bars per symbol, windowed by a date range in the path.
    AGGREGATE = "aggregate"
    # A bare JSON array of one company's historical records, addressed by symbol.
    SYMBOL_HISTORY = "symbol_history"
    # A bare JSON array holding one company's current, undated profile.
    SYMBOL_PROFILE = "symbol_profile"
    # A bare JSON array of market-wide events, windowed by required `from` / `to` query params.
    CALENDAR = "calendar"
    # A page-numbered `{page, symbols}` listing of every tradeable symbol in a market.
    SYMBOL_LIST = "symbol_list"


class FinageAssetClass(StrEnum):
    """Which configured symbol list an endpoint fans out over."""

    STOCK = "stock"
    FOREX = "forex"
    CRYPTO = "crypto"


# Statement endpoints report one row per fiscal period and default to annual, so both periods are
# requested to give the table the full filing history rather than only the yearly summary.
STATEMENT_PERIODS = ("annual", "quarter")

# Markets the symbol list is pulled for. Finage also lists ca-stock / in-stock / ru-stock / index,
# but this source syncs no data for those, so their symbols would resolve nothing.
SYMBOL_LIST_MARKETS = ("us-stock", "forex", "crypto")


@frozen
class FinageEndpointConfig:
    name: str
    # Finage path template. `{symbol}` is filled per symbol; aggregate paths additionally fill
    # `{multiplier}` / `{timespan}` / `{from_date}` / `{to_date}`.
    path: str
    kind: FinageEndpointKind
    primary_keys: list[str] = field(default_factory=lambda: ["symbol"])
    # Which configured symbol list the endpoint fans out over.
    asset_class: FinageAssetClass = FinageAssetClass.STOCK
    # Stable datetime column to partition on. Never a value that changes after a row is first written.
    partition_key: str | None = None
    # Fiscal periods to request separately. Empty for endpoints that take no `period` param.
    periods: tuple[str, ...] = ()
    # Markets to request separately, each filled into `{market}`. Only used by SYMBOL_LIST.
    markets: tuple[str, ...] = ()
    # Query params sent on top of the ones the endpoint kind already builds.
    extra_params: dict[str, str] = field(default_factory=dict)
    should_sync_default: bool = True


# Finage exposes the same quote and aggregate path shapes per asset class, so the forex and crypto
# tables reuse the stock kinds and only differ in which configured symbol list they fan out over.
# Indices and ETFs are reachable the same way but have no configured symbol list yet.
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
    "income_statement": FinageEndpointConfig(
        name="income_statement",
        path="/fnd/income-statement/{symbol}",
        kind=FinageEndpointKind.SYMBOL_HISTORY,
        primary_keys=["symbol", "date", "period"],
        partition_key="date",
        periods=STATEMENT_PERIODS,
    ),
    # One current, undated profile row per symbol — the dimension table the price tables join to.
    "stock_details": FinageEndpointConfig(
        name="stock_details",
        path="/fnd/detail/stock/{symbol}",
        kind=FinageEndpointKind.SYMBOL_PROFILE,
        primary_keys=["symbol"],
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
    # Like the calendars, this lists whole markets rather than the configured symbols, so it is off
    # by default. A symbol is only unique within its market, so the market is part of the key.
    "symbol_list": FinageEndpointConfig(
        name="symbol_list",
        path="/symbol-list/{market}",
        kind=FinageEndpointKind.SYMBOL_LIST,
        primary_keys=["market", "symbol"],
        markets=SYMBOL_LIST_MARKETS,
        should_sync_default=False,
    ),
    # Forex and crypto need their own symbol fields, which are optional, so these are off by default.
    "forex_last_quote": FinageEndpointConfig(
        name="forex_last_quote",
        path="/last/forex/{symbol}",
        kind=FinageEndpointKind.POINT_IN_TIME,
        primary_keys=["symbol"],
        asset_class=FinageAssetClass.FOREX,
        should_sync_default=False,
    ),
    "forex_aggregates": FinageEndpointConfig(
        name="forex_aggregates",
        path="/agg/forex/{symbol}/{multiplier}/{timespan}/{from_date}/{to_date}",
        kind=FinageEndpointKind.AGGREGATE,
        primary_keys=["symbol", "t"],
        asset_class=FinageAssetClass.FOREX,
        partition_key="date",
        # The stock and forex docs disagree on whether `date_format` defaults to a timestamp or a
        # datetime string. `t` is the partition key, so pin the timestamp rather than guess.
        extra_params={"date_format": "ts"},
        should_sync_default=False,
    ),
    "crypto_last_trade": FinageEndpointConfig(
        name="crypto_last_trade",
        path="/last/crypto/{symbol}",
        kind=FinageEndpointKind.POINT_IN_TIME,
        primary_keys=["symbol"],
        asset_class=FinageAssetClass.CRYPTO,
        should_sync_default=False,
    ),
    "crypto_aggregates": FinageEndpointConfig(
        name="crypto_aggregates",
        path="/agg/crypto/{symbol}/{multiplier}/{timespan}/{from_date}/{to_date}",
        kind=FinageEndpointKind.AGGREGATE,
        primary_keys=["symbol", "t"],
        asset_class=FinageAssetClass.CRYPTO,
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
