from dataclasses import field
from typing import Literal

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SortMode
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Alpha Vantage exposes every dataset through a single /query endpoint selected by a `function`
# parameter. Each function returns a bespoke JSON shape, so endpoints are grouped by a `kind` that
# tells the transport how to parse and normalize the response into flat rows.
#
# No function paginates. Most carry no server-side cursor either (no `updated_after`/`since` filter),
# so they are full refresh only, and re-pulled rows dedupe on the primary key at merge time.
# NEWS_SENTIMENT (`time_from`) and INSIDER_TRANSACTIONS (`from`) are the two that do filter.
ParseKind = Literal[
    "economic",
    "estimates",
    "etf_profile",
    "time_series",
    "quote",
    "overview",
    "reports",
    "earnings",
    "corporate_action",
    "listing",
    "news",
    "calendar",
    "insider",
    "institutional",
]


@frozen
class AlphaVantageEndpointConfig:
    name: str
    # The Alpha Vantage `function` query-param value (e.g. TIME_SERIES_DAILY).
    function: str
    kind: ParseKind
    # Unique across the whole table. Every per-symbol endpoint fans out over the user's configured
    # symbols, so `symbol` is always part of the key.
    primary_keys: list[str]
    # A stable date column used for datetime partitioning. Never a mutable field. None for snapshot
    # tables (latest quote, company overview) and for the low-volume corporate-action and listing
    # tables, where monthly partitions would hold a handful of rows each.
    partition_key: str | None = None
    description: str | None = None
    # Whether the table is selected for sync by default in the UI. Kept modest by default because the
    # free tier is rate limited (~25 requests/day), and each selected table costs one request/symbol.
    should_sync_default: bool = True
    # Advertised cursor options. Only set where the function takes a server-side timestamp filter;
    # an empty list means the table is full refresh only. Never append-capable, because those filters
    # are coarser than the stored cursor, so every run re-delivers the rows on the boundary and only
    # a merge can dedupe them.
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # The order rows actually arrive in, which the pipeline's cursor watermark trusts.
    sort_mode: SortMode | None = "asc"
    # Fixed query params beyond function/symbol/apikey, e.g. the finest `interval` a series offers.
    extra_params: dict[str, str] = field(default_factory=dict)
    # Each value is one request with `maturity=<value>`, tagged onto its rows as a `maturity` column.
    maturities: tuple[str, ...] = ()


ALPHA_VANTAGE_ENDPOINTS: dict[str, AlphaVantageEndpointConfig] = {
    "time_series_daily": AlphaVantageEndpointConfig(
        name="time_series_daily",
        function="TIME_SERIES_DAILY",
        kind="time_series",
        primary_keys=["symbol", "date"],
        partition_key="date",
        description="Daily open/high/low/close/volume bars per symbol (20+ years of history). Full refresh.",
    ),
    "time_series_daily_adjusted": AlphaVantageEndpointConfig(
        name="time_series_daily_adjusted",
        function="TIME_SERIES_DAILY_ADJUSTED",
        kind="time_series",
        primary_keys=["symbol", "date"],
        partition_key="date",
        description="Daily bars per symbol with split/dividend-adjusted close, dividend amount, and split coefficient (25+ years of history). Requires a paid Alpha Vantage plan. Full refresh.",
        should_sync_default=False,
    ),
    "time_series_weekly": AlphaVantageEndpointConfig(
        name="time_series_weekly",
        function="TIME_SERIES_WEEKLY",
        kind="time_series",
        primary_keys=["symbol", "date"],
        partition_key="date",
        description="Weekly open/high/low/close/volume bars per symbol. Full refresh.",
        should_sync_default=False,
    ),
    "time_series_monthly": AlphaVantageEndpointConfig(
        name="time_series_monthly",
        function="TIME_SERIES_MONTHLY",
        kind="time_series",
        primary_keys=["symbol", "date"],
        partition_key="date",
        description="Monthly open/high/low/close/volume bars per symbol. Full refresh.",
        should_sync_default=False,
    ),
    "global_quote": AlphaVantageEndpointConfig(
        name="global_quote",
        function="GLOBAL_QUOTE",
        kind="quote",
        primary_keys=["symbol"],
        description="Latest price and trading-day snapshot per symbol (one row per symbol). Full refresh.",
    ),
    "company_overview": AlphaVantageEndpointConfig(
        name="company_overview",
        function="OVERVIEW",
        kind="overview",
        primary_keys=["symbol"],
        description="Company fundamentals, ratios, and descriptive fields per symbol (one row per symbol). Full refresh.",
    ),
    "income_statement": AlphaVantageEndpointConfig(
        name="income_statement",
        function="INCOME_STATEMENT",
        kind="reports",
        primary_keys=["symbol", "fiscalDateEnding", "report_type"],
        partition_key="fiscalDateEnding",
        description="Annual and quarterly income statements per symbol. One row per report. Full refresh.",
    ),
    "balance_sheet": AlphaVantageEndpointConfig(
        name="balance_sheet",
        function="BALANCE_SHEET",
        kind="reports",
        primary_keys=["symbol", "fiscalDateEnding", "report_type"],
        partition_key="fiscalDateEnding",
        description="Annual and quarterly balance sheets per symbol. One row per report. Full refresh.",
    ),
    "cash_flow": AlphaVantageEndpointConfig(
        name="cash_flow",
        function="CASH_FLOW",
        kind="reports",
        primary_keys=["symbol", "fiscalDateEnding", "report_type"],
        partition_key="fiscalDateEnding",
        description="Annual and quarterly cash-flow statements per symbol. One row per report. Full refresh.",
    ),
    "earnings": AlphaVantageEndpointConfig(
        name="earnings",
        function="EARNINGS",
        kind="earnings",
        primary_keys=["symbol", "fiscalDateEnding", "report_type"],
        partition_key="fiscalDateEnding",
        description="Annual and quarterly reported EPS (with estimates and surprise) per symbol. One row per report. Full refresh.",
    ),
    "dividends": AlphaVantageEndpointConfig(
        name="dividends",
        function="DIVIDENDS",
        kind="corporate_action",
        primary_keys=["symbol", "ex_dividend_date"],
        description="Historical and declared dividend distributions per symbol. One row per distribution. Full refresh.",
        should_sync_default=False,
    ),
    "splits": AlphaVantageEndpointConfig(
        name="splits",
        function="SPLITS",
        kind="corporate_action",
        primary_keys=["symbol", "effective_date"],
        description="Historical stock split events per symbol. One row per split. Full refresh.",
        should_sync_default=False,
    ),
    "insider_transactions": AlphaVantageEndpointConfig(
        name="insider_transactions",
        function="INSIDER_TRANSACTIONS",
        kind="insider",
        # Alpha Vantage issues no transaction id, so the filing's own fields are the only identity
        # available, and two identical filings on one day collapse into a single row.
        primary_keys=[
            "symbol",
            "transaction_date",
            "executive",
            "security_type",
            "acquisition_or_disposal",
            "shares",
            "share_price",
        ],
        partition_key="transaction_date",
        incremental_fields=[incremental_field("transaction_date", IncrementalFieldType.Date)],
        # Newest filing first, and the function takes no sort parameter.
        sort_mode="desc",
        description="Insider buy and sell transactions by executives, directors and other key stakeholders per symbol. One row per filing. Supports incremental sync.",
        should_sync_default=False,
    ),
    "institutional_holdings": AlphaVantageEndpointConfig(
        name="institutional_holdings",
        function="INSTITUTIONAL_HOLDINGS",
        kind="institutional",
        # `holder_name` repeats within a symbol, because separate filers share a display name and one
        # name can appear twice for the same reporting date. The position makes the key unique.
        primary_keys=["symbol", "holder_name", "last_reported", "shares_held"],
        description="Institutional holder positions per symbol, each row carrying the symbol's overall institutional ownership totals. Roughly 4,000 holders per symbol. Full refresh.",
        should_sync_default=False,
    ),
    "news_sentiment": AlphaVantageEndpointConfig(
        name="news_sentiment",
        function="NEWS_SENTIMENT",
        kind="news",
        primary_keys=["symbol", "url"],
        partition_key="time_published",
        incremental_fields=[incremental_field("time_published")],
        # Each symbol is a separate oldest-first request series, so the rows of a run have no single order.
        sort_mode=None,
        description="Market news articles mentioning each symbol, with article-level and per-ticker sentiment scores. One row per article per symbol. Supports incremental sync.",
        should_sync_default=False,
    ),
    "listing_status": AlphaVantageEndpointConfig(
        name="listing_status",
        function="LISTING_STATUS",
        kind="listing",
        # Not symbol-scoped, so `symbol` alone is not enough: a delisted ticker can later be reused by
        # a different active company, and the same ticker can be delisted more than once.
        primary_keys=["symbol", "status", "ipoDate"],
        description="Every active and delisted US stock and ETF with its exchange, asset type, and IPO/delisting dates. Covers the whole market rather than the configured symbols. Full refresh.",
    ),
    "earnings_calendar": AlphaVantageEndpointConfig(
        name="earnings_calendar",
        function="EARNINGS_CALENDAR",
        kind="calendar",
        primary_keys=["symbol", "reportDate", "fiscalDateEnding"],
        description="Company earnings scheduled over the next 12 months, with the consensus EPS estimate. Covers the whole market rather than the configured symbols. Full refresh.",
    ),
    "shares_outstanding": AlphaVantageEndpointConfig(
        name="shares_outstanding",
        function="SHARES_OUTSTANDING",
        kind="corporate_action",
        primary_keys=["symbol", "date"],
        description="Quarterly diluted and basic shares outstanding per symbol. One row per quarter. Full refresh.",
        should_sync_default=False,
    ),
    "earnings_estimates": AlphaVantageEndpointConfig(
        name="earnings_estimates",
        function="EARNINGS_ESTIMATES",
        kind="estimates",
        # A fiscal year and its last fiscal quarter end on the same date, so `horizon` is part of the key.
        primary_keys=["symbol", "date", "horizon"],
        partition_key="date",
        description="Annual and quarterly analyst EPS and revenue estimates per symbol, with analyst counts and revision history. One row per period. Full refresh.",
        should_sync_default=False,
    ),
    "etf_profile": AlphaVantageEndpointConfig(
        name="etf_profile",
        function="ETF_PROFILE",
        kind="etf_profile",
        primary_keys=["symbol"],
        description="ETF metrics (net assets, expense ratio, turnover) with the sector allocation and holdings per symbol (one row per ETF). Full refresh.",
        should_sync_default=False,
    ),
    "real_gdp": AlphaVantageEndpointConfig(
        name="real_gdp",
        function="REAL_GDP",
        kind="economic",
        primary_keys=["date"],
        extra_params={"interval": "quarterly"},
        description="Quarterly real GDP of the United States. Not tied to the configured symbols. Full refresh.",
        should_sync_default=False,
    ),
    "cpi": AlphaVantageEndpointConfig(
        name="cpi",
        function="CPI",
        kind="economic",
        primary_keys=["date"],
        extra_params={"interval": "monthly"},
        description="Monthly consumer price index of the United States. Not tied to the configured symbols. Full refresh.",
        should_sync_default=False,
    ),
    "treasury_yield": AlphaVantageEndpointConfig(
        name="treasury_yield",
        function="TREASURY_YIELD",
        kind="economic",
        primary_keys=["maturity", "date"],
        partition_key="date",
        extra_params={"interval": "daily"},
        maturities=("3month", "2year", "5year", "7year", "10year", "30year"),
        description="Daily US treasury yields for the 3-month, 2-, 5-, 7-, 10- and 30-year maturities (one request per maturity). Not tied to the configured symbols. Full refresh.",
        should_sync_default=False,
    ),
    "federal_funds_rate": AlphaVantageEndpointConfig(
        name="federal_funds_rate",
        function="FEDERAL_FUNDS_RATE",
        kind="economic",
        primary_keys=["date"],
        extra_params={"interval": "daily"},
        description="Daily effective federal funds rate of the United States. Not tied to the configured symbols. Full refresh.",
        should_sync_default=False,
    ),
    "unemployment": AlphaVantageEndpointConfig(
        name="unemployment",
        function="UNEMPLOYMENT",
        kind="economic",
        primary_keys=["date"],
        description="Monthly unemployment rate of the United States. Not tied to the configured symbols. Full refresh.",
        should_sync_default=False,
    ),
}

ENDPOINTS = tuple(ALPHA_VANTAGE_ENDPOINTS.keys())
