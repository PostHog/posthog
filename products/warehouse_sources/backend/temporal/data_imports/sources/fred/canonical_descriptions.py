from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

DOCS_BASE_URL = "https://fred.stlouisfed.org/docs/api/fred"

# Shared across every table: FRED versions each record over a real-time (ALFRED) period, so
# each row carries the window during which it was the current version of that record.
_REALTIME_COLUMNS = {
    "realtime_start": "Start of the real-time period this version of the record was in effect for.",
    "realtime_end": "End of the real-time period this version of the record was in effect for. 9999-12-31 for the current version.",
}

_TAG_COLUMNS = {
    "name": "Tag name, for example 'usa', 'monthly' or 'nsa'.",
    "group_id": "Group the tag belongs to: freq (frequency), gen (general), geo (geography), geot (geography type), rls (release), seas (seasonal adjustment) or src (source).",
    "notes": "Description of the tag.",
    "created": "Timestamp of when the tag was created.",
    "popularity": "FRED popularity score for the tag, from 0 to 100.",
    "series_count": "Number of series carrying the tag.",
}

_RELEASE_COLUMNS = {
    "id": "Numeric identifier for the release.",
    "name": "Name of the release, for example 'Employment Situation'.",
    "press_release": "True when the release has an accompanying press release.",
    "link": "URL of the release on the publishing agency's site.",
    "notes": "Description of the release.",
    **_REALTIME_COLUMNS,
}

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "series": {
        "description": "Metadata for each economic data series listed in the source's series IDs, including its title, frequency, units and when it was last updated.",
        "docs_url": f"{DOCS_BASE_URL}/series.html",
        "columns": {
            "id": "FRED series ID, for example UNRATE or CPIAUCSL.",
            "title": "Title of the series, for example 'Unemployment Rate'.",
            "observation_start": "Date of the earliest observation available for the series.",
            "observation_end": "Date of the most recent observation available for the series.",
            "frequency": "Native frequency of the series, for example 'Monthly' or 'Quarterly'.",
            "frequency_short": "Short code for the native frequency, for example 'M' or 'Q'.",
            "units": "Units the observation values are expressed in, for example 'Percent'.",
            "units_short": "Short form of the units.",
            "seasonal_adjustment": "Seasonal adjustment applied to the series, for example 'Seasonally Adjusted'.",
            "seasonal_adjustment_short": "Short code for the seasonal adjustment, for example 'SA' or 'NSA'.",
            "last_updated": "Timestamp of when FRED last updated the series, in US Central time.",
            "popularity": "FRED popularity score for the series, from 0 to 100.",
            "notes": "Description of the series, usually including its source and methodology.",
            **_REALTIME_COLUMNS,
        },
    },
    "observations": {
        "description": "Observation values over time for each series in the source's series IDs. One row per series and observation date.",
        "docs_url": f"{DOCS_BASE_URL}/series_observations.html",
        "columns": {
            "series_id": "FRED series ID the observation belongs to, taken from the source's series IDs.",
            "date": "Date the observation refers to.",
            "value": "Observed value, as a string. FRED returns '.' when no value is available for that date.",
            **_REALTIME_COLUMNS,
        },
    },
    "series_categories": {
        "description": "Categories each series in the source's series IDs belongs to, in FRED's category tree.",
        "docs_url": f"{DOCS_BASE_URL}/series_categories.html",
        "columns": {
            "series_id": "FRED series ID the category applies to.",
            "id": "Numeric identifier for the category.",
            "name": "Name of the category.",
            "parent_id": "Identifier of the parent category, or 0 at the root.",
        },
    },
    "series_tags": {
        "description": "Tags attached to each series in the source's series IDs, covering frequency, geography, source and seasonal adjustment.",
        "docs_url": f"{DOCS_BASE_URL}/series_tags.html",
        "columns": {
            "series_id": "FRED series ID the tag applies to.",
            **_TAG_COLUMNS,
        },
    },
    "series_releases": {
        "description": "The release each series in the source's series IDs is published in.",
        "docs_url": f"{DOCS_BASE_URL}/series_release.html",
        "columns": {
            "series_id": "FRED series ID the release applies to.",
            **_RELEASE_COLUMNS,
        },
    },
    "releases": {
        "description": "Every release of economic data published on FRED, such as the Employment Situation or the Consumer Price Index.",
        "docs_url": f"{DOCS_BASE_URL}/releases.html",
        "columns": _RELEASE_COLUMNS,
    },
    "release_dates": {
        "description": "The publication calendar for FRED releases, including scheduled future dates.",
        "docs_url": f"{DOCS_BASE_URL}/releases_dates.html",
        "columns": {
            "release_id": "Identifier of the release the date belongs to.",
            "release_name": "Name of the release.",
            "date": "Date the release was or will be published.",
        },
    },
    "sources": {
        "description": "Organizations that publish the data behind FRED releases, such as the Bureau of Labor Statistics.",
        "docs_url": f"{DOCS_BASE_URL}/sources.html",
        "columns": {
            "id": "Numeric identifier for the source.",
            "name": "Name of the publishing organization.",
            "link": "URL of the organization's site.",
            "notes": "Description of the source.",
            **_REALTIME_COLUMNS,
        },
    },
    "tags": {
        "description": "Every tag FRED assigns to series, used to filter and group them by frequency, geography, publisher and seasonal adjustment.",
        "docs_url": f"{DOCS_BASE_URL}/tags.html",
        "columns": _TAG_COLUMNS,
    },
}
