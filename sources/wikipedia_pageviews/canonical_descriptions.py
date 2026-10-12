from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_DOCS_URL = "https://doc.wikimedia.org/generated-data-platform/aqs/analytics-api/reference/page-views.html"

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "pageviews": {
        "description": "Daily total pageview counts for the configured Wikimedia project, "
        "filtered by access method and agent type.",
        "docs_url": _DOCS_URL,
        "columns": {
            "project": "Wikimedia project the counts belong to (e.g. en.wikipedia).",
            "access": "Access method the views came from: all-access, desktop, mobile-app, or mobile-web.",
            "agent": "Agent type that generated the views: all-agents, user, spider, or automated.",
            "granularity": "Time bucket of the count; always daily for this source.",
            "timestamp": "Day of the count in YYYYMMDDHH format, as returned by the API.",
            "date": "Day of the count as a timestamp, parsed from the API's timestamp field.",
            "views": "Number of pageviews counted on the day.",
        },
    },
    "article_pageviews": {
        "description": "Daily pageview counts for each configured article title, "
        "filtered by access method and agent type.",
        "docs_url": _DOCS_URL,
        "columns": {
            "project": "Wikimedia project the article belongs to (e.g. en.wikipedia).",
            "article": "Article title in URL form (spaces as underscores).",
            "access": "Access method the views came from: all-access, desktop, mobile-app, or mobile-web.",
            "agent": "Agent type that generated the views: all-agents, user, spider, or automated.",
            "granularity": "Time bucket of the count; always daily for this source.",
            "timestamp": "Day of the count in YYYYMMDDHH format, as returned by the API.",
            "date": "Day of the count as a timestamp, parsed from the API's timestamp field.",
            "views": "Number of pageviews the article received on the day.",
        },
    },
    "top_articles": {
        "description": "The 1000 most-viewed articles on the configured Wikimedia project for each day, "
        "with view counts and ranks.",
        "docs_url": _DOCS_URL,
        "columns": {
            "project": "Wikimedia project the ranking belongs to (e.g. en.wikipedia).",
            "access": "Access method the ranking covers: all-access, desktop, mobile-app, or mobile-web.",
            "year": "Year of the ranking day, as returned by the API (e.g. 2024).",
            "month": "Zero-padded month of the ranking day (e.g. 01).",
            "day": "Zero-padded day of month of the ranking day (e.g. 01).",
            "date": "Ranking day as a timestamp, parsed from the year/month/day fields.",
            "article": "Article title in URL form (spaces as underscores).",
            "views": "Number of pageviews the article received on the day.",
            "rank": "Rank of the article among the day's most-viewed articles, starting at 1.",
        },
    },
}
