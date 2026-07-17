from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Injected by the connector on every row (not part of the raw API response).
_INJECTED_COLUMNS = {
    "lat": "Requested latitude of the location (as configured, not the station OpenWeather snapped to).",
    "lon": "Requested longitude of the location (as configured, not the station OpenWeather snapped to).",
    "location_label": "Optional user-supplied label for the configured location.",
    "dt_iso": "ISO 8601 UTC timestamp derived from `dt`; used as the partition key.",
    "dt": "Time of the data, Unix UTC timestamp.",
}

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "current_weather": {
        "description": "Current weather snapshot for a configured location, from the OpenWeather Current Weather Data API.",
        "docs_url": "https://openweathermap.org/current",
        "columns": {
            **_INJECTED_COLUMNS,
            "coord": "Location coordinates echoed by the API ({lon, lat}).",
            "weather": "List of weather condition objects (id, main, description, icon).",
            "main": "Main measurements: temp, feels_like, temp_min, temp_max, pressure, humidity.",
            "visibility": "Visibility in metres (max 10000).",
            "wind": "Wind data: speed, deg, gust.",
            "clouds": "Cloudiness, as a percentage.",
            "rain": "Rain volume for the last 1h/3h, where available.",
            "snow": "Snow volume for the last 1h/3h, where available.",
            "sys": "System data: country, sunrise, sunset.",
            "timezone": "Shift in seconds from UTC for the location.",
            "id": "OpenWeather city ID.",
            "name": "City name resolved by OpenWeather.",
            "cod": "Internal API response code.",
        },
    },
    "forecast": {
        "description": "5 day / 3 hour weather forecast for a configured location; one row per 3-hour slot.",
        "docs_url": "https://openweathermap.org/forecast5",
        "columns": {
            **_INJECTED_COLUMNS,
            "dt": "Time of the forecasted data slot, Unix UTC timestamp.",
            "main": "Forecasted measurements: temp, feels_like, pressure, humidity, temp_kf.",
            "weather": "List of weather condition objects for the slot.",
            "clouds": "Cloudiness, as a percentage.",
            "wind": "Wind data: speed, deg, gust.",
            "visibility": "Average visibility in metres.",
            "pop": "Probability of precipitation, from 0 to 1.",
            "rain": "Rain volume for the 3-hour slot, where available.",
            "snow": "Snow volume for the 3-hour slot, where available.",
            "sys": "Part of day (`pod`): `n` for night, `d` for day.",
            "dt_txt": "Forecast slot time as a human-readable UTC string.",
            "city": "City metadata for the forecast (id, name, coord, country, timezone, sunrise, sunset).",
        },
    },
    "air_pollution": {
        "description": "Current air quality (AQI and pollutant concentrations) for a configured location.",
        "docs_url": "https://openweathermap.org/api/air-pollution",
        "columns": {
            **_INJECTED_COLUMNS,
            "dt": "Time of the air-quality data, Unix UTC timestamp.",
            "main": "Air Quality Index: `aqi` from 1 (Good) to 5 (Very Poor).",
            "components": "Pollutant concentrations in μg/m³: co, no, no2, o3, so2, pm2_5, pm10, nh3.",
        },
    },
    "air_pollution_forecast": {
        "description": "Hourly air-quality forecast for a configured location.",
        "docs_url": "https://openweathermap.org/api/air-pollution",
        "columns": {
            **_INJECTED_COLUMNS,
            "dt": "Time of the forecasted air-quality slot, Unix UTC timestamp.",
            "main": "Forecasted Air Quality Index: `aqi` from 1 (Good) to 5 (Very Poor).",
            "components": "Forecasted pollutant concentrations in μg/m³: co, no, no2, o3, so2, pm2_5, pm10, nh3.",
        },
    },
}
