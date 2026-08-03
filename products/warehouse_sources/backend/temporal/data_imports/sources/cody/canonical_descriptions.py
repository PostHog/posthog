from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_DOCS_URL = "https://sourcegraph.com/docs/analytics/api"

# Table-level descriptions only: Sourcegraph doesn't publish the CSV column schema for these
# reports, so column descriptions are left to the LLM enrichment pass (which receives the
# docs_url below) rather than curated from guesses.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "usage_by_user": {
        "description": "All-time Sourcegraph and Cody usage totals per user, including searches, chats, code completions, and completion acceptance rates.",
        "docs_url": _DOCS_URL,
    },
    "usage_by_user_month": {
        "description": "Monthly Sourcegraph and Cody usage totals per user, one row per user per calendar month of activity.",
        "docs_url": _DOCS_URL,
    },
    "usage_by_user_day": {
        "description": "Daily Sourcegraph and Cody usage totals per user, one row per user per day of activity.",
        "docs_url": _DOCS_URL,
    },
    "usage_by_user_day_client_language": {
        "description": "Daily Sourcegraph and Cody usage per user, split by client/editor and programming language. The most detailed usage report the Analytics API offers.",
        "docs_url": _DOCS_URL,
    },
    "credits": {
        "description": "Credit bucket allocations and consumption for the Sourcegraph instance, filtered by each bucket's active period.",
        "docs_url": _DOCS_URL,
    },
}
