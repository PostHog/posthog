from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Column descriptions taken from the GNews article schema (https://gnews.io/docs/v4). The nested
# `source` object is flattened onto each row (see gnews.py:_flatten_article), so its fields are
# documented here with their `source_` prefix.
_ARTICLE_COLUMNS = {
    "title": "Headline of the article.",
    "description": "Short snippet describing the article.",
    "content": "Main body text of the article (truncated on free plans).",
    "url": "Canonical URL of the article; unique per article and used as the primary key.",
    "image": "URL of the article's main image.",
    "publishedAt": "Publish timestamp of the article in ISO 8601 (UTC).",
    "lang": "Two-letter language code of the article, when a language filter was not applied.",
    "source_id": "Identifier of the publishing source.",
    "source_name": "Name of the publishing source.",
    "source_url": "Homepage URL of the publishing source.",
    "source_country": "Two-letter country code of the publishing source.",
}

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "articles": {
        "description": "Worldwide news articles matching the configured keyword search query.",
        "docs_url": "https://gnews.io/docs/v4#search-endpoint",
        "columns": _ARTICLE_COLUMNS,
    },
    "top_headlines": {
        "description": "Breaking news headlines for the configured category.",
        "docs_url": "https://gnews.io/docs/v4#top-headlines-endpoint",
        "columns": _ARTICLE_COLUMNS,
    },
}
