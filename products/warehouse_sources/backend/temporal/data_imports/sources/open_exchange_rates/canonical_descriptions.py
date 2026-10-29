from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

DOCS_URL = "https://docs.openexchangerates.org/reference/api-introduction"

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "currencies": {
        "description": "Reference catalog of every currency Open Exchange Rates supports, as one row per currency.",
        "docs_url": "https://docs.openexchangerates.org/reference/currencies-json",
        "columns": {
            "code": "Three-letter ISO 4217 currency code (e.g. USD, GBP, JPY).",
            "name": "Human-readable currency name (e.g. United States Dollar).",
        },
    },
    "latest": {
        "description": "The most recent available exchange rate for each currency against the base currency, as one row per currency.",
        "docs_url": "https://docs.openexchangerates.org/reference/latest-json",
        "columns": {
            "base": "Base currency the rates are quoted against (USD on the free plan).",
            "currency": "Three-letter ISO 4217 code of the quoted currency.",
            "rate": "Exchange rate: units of `currency` per one unit of `base`.",
            "date": "Date the rates apply to, derived from the response timestamp (YYYY-MM-DD, UTC).",
            "timestamp": "Unix timestamp of when the rates were last published.",
        },
    },
    "historical": {
        "description": "Daily historical exchange rates per currency, one row per (base, currency, date). Each value date is fetched from the /historical/{date}.json endpoint.",
        "docs_url": "https://docs.openexchangerates.org/reference/historical-json",
        "columns": {
            "base": "Base currency the rates are quoted against (USD on the free plan).",
            "currency": "Three-letter ISO 4217 code of the quoted currency.",
            "rate": "Exchange rate for that day: units of `currency` per one unit of `base`.",
            "date": "Value date of the rate (YYYY-MM-DD).",
            "timestamp": "Unix timestamp of when the rates for that day were published.",
        },
    },
    "time_series": {
        "description": "Daily historical exchange rates per currency, one row per (base, currency, date). Fetched from the /time-series.json endpoint one month at a time. Requires an Enterprise or Unlimited plan.",
        "docs_url": "https://docs.openexchangerates.org/reference/time-series-json",
        "columns": {
            "base": "Base currency the rates are quoted against.",
            "currency": "Three-letter ISO 4217 code of the quoted currency.",
            "rate": "Exchange rate for that day: units of `currency` per one unit of `base`.",
            "date": "Value date of the rate (YYYY-MM-DD).",
        },
    },
    "ohlc": {
        "description": "Daily open, high, low, close and average exchange rates per currency, one row per (base, currency, date). Fetched from the /ohlc.json endpoint with a one-day period. Requires a VIP Platinum plan.",
        "docs_url": "https://docs.openexchangerates.org/reference/ohlc-json",
        "columns": {
            "base": "Base currency the rates are quoted against.",
            "currency": "Three-letter ISO 4217 code of the quoted currency.",
            "date": "Day the period covers (YYYY-MM-DD, UTC).",
            "start_time": "ISO 8601 UTC timestamp of the start of the period, which the open rate is recorded at.",
            "end_time": "ISO 8601 UTC timestamp of the end of the period (inclusive), which the close rate is recorded at.",
            "open": "Midpoint rate recorded at the start of the period.",
            "high": "Highest midpoint rate recorded during the period.",
            "low": "Lowest midpoint rate recorded during the period.",
            "close": "Midpoint rate recorded at the end of the period.",
            "average": "Time-weighted average midpoint rate for the whole period.",
        },
    },
    "usage": {
        "description": "Your Open Exchange Rates account plan and current-period request usage, as a single row.",
        "docs_url": "https://docs.openexchangerates.org/reference/usage-json",
        "columns": {
            "id": 'Constant synthetic key for this single-row snapshot (always "usage"). The account\'s App ID is deliberately not stored, as it is the API credential.',
            "status": "Account status (e.g. active).",
            "plan_name": "Name of the subscription plan (e.g. Free, Developer).",
            "plan_quota": "Human-readable monthly request quota for the plan.",
            "plan_update_frequency": "How often rates are refreshed on the plan.",
            "requests": "Number of requests made in the current billing period.",
            "requests_quota": "Total requests allowed in the current billing period.",
            "requests_remaining": "Requests remaining in the current billing period.",
            "days_elapsed": "Days elapsed in the current billing period.",
            "days_remaining": "Days remaining in the current billing period.",
            "daily_average": "Average requests per day so far this period.",
        },
    },
}
