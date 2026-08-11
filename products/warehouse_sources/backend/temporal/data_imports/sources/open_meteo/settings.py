from dataclasses import dataclass, field
from typing import Any

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import PartitionFormat
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Open-Meteo splits its products across subdomains rather than paths. Commercial customers get a
# `customer-` prefixed host with reserved capacity, selected by supplying an API key.
# https://open-meteo.com/en/pricing
HOSTS: dict[str, tuple[str, str]] = {
    "forecast": ("https://api.open-meteo.com", "https://customer-api.open-meteo.com"),
    "archive": ("https://archive-api.open-meteo.com", "https://customer-archive-api.open-meteo.com"),
    "air_quality": ("https://air-quality-api.open-meteo.com", "https://customer-air-quality-api.open-meteo.com"),
}

# Every response carries a `time` series; the connector derives a tz-aware UTC datetime from it so
# the incremental watermark and the datetime partitioner both get a real timestamp rather than the
# API's abbreviated `2026-01-01T00:00` string.
_TIME_INCREMENTAL_FIELDS: list[IncrementalField] = [
    incremental_field("time_utc", IncrementalFieldType.DateTime),
]

# ERA5 reanalysis lands with roughly a five-day delay and recent days keep being revised, so each
# incremental run re-reads a trailing week. Incremental merge makes the overlap idempotent.
ARCHIVE_LOOKBACK_SECONDS = 7 * 24 * 60 * 60

# Variable catalogs, taken from the endpoint docs linked on each entry below. Kept fixed rather than
# user-supplied so the table columns (and their canonical descriptions) stay stable across teams.
_ARCHIVE_HOURLY_VARIABLES = (
    "temperature_2m",
    "relative_humidity_2m",
    "dew_point_2m",
    "apparent_temperature",
    "precipitation",
    "rain",
    "snowfall",
    "snow_depth",
    "weather_code",
    "pressure_msl",
    "surface_pressure",
    "cloud_cover",
    "wind_speed_10m",
    "wind_direction_10m",
    "wind_gusts_10m",
    "shortwave_radiation",
)

_ARCHIVE_DAILY_VARIABLES = (
    "weather_code",
    "temperature_2m_max",
    "temperature_2m_min",
    "temperature_2m_mean",
    "apparent_temperature_max",
    "apparent_temperature_min",
    "sunrise",
    "sunset",
    "daylight_duration",
    "sunshine_duration",
    "precipitation_sum",
    "rain_sum",
    "snowfall_sum",
    "precipitation_hours",
    "wind_speed_10m_max",
    "wind_gusts_10m_max",
    "wind_direction_10m_dominant",
    "shortwave_radiation_sum",
    "et0_fao_evapotranspiration",
)

_FORECAST_HOURLY_VARIABLES = (
    "temperature_2m",
    "relative_humidity_2m",
    "dew_point_2m",
    "apparent_temperature",
    "precipitation_probability",
    "precipitation",
    "rain",
    "showers",
    "snowfall",
    "snow_depth",
    "weather_code",
    "pressure_msl",
    "surface_pressure",
    "cloud_cover",
    "visibility",
    "wind_speed_10m",
    "wind_direction_10m",
    "wind_gusts_10m",
    "uv_index",
    "is_day",
)

_FORECAST_DAILY_VARIABLES = (
    "weather_code",
    "temperature_2m_max",
    "temperature_2m_min",
    "apparent_temperature_max",
    "apparent_temperature_min",
    "sunrise",
    "sunset",
    "daylight_duration",
    "sunshine_duration",
    "uv_index_max",
    "precipitation_sum",
    "rain_sum",
    "showers_sum",
    "snowfall_sum",
    "precipitation_hours",
    "precipitation_probability_max",
    "wind_speed_10m_max",
    "wind_gusts_10m_max",
    "wind_direction_10m_dominant",
    "shortwave_radiation_sum",
    "et0_fao_evapotranspiration",
)

_CURRENT_VARIABLES = (
    "temperature_2m",
    "relative_humidity_2m",
    "apparent_temperature",
    "is_day",
    "precipitation",
    "rain",
    "showers",
    "snowfall",
    "weather_code",
    "cloud_cover",
    "pressure_msl",
    "surface_pressure",
    "wind_speed_10m",
    "wind_direction_10m",
    "wind_gusts_10m",
)

_AIR_QUALITY_HOURLY_VARIABLES = (
    "pm10",
    "pm2_5",
    "carbon_monoxide",
    "nitrogen_dioxide",
    "sulphur_dioxide",
    "ozone",
    "ammonia",
    "dust",
    "aerosol_optical_depth",
    "uv_index",
    "uv_index_clear_sky",
    "european_aqi",
    "us_aqi",
)


@dataclass(frozen=True)
class OpenMeteoEndpointConfig:
    name: str
    # Key into `HOSTS`.
    host: str
    path: str
    # Which block of the response holds the data: `hourly`/`daily` are column-oriented arrays that
    # get pivoted into rows, `current` is a single flat object.
    block: str
    variables: tuple[str, ...]
    description: str
    # True for the archive endpoints, which take `start_date`/`end_date` and are therefore walked in
    # date windows. False for the rolling forecast endpoints, which take `past_days`/`forecast_days`.
    windowed: bool = False
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    supports_incremental: bool = False
    supports_append: bool = False
    # `time_utc` alone is not unique table-wide because rows aggregate across every configured
    # location, so the location is part of the key.
    primary_keys: list[str] = field(default_factory=lambda: ["location_id", "time_utc"])
    partition_format: PartitionFormat = "month"
    default_incremental_lookback_seconds: int | None = None
    # Merged into every request for this endpoint.
    extra_params: dict[str, Any] = field(default_factory=dict)


OPEN_METEO_ENDPOINTS: dict[str, OpenMeteoEndpointConfig] = {
    "weather_archive_hourly": OpenMeteoEndpointConfig(
        name="weather_archive_hourly",
        host="archive",
        path="/v1/archive",
        block="hourly",
        variables=_ARCHIVE_HOURLY_VARIABLES,
        windowed=True,
        incremental_fields=list(_TIME_INCREMENTAL_FIELDS),
        supports_incremental=True,
        supports_append=True,
        partition_format="month",
        default_incremental_lookback_seconds=ARCHIVE_LOOKBACK_SECONDS,
        description="Hourly historical weather (ERA5 reanalysis, 1940 onwards) for each configured location. "
        "https://open-meteo.com/en/docs/historical-weather-api",
    ),
    "weather_archive_daily": OpenMeteoEndpointConfig(
        name="weather_archive_daily",
        host="archive",
        path="/v1/archive",
        block="daily",
        variables=_ARCHIVE_DAILY_VARIABLES,
        windowed=True,
        incremental_fields=list(_TIME_INCREMENTAL_FIELDS),
        supports_incremental=True,
        supports_append=True,
        partition_format="month",
        default_incremental_lookback_seconds=ARCHIVE_LOOKBACK_SECONDS,
        description="Daily aggregated historical weather (ERA5 reanalysis, 1940 onwards) for each configured "
        "location. https://open-meteo.com/en/docs/historical-weather-api",
    ),
    "weather_forecast_hourly": OpenMeteoEndpointConfig(
        name="weather_forecast_hourly",
        host="forecast",
        path="/v1/forecast",
        block="hourly",
        variables=_FORECAST_HOURLY_VARIABLES,
        partition_format="week",
        description="Hourly weather forecast for each configured location, covering the past 7 days and the next "
        "16 days. Full refresh only, because forecast values for a given hour are revised on every model run. "
        "https://open-meteo.com/en/docs",
        extra_params={"past_days": 7, "forecast_days": 16},
    ),
    "weather_forecast_daily": OpenMeteoEndpointConfig(
        name="weather_forecast_daily",
        host="forecast",
        path="/v1/forecast",
        block="daily",
        variables=_FORECAST_DAILY_VARIABLES,
        partition_format="week",
        description="Daily weather forecast for each configured location, covering the past 7 days and the next "
        "16 days. Full refresh only, because forecast values for a given day are revised on every model run. "
        "https://open-meteo.com/en/docs",
        extra_params={"past_days": 7, "forecast_days": 16},
    ),
    "weather_current": OpenMeteoEndpointConfig(
        name="weather_current",
        host="forecast",
        path="/v1/forecast",
        block="current",
        variables=_CURRENT_VARIABLES,
        incremental_fields=list(_TIME_INCREMENTAL_FIELDS),
        # There is no server-side timestamp filter for current conditions, so this is not true
        # incremental sync. Append works: each run polls one fresh snapshot per location and the
        # observation time always moves forward, building a time series across runs.
        supports_append=True,
        partition_format="week",
        description="Current weather conditions for each configured location. One row per location per sync; "
        "use the append sync method to accumulate a time series. https://open-meteo.com/en/docs",
        extra_params={"forecast_days": 1},
    ),
    "air_quality_hourly": OpenMeteoEndpointConfig(
        name="air_quality_hourly",
        host="air_quality",
        path="/v1/air-quality",
        block="hourly",
        variables=_AIR_QUALITY_HOURLY_VARIABLES,
        partition_format="week",
        description="Hourly air quality (particulates, gases and AQI) for each configured location, covering the "
        "past 7 days and the next 5 days. Full refresh only, because the CAMS values are revised on every model "
        "run. https://open-meteo.com/en/docs/air-quality-api",
        extra_params={"past_days": 7, "forecast_days": 5},
    ),
}

ENDPOINTS = tuple(OPEN_METEO_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in OPEN_METEO_ENDPOINTS.items()
}
