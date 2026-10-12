"""Canonical, documentation-sourced descriptions for the Google Fonts (Web Fonts Developer API).

Sourced from the official API reference (https://developers.google.com/fonts/docs/developer_api).
Keyed by the endpoint names in `settings.py` `GOOGLE_WEBFONTS_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "webfonts": {
        "description": "The full catalog of font families served by Google Fonts, one row per family.",
        "docs_url": "https://developers.google.com/fonts/docs/developer_api",
        "columns": {
            "family": "Name of the font family (e.g. 'Roboto'). Unique identifier for the family.",
            "variants": "List of the available styles/weights for the family (e.g. 'regular', 'italic', '700').",
            "subsets": "List of character subsets the family supports (e.g. 'latin', 'cyrillic', 'greek').",
            "version": "Current version string of the family (e.g. 'v30').",
            "lastModified": "Date the family was last modified, in YYYY-MM-DD format.",
            "files": "Map of each variant to the URL of its font file.",
            "category": "Category of the family: serif, sans-serif, monospace, display, or handwriting.",
            "kind": "Type of the resource; always 'webfonts#webfont' for a family.",
            "menu": "URL of a font file containing only the glyphs needed to render the family name.",
            "axes": "For variable fonts, the list of variation axes with their tag, start, and end values.",
            "colorCapabilities": "For color fonts, the list of supported color formats (e.g. 'COLRv0', 'COLRv1').",
        },
    },
}
