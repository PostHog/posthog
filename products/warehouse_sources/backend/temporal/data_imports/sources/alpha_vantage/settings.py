import dataclasses
from typing import Literal

# Alpha Vantage exposes every dataset through a single /query endpoint selected by a `function`
# parameter. Each function returns a bespoke JSON shape, so endpoints are grouped by a `kind` that
# tells the transport how to parse and normalize the response into flat rows.
#
# There is no pagination and no server-side incremental cursor (no `updated_after`/`since` filter),
# so every table is full refresh only. Time-series data is naturally append-only by date, so
# re-pulled rows dedupe on the primary key at merge time.
ParseKind = Literal["time_series", "quote", "overview", "reports", "earnings"]


@dataclasses.dataclass
class AlphaVantageEndpointConfig:
    name: str
    # The Alpha Vantage `function` query-param value (e.g. TIME_SERIES_DAILY).
    function: str
    kind: ParseKind
    # Unique across the whole table. Every endpoint fans out over the user's configured symbols, so
    # the injected `symbol` is always part of the key.
    primary_keys: list[str]
    # A stable date column used for datetime partitioning. Never a mutable field. None for snapshot
    # tables (latest quote, company overview) that hold one row per symbol.
    partition_key: str | None = None
    description: str | None = None
    # Whether the table is selected for sync by default in the UI. Kept modest by default because the
    # free tier is rate limited (~25 requests/day), and each selected table costs one request/symbol.
    should_sync_default: bool = True


ALPHA_VANTAGE_ENDPOINTS: dict[str, AlphaVantageEndpointConfig] = {
    "time_series_daily": AlphaVantageEndpointConfig(
        name="time_series_daily",
        function="TIME_SERIES_DAILY",
        kind="time_series",
        primary_keys=["symbol", "date"],
        partition_key="date",
        description="Daily open/high/low/close/volume bars per symbol (20+ years of history). Full refresh.",
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
}

ENDPOINTS = tuple(ALPHA_VANTAGE_ENDPOINTS.keys())
