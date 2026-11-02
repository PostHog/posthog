from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Sourced from the official GIPHY API schema docs (https://developers.giphy.com/docs/api/schema/).
# The GIF Object is shared by every trending/search endpoint, so its column descriptions are
# reused across gifs_*/stickers_* tables.
_GIF_OBJECT_COLUMNS: dict[str, str] = {
    "id": "Unique identifier for this GIF.",
    "type": 'The type of object — usually "gif".',
    "slug": "The unique slug used in this GIF's URL.",
    "url": "The unique URL for this GIF.",
    "bitly_url": "The unique bit.ly URL for this GIF.",
    "embed_url": "A URL used for embedding this GIF.",
    "username": "The username this GIF is attached to, if applicable.",
    "source": "The page on which this GIF was found.",
    "rating": "The MPAA-style content rating (y, g, pg, pg-13, r).",
    "title": "The title that appears on giphy.com for this GIF.",
    "import_datetime": "The creation or upload date from this GIF's source.",
    "trending_datetime": "The date this GIF was marked trending, if applicable.",
    "source_tld": "The top level domain of the source URL.",
    "source_post_url": "The URL of the webpage on which this GIF was found.",
    "images": "Object containing the available renditions (sizes/formats) of this GIF.",
    "user": "Object describing the GIPHY user that uploaded this GIF, if any.",
}

_DOCS_URL = "https://developers.giphy.com/docs/api/schema/"

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "gifs_trending": {
        "description": "The GIFs currently trending on GIPHY, ordered by GIPHY's relevance algorithm.",
        "docs_url": _DOCS_URL,
        "columns": _GIF_OBJECT_COLUMNS,
    },
    "stickers_trending": {
        "description": "The stickers (transparent-background GIFs) currently trending on GIPHY.",
        "docs_url": _DOCS_URL,
        "columns": _GIF_OBJECT_COLUMNS,
    },
    "gifs_search": {
        "description": "GIFs matching the configured search query, ordered by GIPHY's relevance algorithm.",
        "docs_url": _DOCS_URL,
        "columns": _GIF_OBJECT_COLUMNS,
    },
    "stickers_search": {
        "description": "Stickers matching the configured search query, ordered by GIPHY's relevance algorithm.",
        "docs_url": _DOCS_URL,
        "columns": _GIF_OBJECT_COLUMNS,
    },
    "categories": {
        "description": "The GIPHY GIF category taxonomy.",
        "docs_url": _DOCS_URL,
        "columns": {
            "name": "The display name of the category.",
            "name_encoded": "The URL-encoded category name.",
            "subcategories": "A list of subcategories under this category.",
        },
    },
    "trending_search_terms": {
        "description": "The search terms currently trending across GIPHY.",
        "docs_url": _DOCS_URL,
        "columns": {
            "search_term": "A search term currently trending on GIPHY.",
        },
    },
}
