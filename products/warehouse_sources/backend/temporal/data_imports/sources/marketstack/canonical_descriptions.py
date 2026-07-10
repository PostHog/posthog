"""Canonical, documentation-sourced descriptions for Marketstack endpoints and columns.

Sourced from the official Marketstack API documentation (https://marketstack.com/documentation).
Keyed by the endpoint names in `settings.py` `MARKETSTACK_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_DOCS_URL = "https://marketstack.com/documentation"

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "eod": {
        "description": "End-of-day (daily OHLCV) stock prices per symbol, including adjusted prices, split factor, and dividend.",
        "docs_url": _DOCS_URL,
        "columns": {
            "date": "Exact UTC timestamp of the end-of-day data point (ISO 8601).",
            "symbol": "Stock ticker symbol of the instrument.",
            "exchange": "MIC identification of the exchange the data point is associated with.",
            "open": "Opening price of the trading day.",
            "high": "Highest price reached during the trading day.",
            "low": "Lowest price reached during the trading day.",
            "close": "Closing price of the trading day.",
            "volume": "Trading volume of the day.",
            "adj_open": "Split- and dividend-adjusted opening price.",
            "adj_high": "Split- and dividend-adjusted high price.",
            "adj_low": "Split- and dividend-adjusted low price.",
            "adj_close": "Split- and dividend-adjusted closing price.",
            "adj_volume": "Split- and dividend-adjusted trading volume.",
            "split_factor": "Split factor applied on this date (1.0 when no split).",
            "dividend": "Dividend paid on this date (0.0 when none).",
        },
    },
    "intraday": {
        "description": "Intraday (intra-day interval) stock prices per symbol.",
        "docs_url": _DOCS_URL,
        "columns": {
            "date": "Exact UTC timestamp of the intraday data point (ISO 8601).",
            "symbol": "Stock ticker symbol of the instrument.",
            "exchange": "MIC identification of the exchange the data point is associated with.",
            "open": "Opening price of the interval.",
            "high": "Highest price reached during the interval.",
            "low": "Lowest price reached during the interval.",
            "close": "Closing price of the interval.",
            "last": "Last executed trade price in the interval.",
            "volume": "Trading volume of the interval.",
        },
    },
    "splits": {
        "description": "Historical stock split factors per symbol.",
        "docs_url": _DOCS_URL,
        "columns": {
            "date": "Date the stock split took effect (YYYY-MM-DD).",
            "symbol": "Stock ticker symbol of the instrument.",
            "split_factor": "Split factor applied on this date (e.g. 4.0 for a 4-for-1 split).",
        },
    },
    "dividends": {
        "description": "Historical dividend payouts per symbol.",
        "docs_url": _DOCS_URL,
        "columns": {
            "date": "Date the dividend was paid (YYYY-MM-DD).",
            "symbol": "Stock ticker symbol of the instrument.",
            "dividend": "Dividend amount paid per share on this date.",
        },
    },
    "tickers": {
        "description": "Reference table of supported stock tickers with name, exchange, and EOD/intraday availability.",
        "docs_url": _DOCS_URL,
        "columns": {
            "name": "Full name of the company or instrument.",
            "symbol": "Stock ticker symbol of the instrument.",
            "has_intraday": "Whether intraday data is available for this ticker.",
            "has_eod": "Whether end-of-day data is available for this ticker.",
            "country": "Country the ticker is associated with (nullable).",
            "stock_exchange": "Nested exchange the ticker is listed on, including name, acronym, MIC, and country.",
        },
    },
    "exchanges": {
        "description": "Reference table of supported stock exchanges with codes, country, and timezone.",
        "docs_url": _DOCS_URL,
        "columns": {
            "name": "Name of the stock exchange.",
            "acronym": "Acronym of the stock exchange.",
            "mic": "Market Identifier Code (MIC) of the stock exchange.",
            "country": "Country the exchange is located in.",
            "country_code": "ISO 3166-1 alpha-2 code of the exchange's country.",
            "city": "City the exchange is located in.",
            "website": "Website URL of the exchange.",
            "timezone": "Nested timezone details of the exchange, including name and abbreviation.",
        },
    },
    "currencies": {
        "description": "Reference table of supported currencies.",
        "docs_url": _DOCS_URL,
        "columns": {
            "code": "ISO 4217 currency code.",
            "symbol": "Display symbol of the currency.",
            "name": "Name of the currency.",
        },
    },
    "timezones": {
        "description": "Reference table of supported timezones.",
        "docs_url": _DOCS_URL,
        "columns": {
            "timezone": "Name of the timezone (e.g. America/New_York).",
            "abbr": "Standard-time abbreviation of the timezone (e.g. EST).",
            "abbr_dst": "Daylight-saving-time abbreviation of the timezone (e.g. EDT).",
        },
    },
}
