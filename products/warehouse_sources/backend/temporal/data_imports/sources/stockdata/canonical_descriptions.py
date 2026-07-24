"""Canonical, documentation-sourced descriptions for StockData.org endpoints and columns.

Sourced from the official StockData.org API documentation (https://www.stockdata.org/documentation).
Keyed by the endpoint names in `settings.py` `STOCKDATA_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_DOCS_URL = "https://www.stockdata.org/documentation"

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "news": {
        "description": "Financial and market news articles with identified entities and per-entity sentiment scores.",
        "docs_url": _DOCS_URL,
        "columns": {
            "uuid": "Unique identifier of the article. Guaranteed unique per article.",
            "title": "Title of the article.",
            "description": "Meta description of the article.",
            "keywords": "Meta keywords of the article.",
            "snippet": "The first 60 characters of the article body.",
            "url": "URL of the article.",
            "image_url": "URL of the article's featured image.",
            "language": "Language of the article's source.",
            "published_at": "UTC datetime the article was published (ISO 8601).",
            "source": "Domain of the article's source.",
            "relevance_score": "Relevance score based on the search parameter; null when no search was used.",
            "entities": "Entities (symbols) identified in the article, each with match score, sentiment score, and highlighted text.",
            "similar": "Similar articles grouped with this one.",
        },
    },
    "quote": {
        "description": "Latest price and trading-day snapshot per symbol.",
        "docs_url": _DOCS_URL,
        "columns": {
            "ticker": "Ticker symbol of the instrument.",
            "name": "Name of the company or instrument.",
            "exchange_short": "Short code of the exchange the instrument trades on.",
            "exchange_long": "Full name of the exchange the instrument trades on.",
            "mic_code": "Market identifier code (MIC) of the exchange.",
            "currency": "Currency the price is quoted in.",
            "price": "Latest trade price.",
            "day_high": "Highest price of the current trading day.",
            "day_low": "Lowest price of the current trading day.",
            "day_open": "Opening price of the current trading day.",
            "52_week_high": "Highest price over the trailing 52 weeks.",
            "52_week_low": "Lowest price over the trailing 52 weeks.",
            "market_cap": "Market capitalization of the instrument.",
            "previous_close_price": "Closing price of the previous trading day.",
            "previous_close_price_time": "Datetime of the previous close.",
            "day_change": "Price change over the current trading day.",
            "volume": "Trading volume of the current trading day.",
            "is_extended_hours_price": "Whether the price was captured during extended trading hours.",
            "last_trade_time": "Datetime of the last executed trade.",
        },
    },
    "eod": {
        "description": "End-of-day (daily OHLCV) stock prices per symbol.",
        "docs_url": _DOCS_URL,
        "columns": {
            "date": "UTC datetime of the end-of-day data point (ISO 8601).",
            "ticker": "Ticker symbol of the instrument.",
            "open": "Opening price of the trading day.",
            "high": "Highest price reached during the trading day.",
            "low": "Lowest price reached during the trading day.",
            "close": "Closing price of the trading day.",
            "volume": "Trading volume of the day.",
        },
    },
    "intraday": {
        "description": "Intraday (hourly OHLCV) stock prices per symbol.",
        "docs_url": _DOCS_URL,
        "columns": {
            "date": "UTC datetime of the intraday data point (ISO 8601).",
            "ticker": "Ticker symbol of the instrument.",
            "open": "Opening price of the interval.",
            "high": "Highest price reached during the interval.",
            "low": "Lowest price reached during the interval.",
            "close": "Closing price of the interval.",
            "volume": "Trading volume of the interval.",
            "is_extended_hours": "Whether the data point falls within extended trading hours.",
        },
    },
    "dividends": {
        "description": "Historical dividend payouts per symbol.",
        "docs_url": _DOCS_URL,
        "columns": {
            "ticker": "Ticker symbol of the instrument.",
            "date": "Date the dividend was paid (YYYY-MM-DD).",
            "amount": "Dividend amount paid per share.",
        },
    },
    "splits": {
        "description": "Historical stock splits per symbol.",
        "docs_url": _DOCS_URL,
        "columns": {
            "ticker": "Ticker symbol of the instrument.",
            "date": "Date the stock split took effect (YYYY-MM-DD).",
            "numerator": "Numerator of the split ratio.",
            "denominator": "Denominator of the split ratio.",
            "ratio": 'Split ratio as a string (e.g. "2:1").',
        },
    },
}
