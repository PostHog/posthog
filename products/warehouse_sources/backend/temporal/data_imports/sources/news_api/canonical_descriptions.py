from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_ARTICLE_COLUMNS = {
    "source": "The identifier and display name of the source this article came from, as {id, name}.",
    "author": "The author of the article.",
    "title": "The headline or title of the article.",
    "description": "A short description or snippet of the article.",
    "url": "The direct URL to the article. Unique per article and used as the primary key.",
    "urlToImage": "The URL to a relevant image for the article.",
    "publishedAt": "The date and time the article was published, in UTC ISO 8601.",
    "content": "The unformatted content of the article, truncated to around 200 characters on most plans.",
}

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "everything": {
        "description": "News and blog articles matching the configured search query, from NewsAPI's /v2/everything endpoint.",
        "docs_url": "https://newsapi.org/docs/endpoints/everything",
        "columns": _ARTICLE_COLUMNS,
    },
    "top_headlines": {
        "description": "Breaking-news headlines matching the configured search query, from NewsAPI's /v2/top-headlines endpoint.",
        "docs_url": "https://newsapi.org/docs/endpoints/top-headlines",
        "columns": _ARTICLE_COLUMNS,
    },
    "sources": {
        "description": "The publishers and blogs available through NewsAPI's top-headlines endpoint.",
        "docs_url": "https://newsapi.org/docs/endpoints/sources",
        "columns": {
            "id": "The unique identifier for the news source. Used as the primary key.",
            "name": "The display name of the news source.",
            "description": "A description of the news source.",
            "url": "The homepage URL of the news source.",
            "category": "The category the news source belongs to (e.g. business, technology).",
            "language": "The two-letter ISO-639-1 language code of the source.",
            "country": "The two-letter ISO 3166-1 country code of the source.",
        },
    },
}
