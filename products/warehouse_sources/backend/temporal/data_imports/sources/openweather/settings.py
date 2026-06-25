from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Every OpenWeather row carries a `dt` (Unix UTC timestamp) describing the point in time the
# observation/forecast slot refers to. It never changes for a given row, so it doubles as the
# append cursor and a stable partition key. We expose it both as the raw integer (`dt`) and as a
# derived ISO 8601 string (`dt_iso`) so the datetime partitioner has a parseable column.
_DT_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "dt",
        "type": IncrementalFieldType.Integer,
        "field": "dt",
        "field_type": IncrementalFieldType.Integer,
    },
]


@dataclass
class OpenWeatherEndpointConfig:
    name: str
    path: str
    # Where rows live in the JSON response. ``None`` means the response *is* the row
    # (current weather), ``"list"`` means rows are the elements of the ``list`` array
    # (forecast, air pollution).
    data_key: Optional[str]
    incremental_fields: list[IncrementalField] = field(default_factory=lambda: list(_DT_INCREMENTAL_FIELDS))
    # ``dt`` alone is not unique table-wide because rows aggregate across every configured
    # location, so the requested coordinates are part of the key.
    primary_keys: list[str] = field(default_factory=lambda: ["lat", "lon", "dt"])
    # Stable datetime column used for partitioning (derived from ``dt``).
    partition_key: str = "dt_iso"
    should_sync_default: bool = True
    description: Optional[str] = None


OPENWEATHER_ENDPOINTS: dict[str, OpenWeatherEndpointConfig] = {
    "current_weather": OpenWeatherEndpointConfig(
        name="current_weather",
        path="/data/2.5/weather",
        data_key=None,
        description="Current weather snapshot for each configured location. One row per location per sync; "
        "use append sync to accumulate a time series.",
    ),
    "forecast": OpenWeatherEndpointConfig(
        name="forecast",
        path="/data/2.5/forecast",
        data_key="list",
        description="5 day / 3 hour weather forecast. One row per 3-hour slot per location.",
    ),
    "air_pollution": OpenWeatherEndpointConfig(
        name="air_pollution",
        path="/data/2.5/air_pollution",
        data_key="list",
        description="Current air quality (AQI and pollutant concentrations) for each configured location.",
    ),
    "air_pollution_forecast": OpenWeatherEndpointConfig(
        name="air_pollution_forecast",
        path="/data/2.5/air_pollution/forecast",
        data_key="list",
        description="Hourly air-quality forecast for each configured location.",
    ),
}

ENDPOINTS = tuple(OPENWEATHER_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in OPENWEATHER_ENDPOINTS.items()
}
