"""Canonical, documentation-sourced descriptions for Marketstack endpoints and columns.

Sourced from the official Marketstack API documentation (https://marketstack.com/documentation).
Keyed by the endpoint names in `settings.py` `MARKETSTACK_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_DOCS_URL = "https://marketstack.com/documentation"
_DOCS_V2_URL = "https://marketstack.com/documentation_v2"

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
    "tickerinfo": {
        "description": "Extended company and listing information per ticker, including sector, industry, description, and key identifiers.",
        "docs_url": _DOCS_V2_URL,
        "columns": {
            "ticker": "Ticker symbol.",
            "name": "Company or instrument name.",
            "item_type": "Type of item (e.g. equity).",
            "sector": "Sector of the company.",
            "industry": "Industry of the company.",
            "exchange_code": "Exchange code.",
            "full_time_employees": "Number of full-time employees.",
            "ipo_date": "IPO date.",
            "date_founded": "Date founded.",
            "key_executives": "Key executives with name, function, salary, exercised options, and birth year.",
            "incorporation": "State or country of incorporation.",
            "start_fiscal": "Fiscal year start (MM-DD).",
            "end_fiscal": "Fiscal year end (MM-DD).",
            "previous_names": "Previous names of the company.",
            "stock_exchanges": "Exchanges the ticker is listed on.",
            "reporting_currency": "Reporting currency.",
            "website": "Company website.",
            "about": "Company description.",
        },
    },
    "companyratings": {
        "description": "Individual analyst buy/sell/hold ratings and price targets per ticker.",
        "docs_url": _DOCS_V2_URL,
        "columns": {
            "ticker": "Ticker symbol.",
            "company_name": "Name of the company.",
            "analyst_name": "Name of the analyst.",
            "analyst_firm": "Firm the analyst works for.",
            "analyst_role": "Role of the analyst.",
            "date_rating": "Date of the rating.",
            "target_date": "Date the price target applies to.",
            "price_target": "Price target set by the analyst.",
            "rated": "Rating given by the analyst (buy, sell, or hold).",
            "conclusion": "Conclusion of the rating.",
        },
    },
    "submissions": {
        "description": "Recent SEC filing submissions per company, one row per filing.",
        "docs_url": _DOCS_V2_URL,
        "columns": {
            "cik_code": "SEC Central Index Key of the filer (zero-padded).",
            "company_name": "Company name.",
            "accession_number": "Accession number of the filing.",
            "filing_date": "Date the filing was made.",
            "report_date": "Date of the reporting period.",
            "acceptance_date_time": "Time the SEC accepted the filing.",
            "form": "Filing form type (e.g. 10-K, 10-Q, 8-K).",
            "file_number": "SEC file number.",
            "primary_document": "File name of the primary document.",
            "primary_doc_description": "Description of the primary document.",
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
