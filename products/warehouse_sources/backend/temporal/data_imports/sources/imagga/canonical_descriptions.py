from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Sourced from Imagga's public API docs (https://docs.imagga.com/#usage). The /usage response is
# normalized into two tables; column names below reflect that normalization (nested objects are
# flattened with a `<key>_` prefix, and the daily histogram is exploded into rows).
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "usage": {
        "description": "Current billing-period consumption snapshot for the Imagga account: request and processed counters, the monthly request limit, and concurrency.",
        "docs_url": "https://docs.imagga.com/#usage",
        "columns": {
            "billing_period_start": "Start of the current billing period.",
            "billing_period_end": "End of the current billing period.",
            "monthly_limit": "Maximum number of requests allowed in the current billing period under the account's plan.",
            "daily_requests": "Number of API requests made so far on the reference day.",
            "daily_processed": "Number of items processed so far on the reference day (a single request can process multiple items).",
            "daily_for": "The day the daily_* counters refer to.",
            "last_usage": "Unix timestamp of the account's most recent API usage.",
            "concurrency_now": "Number of requests currently being processed concurrently.",
            "concurrency_max": "Maximum number of concurrent requests allowed by the account's plan.",
        },
    },
    "daily_usage": {
        "description": "Per-day usage history for the Imagga account, one row per day.",
        "docs_url": "https://docs.imagga.com/#usage",
        "columns": {
            "date": "Calendar day (UTC) the usage count refers to.",
            "timestamp": "Unix-second timestamp of the day, as returned by Imagga.",
            "count": "Number of API requests recorded for the day.",
        },
    },
}
