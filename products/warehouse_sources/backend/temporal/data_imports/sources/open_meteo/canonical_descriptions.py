from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Stamped onto every row by the connector; not part of the raw Open-Meteo response.
_INJECTED_COLUMNS = {
    "location_id": "Configured location as `latitude,longitude`. Part of the primary key.",
    "latitude": "Requested latitude of the location, exactly as configured.",
    "longitude": "Requested longitude of the location, exactly as configured.",
    "location_label": "Optional label supplied for the configured location.",
    "resolved_latitude": "Latitude of the grid cell Open-Meteo actually served, which can differ from the requested one.",
    "resolved_longitude": "Longitude of the grid cell Open-Meteo actually served, which can differ from the requested one.",
    "elevation": "Elevation of the grid cell in metres, from a 90m digital elevation model.",
    "timezone": "Timezone the timestamps are expressed in. Always GMT, since every request pins it.",
    "utc_offset_seconds": "Timezone offset applied to the timestamps, in seconds. Always 0.",
    "time_utc": "Timestamp of the row as a UTC datetime, derived from `time`. Used as the incremental cursor and partition key.",
    "time": "Timestamp of the row exactly as Open-Meteo returned it (ISO 8601, no offset).",
}

_HOURLY_WEATHER_COLUMNS = {
    "temperature_2m": "Air temperature at 2 metres above ground.",
    "relative_humidity_2m": "Relative humidity at 2 metres above ground, as a percentage.",
    "dew_point_2m": "Dew point temperature at 2 metres above ground.",
    "apparent_temperature": "Perceived feels-like temperature, combining wind chill, humidity and solar radiation.",
    "precipitation": "Total precipitation (rain, showers, snow) for the preceding hour.",
    "rain": "Rain from large scale weather systems for the preceding hour.",
    "snowfall": "Snowfall for the preceding hour, in centimetres.",
    "snow_depth": "Snow depth on the ground, in metres.",
    "weather_code": "WMO weather interpretation code for the hour.",
    "pressure_msl": "Atmospheric pressure reduced to mean sea level.",
    "surface_pressure": "Atmospheric pressure at surface level.",
    "cloud_cover": "Total cloud cover, as a percentage.",
    "wind_speed_10m": "Wind speed at 10 metres above ground.",
    "wind_direction_10m": "Wind direction at 10 metres above ground, in degrees.",
    "wind_gusts_10m": "Maximum wind gust of the preceding hour at 10 metres above ground.",
}

_DAILY_WEATHER_COLUMNS = {
    "weather_code": "Most severe WMO weather interpretation code of the day.",
    "temperature_2m_max": "Maximum daily air temperature at 2 metres above ground.",
    "temperature_2m_min": "Minimum daily air temperature at 2 metres above ground.",
    "apparent_temperature_max": "Maximum daily feels-like temperature.",
    "apparent_temperature_min": "Minimum daily feels-like temperature.",
    "sunrise": "Sunrise time for the day.",
    "sunset": "Sunset time for the day.",
    "daylight_duration": "Number of seconds of daylight.",
    "sunshine_duration": "Number of seconds of sunshine, counting only direct normal irradiance above 120 W/m².",
    "precipitation_sum": "Total precipitation (rain, showers, snow) for the day.",
    "rain_sum": "Total rain for the day.",
    "snowfall_sum": "Total snowfall for the day, in centimetres.",
    "precipitation_hours": "Number of hours in the day with precipitation.",
    "wind_speed_10m_max": "Maximum wind speed of the day at 10 metres above ground.",
    "wind_gusts_10m_max": "Maximum wind gust of the day at 10 metres above ground.",
    "wind_direction_10m_dominant": "Dominant wind direction of the day, in degrees.",
    "shortwave_radiation_sum": "Sum of daily shortwave solar radiation, in MJ/m².",
    "et0_fao_evapotranspiration": "Daily reference evapotranspiration for a well watered grass field (FAO-56).",
}

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "weather_archive_hourly": {
        "description": "Hourly historical weather for each configured location, from the Open-Meteo Historical Weather API (ERA5 and ERA5-Land reanalysis, 1940 onwards). One row per location per hour.",
        "docs_url": "https://open-meteo.com/en/docs/historical-weather-api",
        "columns": {
            **_INJECTED_COLUMNS,
            **_HOURLY_WEATHER_COLUMNS,
            "shortwave_radiation": "Average shortwave solar radiation of the preceding hour, in W/m².",
        },
    },
    "weather_archive_daily": {
        "description": "Daily aggregated historical weather for each configured location, from the Open-Meteo Historical Weather API (ERA5 and ERA5-Land reanalysis, 1940 onwards). One row per location per day.",
        "docs_url": "https://open-meteo.com/en/docs/historical-weather-api",
        "columns": {
            **_INJECTED_COLUMNS,
            **_DAILY_WEATHER_COLUMNS,
            "temperature_2m_mean": "Mean daily air temperature at 2 metres above ground.",
        },
    },
    "weather_forecast_hourly": {
        "description": "Hourly weather forecast for each configured location, covering the past 7 days and the next 16 days. Replaced on every sync, because forecast values for a given hour are revised on every model run.",
        "docs_url": "https://open-meteo.com/en/docs",
        "columns": {
            **_INJECTED_COLUMNS,
            **_HOURLY_WEATHER_COLUMNS,
            "precipitation_probability": "Probability of precipitation in the hour, as a percentage.",
            "showers": "Convective shower precipitation for the preceding hour.",
            "visibility": "Horizontal visibility at ground level, in metres.",
            "uv_index": "UV index, accounting for cloud cover.",
            "is_day": "1 while the sun is above the horizon at this location, 0 otherwise.",
        },
    },
    "weather_forecast_daily": {
        "description": "Daily weather forecast for each configured location, covering the past 7 days and the next 16 days. Replaced on every sync, because forecast values for a given day are revised on every model run.",
        "docs_url": "https://open-meteo.com/en/docs",
        "columns": {
            **_INJECTED_COLUMNS,
            **_DAILY_WEATHER_COLUMNS,
            "showers_sum": "Total convective shower precipitation for the day.",
            "precipitation_probability_max": "Highest hourly probability of precipitation during the day, as a percentage.",
            "uv_index_max": "Maximum UV index of the day, accounting for cloud cover.",
        },
    },
    "weather_current": {
        "description": "Current weather conditions for each configured location. One row per location per sync; use the append sync method to build a time series of snapshots.",
        "docs_url": "https://open-meteo.com/en/docs",
        "columns": {
            **_INJECTED_COLUMNS,
            **_HOURLY_WEATHER_COLUMNS,
            "interval": "Number of seconds the current conditions are valid for.",
            "showers": "Convective shower precipitation for the preceding hour.",
            "is_day": "1 while the sun is above the horizon at this location, 0 otherwise.",
        },
    },
    "air_quality_hourly": {
        "description": "Hourly air quality for each configured location, from the Open-Meteo Air Quality API (CAMS European and global models), covering the past 7 days and the next 5 days. Replaced on every sync, because the CAMS values are revised on every model run.",
        "docs_url": "https://open-meteo.com/en/docs/air-quality-api",
        "columns": {
            **_INJECTED_COLUMNS,
            "pm10": "Particulate matter up to 10 micrometres, close to surface (10 metres above ground).",
            "pm2_5": "Particulate matter up to 2.5 micrometres, close to surface (10 metres above ground).",
            "carbon_monoxide": "Carbon monoxide concentration close to surface.",
            "nitrogen_dioxide": "Nitrogen dioxide concentration close to surface.",
            "sulphur_dioxide": "Sulphur dioxide concentration close to surface.",
            "ozone": "Ozone concentration close to surface.",
            "ammonia": "Ammonia concentration close to surface. Europe only.",
            "dust": "Saharan dust particle concentration close to surface.",
            "aerosol_optical_depth": "Aerosol optical depth at 550 nm of the entire atmosphere column.",
            "uv_index": "UV index, accounting for cloud cover.",
            "uv_index_clear_sky": "UV index assuming clear sky.",
            "european_aqi": "European Air Quality Index, on a 0 (good) to over 100 (extremely poor) scale.",
            "us_aqi": "United States Air Quality Index, on a 0 (good) to over 300 (hazardous) scale.",
        },
    },
}
