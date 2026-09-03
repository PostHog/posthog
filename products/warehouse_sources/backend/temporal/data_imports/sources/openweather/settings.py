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


# Opaque vendor version labels (never parsed or ordered). The Current Weather, 5 Day / 3 Hour
# Forecast and Air Pollution APIs are served under `2.5`; the One Call product's current stable
# release is `3.0` (One Call 2.5 was closed in June 2024).
API_VERSION_2_5 = "2.5"
API_VERSION_3_0 = "3.0"

# The 2.5 general-purpose APIs. Each endpoint is its own request per location per sync.
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

# The One Call API 3.0 serves current weather plus forecasts from a single `/data/3.0/onecall`
# response; each table extracts one section (`current` object, `hourly`/`daily` lists) and every
# item carries its own `dt`, so the shared `[lat, lon, dt]` key and `dt_iso` partition still apply.
_ONECALL_PATH = "/data/3.0/onecall"
OPENWEATHER_ENDPOINTS_3_0: dict[str, OpenWeatherEndpointConfig] = {
    "current": OpenWeatherEndpointConfig(
        name="current",
        path=_ONECALL_PATH,
        data_key="current",
        description="Current weather snapshot for each configured location, from the One Call API 3.0. "
        "One row per location per sync; use append sync to accumulate a time series.",
    ),
    "hourly": OpenWeatherEndpointConfig(
        name="hourly",
        path=_ONECALL_PATH,
        data_key="hourly",
        description="Hourly weather forecast (48 hours) for each configured location. One row per hour.",
    ),
    "daily": OpenWeatherEndpointConfig(
        name="daily",
        path=_ONECALL_PATH,
        data_key="daily",
        description="Daily weather forecast (8 days) for each configured location. One row per day.",
    ),
}

OPENWEATHER_ENDPOINTS_BY_VERSION: dict[str, dict[str, OpenWeatherEndpointConfig]] = {
    API_VERSION_2_5: OPENWEATHER_ENDPOINTS,
    API_VERSION_3_0: OPENWEATHER_ENDPOINTS_3_0,
}

# The endpoint each version's credential probe hits — chosen so it exercises the same product
# (and subscription) the sync reads, not just any key-accepting endpoint.
PROBE_ENDPOINT_BY_VERSION: dict[str, str] = {
    API_VERSION_2_5: "current_weather",
    API_VERSION_3_0: "current",
}


def endpoints_for_version(api_version: str) -> dict[str, OpenWeatherEndpointConfig]:
    """Endpoint set for a resolved vendor API version.

    Raises on an unknown label rather than falling back to a default — sending the wrong version's
    request paths would silently drift a pinned source off its version.
    """
    try:
        return OPENWEATHER_ENDPOINTS_BY_VERSION[api_version]
    except KeyError:
        raise ValueError(f"Unsupported OpenWeather API version: {api_version!r}")
