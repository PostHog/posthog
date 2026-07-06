from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

DOCS_URL = "https://exchangeratesapi.io/documentation/"

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "symbols": {
        "description": "Reference catalog of every currency the Exchange Rates API supports, as one row per currency.",
        "docs_url": DOCS_URL,
        "columns": {
            "code": "Three-letter ISO 4217 currency code (e.g. USD, GBP, JPY).",
            "name": "Human-readable currency name (e.g. United States Dollar).",
        },
    },
    "latest": {
        "description": "The most recent available exchange rate for each currency against the base currency, as one row per currency.",
        "docs_url": DOCS_URL,
        "columns": {
            "base": "Base currency the rates are quoted against (EUR on the free plan).",
            "currency": "Three-letter ISO 4217 code of the quoted currency.",
            "rate": "Exchange rate: units of `currency` per one unit of `base`.",
            "date": "Date the rates apply to (YYYY-MM-DD).",
            "timestamp": "Unix timestamp of when the rates were last updated.",
        },
    },
    "timeseries": {
        "description": "Daily historical exchange rates per currency over a requested date range, normalized to one row per (base, currency, date). Requests are chunked into 365-day windows.",
        "docs_url": DOCS_URL,
        "columns": {
            "base": "Base currency the rates are quoted against (EUR on the free plan).",
            "currency": "Three-letter ISO 4217 code of the quoted currency.",
            "rate": "Exchange rate for that day: units of `currency` per one unit of `base`.",
            "date": "Value date of the rate (YYYY-MM-DD).",
        },
    },
}
