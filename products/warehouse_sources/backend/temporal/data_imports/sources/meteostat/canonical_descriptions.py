"""Canonical, documentation-sourced descriptions for Meteostat endpoints and columns.

Sourced from the official Meteostat JSON API reference (https://dev.meteostat.net/api). Keyed by
the resource names in `settings.py` `ENDPOINTS`, which match the `ExternalDataSchema.name` of a
synced Meteostat table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_STATION_ID_COLUMN = "Meteostat weather station ID this record belongs to, as configured in the source settings."

_POINT_COLUMNS = {
    "latitude": "Latitude of the geographic location, as configured in the source settings.",
    "longitude": "Longitude of the geographic location, as configured in the source settings.",
    "altitude": "Elevation in meters of the geographic location, as configured in the source settings. Empty "
    "when not set, in which case Meteostat estimates the elevation.",
}

_HOURLY_COLUMNS = {
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
}

_DAILY_COLUMNS = {
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
}

_MONTHLY_COLUMNS = {
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
}

_NORMALS_COLUMNS = {
    "start": "The first year (YYYY) of the reference period.",
    "end": "The last year (YYYY) of the reference period.",
    "month": "The month (1 to 12).",
    "tavg": "The average daily air temperature in °C.",
    "tmin": "The average daily minimum air temperature in °C.",
    "tmax": "The average daily maximum air temperature in °C.",
    "prcp": "The monthly precipitation total in mm.",
    "wspd": "The average wind speed in km/h.",
    "pres": "The average sea-level air pressure in hPa.",
    "tsun": "The monthly sunshine total in minutes (m).",
}

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "Hourly": {
        "description": "Historical hourly weather observations for a station, with gaps optionally filled "
        "by statistically optimized model data.",
        "docs_url": "https://dev.meteostat.net/api/stations/hourly",
        "columns": {
            "station_id": _STATION_ID_COLUMN,
            **_HOURLY_COLUMNS,
        },
    },
    "Daily": {
        "description": "Historical daily weather statistics for a station, aggregated from observations and "
        "model data.",
        "docs_url": "https://dev.meteostat.net/api/stations/daily",
        "columns": {
            "station_id": _STATION_ID_COLUMN,
            **_DAILY_COLUMNS,
        },
    },
    "Monthly": {
        "description": "Historical monthly weather statistics for a station, aggregated from hourly "
        "observations, daily records, and model data.",
        "docs_url": "https://dev.meteostat.net/api/stations/monthly",
        "columns": {
            "station_id": _STATION_ID_COLUMN,
            **_MONTHLY_COLUMNS,
        },
    },
    "Stations": {
        "description": "Meta data for each configured weather station, including its names, country, region, "
        "identifiers, location, time zone, and data inventory.",
        "docs_url": "https://dev.meteostat.net/api/stations/meta",
        "columns": {
            "station_id": _STATION_ID_COLUMN,
            "id": "Meteostat ID of the weather station.",
            "name": "Name of the weather station in different languages, keyed by language code.",
            "country": "ISO 3166-1 alpha-2 country code, e.g. CA for Canada.",
            "region": "ISO 3166-2 state or region code, e.g. TX for Texas.",
            "identifier": "Other identifiers of the weather station: national, WMO, and ICAO IDs.",
            "location": "Geographic location of the weather station: latitude, longitude, and elevation in meters.",
            "timezone": "Time zone of the weather station.",
            "inventory": "First and last day or year of the available model, hourly, daily, monthly, and climate "
            "normals data.",
        },
    },
    "Normals": {
        "description": "Climate normals for a station: long-term monthly averages of weather observations, "
        "with twelve rows (one per month) for each reference period.",
        "docs_url": "https://dev.meteostat.net/api/stations/normals",
        "columns": {
            "station_id": _STATION_ID_COLUMN,
            **_NORMALS_COLUMNS,
        },
    },
    "PointHourly": {
        "description": "Historical hourly weather observations for a geographic location, interpolated from "
        "nearby weather stations, with gaps optionally filled by model data.",
        "docs_url": "https://dev.meteostat.net/api/point/hourly",
        "columns": {**_POINT_COLUMNS, **_HOURLY_COLUMNS},
    },
    "PointDaily": {
        "description": "Historical daily weather statistics for a geographic location, interpolated from nearby "
        "weather stations.",
        "docs_url": "https://dev.meteostat.net/api/point/daily",
        "columns": {**_POINT_COLUMNS, **_DAILY_COLUMNS},
    },
    "PointMonthly": {
        "description": "Historical monthly weather statistics for a geographic location, interpolated from "
        "nearby weather stations.",
        "docs_url": "https://dev.meteostat.net/api/point/monthly",
        "columns": {**_POINT_COLUMNS, **_MONTHLY_COLUMNS},
    },
    "PointNormals": {
        "description": "Climate normals for a geographic location: long-term monthly averages, with twelve rows "
        "(one per month) for each reference period.",
        "docs_url": "https://dev.meteostat.net/api/point/normals",
        "columns": {**_POINT_COLUMNS, **_NORMALS_COLUMNS},
    },
}
