from dataclasses import field
from typing import Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Financial Modeling Prep "stable" API host. The legacy `/api/v3/` paths still work, but every
# endpoint here is expressed relative to the stable base. Auth is an `apikey` query param appended
# to every request (see financial_modelling.py).
FINANCIAL_MODELLING_BASE_URL = "https://financialmodelingprep.com/stable"

# Endpoints that accept `limit` cap it at 1000 and offer no page cursor, so ask for the maximum.
# Left off, FMP falls back to a handful of records and silently truncates the symbol's history.
FINANCIAL_MODELLING_MAX_LIMIT = "1000"

# 13F endpoints are scoped to one calendar quarter per request, so a symbol's series is built by
# asking for each quarter in turn. Eight covers two years without multiplying the request count
# past what a small key can afford.
FINANCIAL_MODELLING_QUARTERS_LOOKBACK = 8


@frozen
class FinancialModellingEndpointConfig:
    name: str
    # Path under FINANCIAL_MODELLING_BASE_URL (no leading slash).
    path: str
    primary_keys: list[str]
    # When True, the endpoint is symbol-keyed: we issue one request per configured symbol and inject
    # the symbol onto each row. When False, the endpoint is market-wide (a single request per sync).
    fan_out_over_symbols: bool = False
    # Stable field used to partition the Delta table. Must be a value that never changes for a row
    # (a fiscal-period or trading `date`), never `updated_at`/`lastSeen`.
    partition_key: Optional[str] = None
    # Server-side incremental cursor options surfaced in the schema picker. Only populated for
    # endpoints that honor a genuine `from`/`to` date filter.
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # True only when the endpoint actually filters server-side on `from`/`to`. Drives incremental sync.
    supports_date_window: bool = False
    # Extra static query params (e.g. statement period).
    extra_params: dict[str, str] = field(default_factory=dict)
    # Some endpoints historically wrapped their array under a key (e.g. {"symbol": ..., "historical": [...]}).
    # When set, rows are read from data[response_key] if the response is an object rather than a bare array.
    response_key: Optional[str] = None
    # First incremental sync is bounded to the last N days so we don't pull unbounded history in one go.
    default_lookback_days: Optional[int] = None
    # Set on endpoints that only answer for one calendar quarter at a time: the fan-out issues one
    # request per symbol per quarter, walking back this many completed quarters.
    quarters_lookback: Optional[int] = None
    should_sync_default: bool = True


def _date_incremental_fields() -> list[IncrementalField]:
    return [
        {
            "label": "date",
            "type": IncrementalFieldType.Date,
            "field": "date",
            "field_type": IncrementalFieldType.Date,
        }
    ]


FINANCIAL_MODELLING_ENDPOINTS: dict[str, FinancialModellingEndpointConfig] = {
    # Reference catalog of every tradable symbol FMP knows about. One bounded request, no symbol
    # required. Full refresh — there is no server-side change cursor.
    "stock_list": FinancialModellingEndpointConfig(
        name="stock_list",
        path="stock-list",
        primary_keys=["symbol"],
    ),
    # Company profile (sector, industry, market cap, description, ...). One request per symbol.
    # Full refresh — no updated_at cursor exposed by the API.
    "company_profiles": FinancialModellingEndpointConfig(
        name="company_profiles",
        path="profile",
        primary_keys=["symbol"],
        fan_out_over_symbols=True,
    ),
    # Annual income statements per symbol. Full refresh; rows are keyed by the fiscal-period `date`.
    "income_statements": FinancialModellingEndpointConfig(
        name="income_statements",
        path="income-statement",
        primary_keys=["symbol", "date", "period"],
        fan_out_over_symbols=True,
        partition_key="date",
        extra_params={"period": "annual"},
    ),
    "balance_sheet_statements": FinancialModellingEndpointConfig(
        name="balance_sheet_statements",
        path="balance-sheet-statement",
        primary_keys=["symbol", "date", "period"],
        fan_out_over_symbols=True,
        partition_key="date",
        extra_params={"period": "annual"},
    ),
    "cash_flow_statements": FinancialModellingEndpointConfig(
        name="cash_flow_statements",
        path="cash-flow-statement",
        primary_keys=["symbol", "date", "period"],
        fan_out_over_symbols=True,
        partition_key="date",
        extra_params={"period": "annual"},
    ),
    # FMP's headline per-company metric set (market cap, enterprise value, returns, yields) per
    # fiscal period. Takes `limit` and `period` but no `from`/`to`, so it is full refresh.
    "key_metrics": FinancialModellingEndpointConfig(
        name="key_metrics",
        path="key-metrics",
        primary_keys=["symbol", "date", "period"],
        fan_out_over_symbols=True,
        partition_key="date",
        extra_params={"period": "annual", "limit": FINANCIAL_MODELLING_MAX_LIMIT},
    ),
    # Valuation, profitability, liquidity and leverage ratios per fiscal period. Same shape and
    # parameters as key_metrics.
    "ratios": FinancialModellingEndpointConfig(
        name="ratios",
        path="ratios",
        primary_keys=["symbol", "date", "period"],
        fan_out_over_symbols=True,
        partition_key="date",
        extra_params={"period": "annual", "limit": FINANCIAL_MODELLING_MAX_LIMIT},
    ),
    # Trailing-twelve-month snapshot of the key metrics. One always-current row per symbol with no
    # fiscal `date`, so it is keyed on the symbol alone and replaced in full on every sync.
    "key_metrics_ttm": FinancialModellingEndpointConfig(
        name="key_metrics_ttm",
        path="key-metrics-ttm",
        primary_keys=["symbol"],
        fan_out_over_symbols=True,
    ),
    # Trailing-twelve-month snapshot of the ratios. Same one-row-per-symbol shape as key_metrics_ttm.
    "ratios_ttm": FinancialModellingEndpointConfig(
        name="ratios_ttm",
        path="ratios-ttm",
        primary_keys=["symbol"],
        fan_out_over_symbols=True,
    ),
    # Actual dividend history per symbol (ex-date, record, payment, amount, yield). Unlike the
    # market-wide dividends_calendar it takes no `from`/`to`, so it is full refresh.
    "dividends": FinancialModellingEndpointConfig(
        name="dividends",
        path="dividends",
        primary_keys=["symbol", "date"],
        fan_out_over_symbols=True,
        partition_key="date",
        extra_params={"limit": FINANCIAL_MODELLING_MAX_LIMIT},
    ),
    # Reported earnings per symbol: actual vs estimated EPS and revenue. The market-wide
    # earnings_calendar covers the forward schedule; this is the per-symbol history behind it.
    "earnings": FinancialModellingEndpointConfig(
        name="earnings",
        path="earnings",
        primary_keys=["symbol", "date"],
        fan_out_over_symbols=True,
        partition_key="date",
        extra_params={"limit": FINANCIAL_MODELLING_MAX_LIMIT},
    ),
    # End-of-day OHLCV history per symbol. Honors `from`/`to`, so this is the one symbol-keyed
    # endpoint we sync incrementally on the trading `date`.
    "historical_prices": FinancialModellingEndpointConfig(
        name="historical_prices",
        path="historical-price-full",
        primary_keys=["symbol", "date"],
        fan_out_over_symbols=True,
        partition_key="date",
        incremental_fields=_date_incremental_fields(),
        supports_date_window=True,
        # Stable bare-array responses need no unwrapping; the legacy shape nests under "historical".
        response_key="historical",
        default_lookback_days=365 * 5,
    ),
    # Market-wide earnings calendar. Honors `from`/`to`; incremental on the event `date`.
    "earnings_calendar": FinancialModellingEndpointConfig(
        name="earnings_calendar",
        path="earnings-calendar",
        primary_keys=["symbol", "date"],
        partition_key="date",
        incremental_fields=_date_incremental_fields(),
        supports_date_window=True,
        default_lookback_days=365 * 2,
    ),
    # Market-wide dividends calendar. Honors `from`/`to`; incremental on the ex-dividend `date`.
    "dividends_calendar": FinancialModellingEndpointConfig(
        name="dividends_calendar",
        path="dividends-calendar",
        primary_keys=["symbol", "date"],
        partition_key="date",
        incremental_fields=_date_incremental_fields(),
        supports_date_window=True,
        default_lookback_days=365 * 2,
    ),
    # Lookup resolving the exchange codes carried on stock_list and company_profiles. One bounded
    # market-wide request, no parameters.
    "available_exchanges": FinancialModellingEndpointConfig(
        name="available_exchanges",
        path="available-exchanges",
        primary_keys=["exchange"],
    ),
    # Lookup of every sector classification company_profiles can report.
    "available_sectors": FinancialModellingEndpointConfig(
        name="available_sectors",
        path="available-sectors",
        primary_keys=["sector"],
    ),
    # Lookup of every industry classification company_profiles can report.
    "available_industries": FinancialModellingEndpointConfig(
        name="available_industries",
        path="available-industries",
        primary_keys=["industry"],
    ),
    # Split history per symbol (split date and ratio). Needed to compare historical_prices across a
    # split. Takes `symbol` and `limit` but no `from`/`to`, so full refresh.
    "splits": FinancialModellingEndpointConfig(
        name="splits",
        path="splits",
        primary_keys=["symbol", "date"],
        fan_out_over_symbols=True,
        partition_key="date",
        extra_params={"limit": FINANCIAL_MODELLING_MAX_LIMIT},
    ),
    # Current market capitalization: one always-current row per symbol, so it is keyed on the symbol
    # alone and replaced in full on every sync (same shape as the TTM endpoints).
    "market_capitalization": FinancialModellingEndpointConfig(
        name="market_capitalization",
        path="market-capitalization",
        primary_keys=["symbol"],
        fan_out_over_symbols=True,
    ),
    # Daily market capitalization history per symbol. Honors `from`/`to`, so this syncs incrementally
    # on the observation `date`. `limit` still has to be sent: it defaults to 100 and would otherwise
    # truncate the window. The endpoint has no page cursor, so the first window must stay inside
    # `limit` rows — a wider one silently drops its oldest days, and the watermark then skips past
    # them forever.
    "historical_market_capitalization": FinancialModellingEndpointConfig(
        name="historical_market_capitalization",
        path="historical-market-capitalization",
        primary_keys=["symbol", "date"],
        fan_out_over_symbols=True,
        partition_key="date",
        incremental_fields=_date_incremental_fields(),
        supports_date_window=True,
        extra_params={"limit": FINANCIAL_MODELLING_MAX_LIMIT},
        default_lookback_days=365 * 2,
    ),
    # 13F institutional holdings summarized per symbol and quarter: how many institutions hold the
    # symbol, the share and value changes, and the ownership percentage. Off by default because it
    # costs one request per symbol per quarter, which a rate-limited key feels immediately.
    "institutional_positions_summary": FinancialModellingEndpointConfig(
        name="institutional_positions_summary",
        path="institutional-ownership/symbol-positions-summary",
        primary_keys=["symbol", "date"],
        fan_out_over_symbols=True,
        partition_key="date",
        quarters_lookback=FINANCIAL_MODELLING_QUARTERS_LOOKBACK,
        should_sync_default=False,
    ),
}

ENDPOINTS = tuple(FINANCIAL_MODELLING_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in FINANCIAL_MODELLING_ENDPOINTS.items()
}
