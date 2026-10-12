from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "holidays": {
        "description": "Holidays and observances for the selected country and year.",
        "docs_url": "https://calendarific.com/api-documentation",
        "columns": {
            "name": "Holiday name.",
            "description": "Explanation of the holiday.",
            "country": "Country code and name.",
            "date": "Holiday date in ISO format, with year, month, and day components.",
            "type": "Categories for the holiday.",
            "primary_type": "Main holiday category.",
            "canonical_url": "Calendarific page for the holiday.",
            "locations": "Regions that observe the holiday, or All for the entire country.",
        },
    },
    "countries": {
        "description": "Supported countries, with country codes, holiday counts, and the number of supported languages.",
        "docs_url": "https://calendarific.com/api-documentation",
        "columns": {},
    },
    "languages": {
        "description": "Supported languages, with ISO codes, English names, and native names.",
        "docs_url": "https://calendarific.com/api-documentation",
        "columns": {},
    },
}
