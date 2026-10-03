from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_DOCS_URL = "https://date.nager.at/scalar"

_HOLIDAY_COLUMNS = {
    "id": "Synthetic identifier this source adds from countryCode, date, name, subdivisionCodes, "
    "and holidayTypes, so a holiday split across subdivisions gets a unique row.",
    "date": "The date of the holiday.",
    "name": "English name of the holiday.",
    "countryCode": "ISO 3166-1 alpha-2 country code.",
    "nationalHoliday": "True if the holiday applies to the entire country.",
    "subdivisionCodes": "ISO 3166-2 codes of the subdivisions the holiday applies to, or null if it applies nationally.",
    "holidayTypes": "Holiday type classifications, for example Public, Bank, or School.",
}

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "Countries": {
        "description": "Countries the Nager.Date API publishes public holiday data for.",
        "docs_url": _DOCS_URL,
        "columns": {
            "countryCode": "ISO 3166-1 alpha-2 country code, for example US or DE.",
            "name": "The common name of the country.",
        },
    },
    "CountryInfo": {
        "description": "Name and region information for each configured country, including neighboring countries.",
        "docs_url": _DOCS_URL,
        "columns": {
            "commonName": "The commonly used name of the country.",
            "nativeName": "The name of the country in its native language.",
            "officialName": "The official name of the country.",
            "countryCode": "ISO 3166-1 alpha-2 country code.",
            "region": "Geopolitical or continental region of the country.",
            "borders": "Neighboring countries based on geographical borders, or null if none.",
        },
    },
    "PublicHolidays": {
        "description": "Public holidays for each configured country, for the years the API currently supports "
        "(a rolling window around the current year).",
        "docs_url": _DOCS_URL,
        "columns": _HOLIDAY_COLUMNS,
    },
    "NextPublicHolidays": {
        "description": "The next public holidays occurring within 365 days for each configured country.",
        "docs_url": _DOCS_URL,
        "columns": _HOLIDAY_COLUMNS,
    },
}
