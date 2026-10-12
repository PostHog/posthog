"""Canonical, documentation-sourced descriptions for NewsData.io endpoints and columns.

Sourced from the official NewsData.io API reference (https://newsdata.io/documentation).
Keyed by the endpoint names in `settings.py` `NEWSDATA_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced NewsData.io table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# The latest, archive, and crypto endpoints all return the same news-article shape.
_ARTICLE_COLUMNS = {
    "article_id": "Unique identifier for the news article.",
    "title": "The article's headline.",
    "link": "URL of the original article.",
    "keywords": "Keywords associated with the article.",
    "creator": "Author(s) of the article.",
    "video_url": "URL of a video embedded in the article, if any.",
    "description": "A short summary of the article.",
    "content": "The full text content of the article (available on paid plans).",
    "pubDate": "Date and time the article was published, in UTC.",
    "pubDateTZ": "Timezone of the original publish date.",
    "image_url": "URL of the article's main image.",
    "source_id": "Identifier of the news source that published the article.",
    "source_priority": "Ranking of the source's importance/authority.",
    "source_name": "Display name of the news source.",
    "source_url": "Home URL of the news source.",
    "source_icon": "URL of the news source's icon.",
    "language": "Language the article is written in.",
    "country": "Countries the article is relevant to.",
    "category": "Categories the article belongs to (e.g. business, technology).",
    "sentiment": "Overall sentiment of the article (positive, neutral, or negative).",
    "sentiment_stats": "Per-sentiment confidence breakdown for the article.",
    "ai_tag": "AI-generated topic tags for the article.",
    "ai_region": "AI-detected regions mentioned in the article.",
    "ai_org": "AI-detected organizations mentioned in the article.",
    "duplicate": "Whether the article is flagged as a duplicate of another.",
}

_LATEST_DOCS = "https://newsdata.io/documentation/#latest-news"
_ARCHIVE_DOCS = "https://newsdata.io/documentation/#news-archive"
_CRYPTO_DOCS = "https://newsdata.io/documentation/#crypto-news"

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "latest": {
        "description": "Real-time news articles from the last 48 hours across sources worldwide.",
        "docs_url": _LATEST_DOCS,
        "columns": _ARTICLE_COLUMNS,
    },
    "archive": {
        "description": "Historical news articles (up to 7 years) filterable by publish date.",
        "docs_url": _ARCHIVE_DOCS,
        "columns": _ARTICLE_COLUMNS,
    },
    "crypto": {
        "description": "Cryptocurrency-related news articles filterable by publish date and coin.",
        "docs_url": _CRYPTO_DOCS,
        "columns": {
            **_ARTICLE_COLUMNS,
            "coin": "Cryptocurrency coins the article relates to (e.g. btc, eth).",
        },
    },
    "sources": {
        "description": "Catalog of news sources available through NewsData.io.",
        "docs_url": "https://newsdata.io/documentation/#news-sources",
        "columns": {
            "id": "Unique identifier for the news source.",
            "name": "Display name of the news source.",
            "url": "Home URL of the news source.",
            "icon": "URL of the news source's icon.",
            "priority": "Ranking of the source's importance/authority.",
            "description": "A short description of the news source.",
            "category": "Categories the source primarily covers.",
            "language": "Languages the source publishes in.",
            "country": "Countries the source operates in.",
            "last_fetch": "Time the source was last fetched by NewsData.io.",
            "total_article": "Total number of articles available from the source.",
        },
    },
}
