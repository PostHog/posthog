from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_DOCS_URL = "https://doc.wikimedia.org/generated-data-platform/aqs/analytics-api/reference/page-views.html"
_DEVICES_DOCS_URL = "https://doc.wikimedia.org/generated-data-platform/aqs/analytics-api/reference/devices.html"
_MEDIA_DOCS_URL = "https://doc.wikimedia.org/generated-data-platform/aqs/analytics-api/reference/media-files.html"

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
    "country_pageviews": {
        "description": "Monthly pageviews for the configured Wikimedia project, split by the country the views "
        "came from. Only countries with more than 100 views appear.",
        "docs_url": _DOCS_URL,
        "columns": {
            "project": "Wikimedia project the counts belong to (e.g. en.wikipedia).",
            "access": "Access method the views came from: all-access, desktop, mobile-app, or mobile-web.",
            "year": "Year of the month, as returned by the API (e.g. 2024).",
            "month": "Zero-padded month (e.g. 01).",
            "date": "First day of the month as a timestamp.",
            "country": "Country code in ISO 3166-1 alpha-2 format.",
            "views": "Range of pageviews from the country in the month (e.g. 100000-999999).",
            "views_ceil": "Approximate number of pageviews from the country in the month.",
            "rank": "Rank of the country by pageviews in the month, starting at 1.",
        },
    },
    "country_top_articles": {
        "description": "The most-viewed pages per day for each configured country, across all Wikimedia projects. "
        "Excludes bots and crawlers, and omits pages with 1000 or fewer views.",
        "docs_url": _DOCS_URL,
        "columns": {
            "country": "Country code in ISO 3166-1 alpha-2 format.",
            "access": "Access method the ranking covers: all-access, desktop, mobile-app, or mobile-web.",
            "year": "Year of the ranking day, as returned by the API (e.g. 2024).",
            "month": "Zero-padded month of the ranking day (e.g. 01).",
            "day": "Zero-padded day of month of the ranking day (e.g. 01).",
            "date": "Ranking day as a timestamp, parsed from the year/month/day fields.",
            "project": "Wikimedia project the page belongs to (e.g. fr.wikipedia).",
            "article": "Page title in URL form (spaces as underscores).",
            "views_ceil": "Approximate number of views the page received from the country on the day.",
            "rank": "Rank of the page among the country's most-viewed pages on the day, starting at 1.",
        },
    },
    "unique_devices": {
        "description": "Daily number of unique devices that visited the configured Wikimedia project, "
        "for all sites, the desktop site, and the mobile site.",
        "docs_url": _DEVICES_DOCS_URL,
        "columns": {
            "project": "Wikimedia project the counts belong to (e.g. en.wikipedia).",
            "access_site": "Site the devices visited: all-sites, desktop-site, or mobile-site.",
            "granularity": "Time bucket of the count; always daily for this source.",
            "timestamp": "Day of the count in YYYYMMDD format, as returned by the API.",
            "date": "Day of the count as a timestamp, parsed from the API's timestamp field.",
            "devices": "Number of unique devices that visited on the day.",
            "offset": "Number of devices with one visit or an unknown number of visits.",
            "underestimate": "Number of devices with two or more visits on the day.",
        },
    },
    "media_requests": {
        "description": "Daily requests for media files on upload.wikimedia.org that the configured project referred, "
        "split by media type.",
        "docs_url": _MEDIA_DOCS_URL,
        "columns": {
            "referer": "Wikimedia project that referred the requests (e.g. en.wikipedia).",
            "media_type": "Type of media file: image, video, audio, document, or other.",
            "agent": "Agent type that made the requests: user, spider, or all-agents.",
            "granularity": "Time bucket of the count; always daily for this source.",
            "timestamp": "Day of the count in YYYYMMDDHH format, as returned by the API.",
            "date": "Day of the count as a timestamp, parsed from the API's timestamp field.",
            "requests": "Number of media file requests on the day.",
        },
    },
}
