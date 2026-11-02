from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Injected by the connector on every row (not part of the raw API response).
_INJECTED_COLUMNS = {
    "latitude": "Requested latitude of the location (as configured, not a snapped grid cell).",
    "longitude": "Requested longitude of the location (as configured, not a snapped grid cell).",
    "location_label": "Optional user-supplied label for the configured location.",
    "dt_iso": "ISO 8601 UTC timestamp derived from the response timestamp; used as the partition key and append cursor.",
}

_AIR_QUALITY_COLUMNS = {
    "dateTime": "Rounded timestamp the data refers to, RFC 3339 UTC.",
    "regionCode": "ISO 3166-1 alpha-2 country/region code the location falls in.",
    "indexes": "List of air-quality indexes (e.g. Universal AQI and the local index) with code, value, category, and dominant pollutant.",
    "pollutants": "List of pollutant objects (code, display name, concentration, and additional info) where requested.",
    "healthRecommendations": "Health advice per population group (general, elderly, athletes, etc.) where requested.",
}

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "air_quality_current": {
        "description": "Current air-quality conditions for a configured location, from the Google Maps Platform Air Quality API (currentConditions).",
        "docs_url": "https://developers.google.com/maps/documentation/air-quality/reference/rest/v1/currentConditions/lookup",
        "columns": {
            **_INJECTED_COLUMNS,
            **_AIR_QUALITY_COLUMNS,
        },
    },
    "air_quality_forecast": {
        "description": "Hourly air-quality forecast (up to 96 hours ahead) for a configured location; one row per forecast hour.",
        "docs_url": "https://developers.google.com/maps/documentation/air-quality/reference/rest/v1/forecast/lookup",
        "columns": {
            **_INJECTED_COLUMNS,
            **_AIR_QUALITY_COLUMNS,
        },
    },
    "air_quality_history": {
        "description": "Historical hourly air quality (the last 24 hours) for a configured location; one row per hour.",
        "docs_url": "https://developers.google.com/maps/documentation/air-quality/reference/rest/v1/history/lookup",
        "columns": {
            **_INJECTED_COLUMNS,
            **_AIR_QUALITY_COLUMNS,
        },
    },
    "pollen_forecast": {
        "description": "Daily pollen forecast (up to 5 days ahead) for a configured location, from the Google Maps Platform Pollen API; one row per day.",
        "docs_url": "https://developers.google.com/maps/documentation/pollen/reference/rest/v1/forecast/lookup",
        "columns": {
            **_INJECTED_COLUMNS,
            "date": "Calendar date the forecast day refers to, as a `{year, month, day}` object.",
            "regionCode": "ISO 3166-1 alpha-2 country/region code the location falls in.",
            "pollenTypeInfo": "Per pollen type (grass, tree, weed) index, category, and health recommendations for the day.",
            "plantInfo": "Per plant index, category, and plant description (in-season flag, cross-reactions) for the day.",
        },
    },
}
