"""Canonical, documentation-sourced descriptions for Guardian Open Platform endpoints and columns.

Sourced from the official Guardian Open Platform docs (https://open-platform.theguardian.com/documentation/).
Keyed by the endpoint names in `settings.py` `GUARDIAN_ENDPOINTS`, matching each synced table's
`ExternalDataSchema.name`. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "content": {
        "description": "A piece of Guardian content (article, liveblog, gallery, etc.) returned by the search endpoint.",
        "docs_url": "https://open-platform.theguardian.com/documentation/search",
        "columns": {
            "id": "The path to content, and its unique identifier (e.g. 'world/2026/jul/02/...').",
            "type": "The content type (e.g. article, liveblog, gallery, video, interactive).",
            "sectionId": "Identifier of the section the content belongs to.",
            "sectionName": "Display name of the section the content belongs to.",
            "webPublicationDate": "The combined date and time of publication (ISO 8601).",
            "webTitle": "The headline of the content.",
            "webUrl": "The URL of the content on theguardian.com.",
            "apiUrl": "The URL of the content in the Content API.",
            "fields": "Additional content fields requested via show-fields (headline, body, byline, wordcount, thumbnail, etc.).",
            "tags": "Tags associated with the content (keywords, contributors, series, tone, etc.).",
            "references": "External references associated with the content (e.g. ISBNs, IMDB ids).",
            "isHosted": "Whether the content is hosted (paid/commercial) content.",
            "pillarId": "Identifier of the pillar the content sits under (e.g. pillar/news).",
            "pillarName": "Display name of the pillar the content sits under (e.g. News, Sport).",
        },
    },
    "tags": {
        "description": "A Guardian tag used to categorize content — keywords, contributors, series, tones, and more.",
        "docs_url": "https://open-platform.theguardian.com/documentation/tag",
        "columns": {
            "id": "The unique identifier of the tag (its path).",
            "type": "The tag type (e.g. keyword, contributor, series, tone, type, publication).",
            "sectionId": "Identifier of the section the tag is associated with, if any.",
            "sectionName": "Display name of the section the tag is associated with, if any.",
            "webTitle": "The display name of the tag.",
            "webUrl": "The URL of the tag's page on theguardian.com.",
            "apiUrl": "The URL of the tag in the Content API.",
            "keywordType": "For keyword tags, the more specific keyword classification.",
        },
    },
    "sections": {
        "description": "A Guardian section grouping related content (e.g. World news, Football, Technology).",
        "docs_url": "https://open-platform.theguardian.com/documentation/section",
        "columns": {
            "id": "The unique identifier of the section.",
            "webTitle": "The display name of the section.",
            "webUrl": "The URL of the section's page on theguardian.com.",
            "apiUrl": "The URL of the section in the Content API.",
            "editions": "The editions in which this section appears.",
        },
    },
    "editions": {
        "description": "A regional Guardian edition (e.g. UK, US, Australia, International).",
        "docs_url": "https://open-platform.theguardian.com/documentation/edition",
        "columns": {
            "id": "The unique identifier of the edition.",
            "path": "The path of the edition's front page.",
            "edition": "The short code of the edition (e.g. UK, US, AU).",
            "webTitle": "The display name of the edition.",
            "webUrl": "The URL of the edition's front page on theguardian.com.",
            "apiUrl": "The URL of the edition in the Content API.",
        },
    },
}
