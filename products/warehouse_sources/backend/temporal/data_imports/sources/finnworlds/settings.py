from dataclasses import dataclass, field
from enum import StrEnum
from typing import Optional


class ResponseMode(StrEnum):
    """How rows are extracted from a Finnworlds JSON response.

    Finnworlds wraps almost everything in ``{"status": ..., "result": {"basics": {...}, "output": ...}}``,
    but ``output`` is sometimes a named array, sometimes a bare list, and sometimes a single flat object.
    A handful of endpoints break the envelope entirely (e.g. SEC filings keep the array at the top level).
    These shapes are taken from the public docs and have not been curl-verified end to end, so the
    extractor degrades to an empty row set when the documented path is absent.
    """

    # result.output[<data_key>] is a list of records (fundamentals, dividends, splits, OHLC).
    OUTPUT_ARRAY = "output_array"
    # result.output is a single flat object → emitted as one row (financial ratios, company info).
    OUTPUT_OBJECT = "output_object"
    # result.output is itself a bare list of records (bond yields).
    OUTPUT_BARE = "output_bare"
    # result[<data_key>] is a list of records (analyst/company ratings live under result.analysts).
    RESULT_KEY = "result_key"
    # <data_key> is a top-level list, outside the result envelope (SEC filings).
    TOP_LEVEL = "top_level"


@dataclass
class FinnworldsEndpointConfig:
    name: str  # warehouse table name (and ExternalDataSchema.name)
    path: str  # API path segment under https://api.finnworlds.com/api/v1/
    response_mode: ResponseMode
    data_key: Optional[str] = None  # array/object key for OUTPUT_ARRAY / RESULT_KEY / TOP_LEVEL
    # Most endpoints return data for a single identifier per call, so a full sync fans out over the
    # user's ticker list. Endpoints that return a global list (bond yields) set this False.
    requires_ticker: bool = True
    # Inject result.basics.period into each row so fundamentals from different reporting periods don't
    # collide on the (ticker, period, date) primary key.
    include_period: bool = False
    # Nested object keys whose contents are merged up into the row before primary keys are read
    # (e.g. company ratings nest the rating under a "rating" object).
    flatten_keys: list[str] = field(default_factory=list)
    primary_keys: list[str] = field(default_factory=lambda: ["ticker"])
    partition_key: Optional[str] = None  # stable date field for datetime partitioning
    should_sync_default: bool = True


FINNWORLDS_ENDPOINTS: dict[str, FinnworldsEndpointConfig] = {
    "company_information": FinnworldsEndpointConfig(
        name="company_information",
        path="information",
        response_mode=ResponseMode.OUTPUT_OBJECT,
        primary_keys=["ticker"],
    ),
    "income_statements": FinnworldsEndpointConfig(
        name="income_statements",
        path="incomestatements",
        response_mode=ResponseMode.OUTPUT_ARRAY,
        data_key="income_statement",
        include_period=True,
        primary_keys=["ticker", "period", "date"],
        partition_key="date",
    ),
    "balance_sheets": FinnworldsEndpointConfig(
        name="balance_sheets",
        path="balancesheets",
        response_mode=ResponseMode.OUTPUT_ARRAY,
        data_key="balance_sheet",
        include_period=True,
        primary_keys=["ticker", "period", "date"],
        partition_key="date",
    ),
    "cash_flows": FinnworldsEndpointConfig(
        name="cash_flows",
        path="cashflows",
        response_mode=ResponseMode.OUTPUT_ARRAY,
        data_key="cash_flow",
        include_period=True,
        primary_keys=["ticker", "period", "date"],
        partition_key="date",
    ),
    "financial_ratios": FinnworldsEndpointConfig(
        name="financial_ratios",
        path="financialratios",
        response_mode=ResponseMode.OUTPUT_OBJECT,
        primary_keys=["ticker", "date"],
        partition_key="date",
    ),
    "dividends": FinnworldsEndpointConfig(
        name="dividends",
        path="dividends",
        response_mode=ResponseMode.OUTPUT_ARRAY,
        data_key="dividends",
        primary_keys=["ticker", "date"],
        partition_key="date",
    ),
    "stock_splits": FinnworldsEndpointConfig(
        name="stock_splits",
        path="stocksplits",
        response_mode=ResponseMode.OUTPUT_ARRAY,
        data_key="stocksplits",
        primary_keys=["ticker", "date"],
        partition_key="date",
    ),
    "stock_prices": FinnworldsEndpointConfig(
        name="stock_prices",
        path="historicalcandlestick",
        response_mode=ResponseMode.OUTPUT_ARRAY,
        data_key="daily_stock_data",
        primary_keys=["ticker", "date"],
        partition_key="date",
    ),
    "company_ratings": FinnworldsEndpointConfig(
        name="company_ratings",
        path="companyratings",
        response_mode=ResponseMode.RESULT_KEY,
        data_key="analysts",
        flatten_keys=["rating"],
        # No single natural key — a ticker has many analysts, each with dated ratings.
        primary_keys=["ticker", "analyst_name", "analyst_firm", "date_rating"],
        partition_key="date_rating",
    ),
    "sec_filings": FinnworldsEndpointConfig(
        name="sec_filings",
        path="secfilings",
        response_mode=ResponseMode.TOP_LEVEL,
        data_key="sec_filings",
        # The EDGAR index URL is the most stable unique value per filing.
        primary_keys=["ticker", "url"],
        partition_key="date",
    ),
    "bond_yields": FinnworldsEndpointConfig(
        name="bond_yields",
        path="bonds",
        response_mode=ResponseMode.OUTPUT_BARE,
        requires_ticker=False,
        primary_keys=["country", "type", "datetime"],
        partition_key="datetime",
        should_sync_default=False,
    ),
}

ENDPOINTS = tuple(FINNWORLDS_ENDPOINTS.keys())
