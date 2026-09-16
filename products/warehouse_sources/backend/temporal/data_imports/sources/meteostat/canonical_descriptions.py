"""Canonical, documentation-sourced descriptions for Meteostat endpoints and columns.

Sourced from the official Meteostat JSON API reference (https://dev.meteostat.net/api). Keyed by
the resource names in `settings.py` `ENDPOINTS`, which match the `ExternalDataSchema.name` of a
synced Meteostat table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_STATION_ID_COLUMN = "Meteostat weather station ID this record belongs to, as configured in the source settings."

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "Hourly": {
        "description": "Historical hourly weather observations for a station, with gaps optionally filled "
        "by statistically optimized model data.",
        "docs_url": "https://dev.meteostat.net/api/stations/hourly",
        "columns": {
            "station_id": _STATION_ID_COLUMN,
            "time": "Time of observation (YYYY-MM-DD hh:mm:ss).",
            "temp": "The air temperature in °C.",
            "dwpt": "The dew point in °C.",
            "rhum": "The relative humidity in percent (%).",
            "prcp": "The one hour precipitation total in mm.",
            "snow": "The snow depth in mm.",
            "wdir": "The wind direction in degrees (°).",
            "wspd": "The average wind speed in km/h.",
            "wpgt": "The peak wind gust in km/h.",
            "pres": "The sea-level air pressure in hPa.",
            "tsun": "The one hour sunshine total in minutes (m).",
            "coco": "The weather condition code.",
        },
    },
    "Daily": {
        "description": "Historical daily weather statistics for a station, aggregated from observations and "
        "model data.",
        "docs_url": "https://dev.meteostat.net/api/stations/daily",
        "columns": {
            "station_id": _STATION_ID_COLUMN,
            "date": "The date (YYYY-MM-DD).",
            "tavg": "The average air temperature in °C.",
            "tmin": "The minimum air temperature in °C.",
            "tmax": "The maximum air temperature in °C.",
            "prcp": "The daily precipitation total in mm.",
            "snow": "The maximum snow depth in mm.",
            "wdir": "The average wind direction in degrees (°).",
            "wspd": "The average wind speed in km/h.",
            "wpgt": "The peak wind gust in km/h.",
            "pres": "The average sea-level air pressure in hPa.",
            "tsun": "The daily sunshine total in minutes (m).",
        },
    },
    "Monthly": {
        "description": "Historical monthly weather statistics for a station, aggregated from hourly "
        "observations, daily records, and model data.",
        "docs_url": "https://dev.meteostat.net/api/stations/monthly",
        "columns": {
            "station_id": _STATION_ID_COLUMN,
            "date": "The first date (YYYY-MM-DD) of the month.",
            "tavg": "The average daily air temperature in °C.",
            "tmin": "The average daily minimum air temperature in °C.",
            "tmax": "The average daily maximum air temperature in °C.",
            "prcp": "The monthly precipitation total in mm.",
            "snow": "The maximum snow depth in mm.",
            "wdir": "The average wind direction in degrees (°).",
            "wspd": "The average wind speed in km/h.",
            "wpgt": "The peak wind gust in km/h.",
            "pres": "The average sea-level air pressure in hPa.",
            "tsun": "The monthly sunshine total in minutes (m).",
        },
    },
}
