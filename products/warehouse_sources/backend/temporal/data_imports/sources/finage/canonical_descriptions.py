"""Canonical, documentation-sourced descriptions for Finage endpoints and columns.

Sourced from the official Finage API reference (https://finage.co.uk/docs). Keyed by the endpoint
names in `settings.py` `FINAGE_ENDPOINTS`, which match the `ExternalDataSchema.name` of a synced
Finage table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "last_quote": {
        "description": "The latest bid/ask quote for each tracked stock symbol.",
        "docs_url": "https://finage.co.uk/docs/api/stock-last-quote",
        "columns": {
            "symbol": "Ticker symbol the quote is for (e.g. AAPL).",
            "ask": "Most recent ask price.",
            "bid": "Most recent bid price.",
            "asize": "Size available at the ask price.",
            "bsize": "Size available at the bid price.",
            "timestamp": "Unix epoch (milliseconds) at which the quote was last updated.",
        },
    },
    "last_trade": {
        "description": "The latest executed trade for each tracked stock symbol.",
        "docs_url": "https://finage.co.uk/docs/api/stock-last-trade",
        "columns": {
            "symbol": "Ticker symbol the trade is for (e.g. AAPL).",
            "price": "Price the last trade executed at.",
            "size": "Number of shares in the last trade.",
            "timestamp": "Unix epoch (milliseconds) at which the trade occurred.",
        },
    },
    "aggregates": {
        "description": "Historical daily OHLCV bars for each tracked stock symbol.",
        "docs_url": "https://finage.co.uk/docs/api/stock-market-aggregates-api",
        "columns": {
            "symbol": "Ticker symbol the bar is for (e.g. AAPL).",
            "date": "ISO date (YYYY-MM-DD) of the bar, derived from `t`. Used as the partition key.",
            "o": "Open price for the bar.",
            "h": "Highest price during the bar.",
            "l": "Lowest price during the bar.",
            "c": "Close price for the bar.",
            "v": "Trading volume during the bar.",
            "t": "Unix epoch (milliseconds) at the start of the bar.",
        },
    },
}
