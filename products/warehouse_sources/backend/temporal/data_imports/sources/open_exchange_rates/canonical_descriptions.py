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
    "usage": {
        "description": "Your Open Exchange Rates account plan and current-period request usage, as a single row.",
        "docs_url": "https://docs.openexchangerates.org/reference/usage-json",
        "columns": {
            "app_id": "The App ID the usage figures belong to.",
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
