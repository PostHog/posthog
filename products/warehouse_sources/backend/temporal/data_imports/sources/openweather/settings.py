from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Optional

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


@dataclass(frozen=True)
class HistoryWindow:
    """How a history endpoint that takes a ``start``/``end`` Unix range is read."""

    # Longest range one request covers. Each window is its own billed call.
    size: timedelta
    # Where a sync with no watermark starts: the first date the vendor has data for, or a lookback
    # from the sync time when how far back the data goes depends on the customer's plan.
    earliest_start: Optional[datetime] = None
    lookback: Optional[timedelta] = None


@dataclass(frozen=True)
class OpenWeatherEndpointConfig:
    name: str
    path: str
    # Where rows live in the JSON response. ``None`` means the response *is* the row
    # (current weather) or a list of rows (geocoding), ``"list"`` means rows are the elements
    # of the ``list`` array (forecast, air pollution).
    data_key: Optional[str]
    incremental_fields: list[IncrementalField] = field(default_factory=lambda: list(_DT_INCREMENTAL_FIELDS))
    # ``dt`` alone is not unique table-wide because rows aggregate across every configured
    # location, so the requested coordinates are part of the key.
    primary_keys: list[str] = field(default_factory=lambda: ["lat", "lon", "dt"])
    # Unix timestamp column each row is stamped with an ISO 8601 copy of (``<field>_iso``).
    timestamp_field: Optional[str] = "dt"
    # Stable datetime column used for partitioning (derived from ``timestamp_field``).
    partition_key: Optional[str] = "dt_iso"
    should_sync_default: bool = True
    description: Optional[str] = None
    # Host serving the path, when it is not the main API host.
    base_url: Optional[str] = None
    extra_params: dict[str, Any] = field(default_factory=dict)
    # Set for endpoints that take a ``start``/``end`` range; these filter server-side on ``dt``,
    # so they support true incremental sync.
    history_window: Optional[HistoryWindow] = None
    supports_append: bool = True
    # The row carries the coordinates of the place it describes (geocoding). They move to
    # ``place_lat``/``place_lon`` so the requested ``lat``/``lon`` key stays stable.
    has_place_coords: bool = False

    @property
    def supports_incremental(self) -> bool:
        return self.history_window is not None


# Opaque vendor version labels (never parsed or ordered). The Current Weather, 5 Day / 3 Hour
# Forecast and Air Pollution APIs are served under `2.5`; the One Call product runs on `3.0` and,
# since June 2026, `4.0` (One Call 2.5 was closed in June 2024).
API_VERSION_2_5 = "2.5"
API_VERSION_3_0 = "3.0"
API_VERSION_4_0 = "4.0"

# The Geocoding API is versioned on its own (`1.0`) and does not depend on the pinned product, so
# every version exposes it as a lookup table over the configured locations.
_SHARED_ENDPOINTS: dict[str, OpenWeatherEndpointConfig] = {
    "geocoding": OpenWeatherEndpointConfig(
        name="geocoding",
        path="/geo/1.0/reverse",
        data_key=None,
        extra_params={"limit": 1},
        incremental_fields=[],
        primary_keys=["lat", "lon"],
        timestamp_field=None,
        partition_key=None,
        supports_append=False,
        has_place_coords=True,
        description="Place name, state and country for each configured location, from reverse geocoding. "
        "One row per location.",
    ),
}

# The 2.5 general-purpose APIs. Each endpoint is its own request per location per sync, except the
# history endpoints, which make one request per window per location.
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
    "air_pollution_history": OpenWeatherEndpointConfig(
        name="air_pollution_history",
        path="/data/2.5/air_pollution/history",
        data_key="list",
        # The API documents no range limit per call; 30 days keeps each response a few hundred rows.
        history_window=HistoryWindow(size=timedelta(days=30), earliest_start=datetime(2020, 11, 27, tzinfo=UTC)),
        description="Hourly historical air quality for each configured location, from 27 November 2020. "
        "One row per hour per location.",
    ),
    "weather_history": OpenWeatherEndpointConfig(
        name="weather_history",
        path="/data/2.5/history/city",
        base_url="https://history.openweathermap.org",
        data_key="list",
        extra_params={"type": "hour"},
        # One week is the most the API returns per call. How far back data goes depends on the
        # subscription, so the first sync reads only the last week and later syncs extend it.
        history_window=HistoryWindow(size=timedelta(days=7), lookback=timedelta(days=7)),
        # Sold separately, so a key that passes validation can still get a 401 here.
        should_sync_default=False,
        description="Hourly historical weather observations for each configured location. The first sync reads "
        "the last 7 days and each sync after it adds the hours since. Needs a History API subscription.",
    ),
    **_SHARED_ENDPOINTS,
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
    "minutely": OpenWeatherEndpointConfig(
        name="minutely",
        path=_ONECALL_PATH,
        data_key="minutely",
        description="Minute-by-minute precipitation forecast for the next hour. One row per minute per location.",
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
    "alerts": OpenWeatherEndpointConfig(
        name="alerts",
        path=_ONECALL_PATH,
        data_key="alerts",
        # Alerts carry no `dt` or id; an issuer's alert is identified by its event and start time.
        # Full refresh only: an alert stays in the response while active, so append would insert it again
        # on every sync.
        incremental_fields=[],
        primary_keys=["lat", "lon", "sender_name", "event", "start"],
        timestamp_field="start",
        partition_key="start_iso",
        supports_append=False,
        description="Government weather alerts active at sync time for each configured location. One row per alert.",
    ),
    **_SHARED_ENDPOINTS,
}

# The One Call API 4.0 splits the 3.0 response into one endpoint per timeline step, so each table
# is its own request. Every endpoint answers with the same `{lat, lon, timezone, data: [...]}`
# envelope, and each `data` item carries its own `dt`, so the shared `[lat, lon, dt]` key and
# `dt_iso` partition still apply. `current`, `hourly` and `daily` keep the 3.0 table names so a
# 4.0 source exposes the same tables under different paths.
_ONECALL_4_BASE = "/data/4.0/onecall"
# Timeline endpoints answer a fixed-size page and offer `next`/`prev` URLs to walk further. We read
# the first page only: each page is billed as its own call, and one request per location per sync is
# the cost the source's setup copy promises.
OPENWEATHER_ENDPOINTS_4_0: dict[str, OpenWeatherEndpointConfig] = {
    "current": OpenWeatherEndpointConfig(
        name="current",
        path=f"{_ONECALL_4_BASE}/current",
        data_key="data",
        description="Current weather snapshot for each configured location, from the One Call API 4.0. "
        "One row per location per sync; use append sync to accumulate a time series.",
    ),
    "minutely": OpenWeatherEndpointConfig(
        name="minutely",
        path=f"{_ONECALL_4_BASE}/timeline/1min",
        data_key="data",
        description="Minute-by-minute precipitation forecast for the next hour. One row per minute per location.",
    ),
    "quarter_hourly": OpenWeatherEndpointConfig(
        name="quarter_hourly",
        path=f"{_ONECALL_4_BASE}/timeline/15min",
        data_key="data",
        description="15 minute weather forecast timeline. One row per 15 minute slot, up to 50 slots ahead "
        "of the sync time.",
    ),
    "hourly": OpenWeatherEndpointConfig(
        name="hourly",
        path=f"{_ONECALL_4_BASE}/timeline/1h",
        data_key="data",
        description="Hourly weather forecast timeline. One row per hour, up to 20 hours ahead of the sync time.",
    ),
    "daily": OpenWeatherEndpointConfig(
        name="daily",
        path=f"{_ONECALL_4_BASE}/timeline/1day",
        data_key="data",
        description="Daily weather forecast timeline. One row per day, up to 10 days ahead of the sync time.",
    ),
    **_SHARED_ENDPOINTS,
}

OPENWEATHER_ENDPOINTS_BY_VERSION: dict[str, dict[str, OpenWeatherEndpointConfig]] = {
    API_VERSION_2_5: OPENWEATHER_ENDPOINTS,
    API_VERSION_3_0: OPENWEATHER_ENDPOINTS_3_0,
    API_VERSION_4_0: OPENWEATHER_ENDPOINTS_4_0,
}

# The endpoint each version's credential probe hits — chosen so it exercises the same product
# (and subscription) the sync reads, not just any key-accepting endpoint. A 4.0 subscription is
# sold separately from a 3.0 one, so probing 4.0's own endpoint is what catches an unsubscribed key.
PROBE_ENDPOINT_BY_VERSION: dict[str, str] = {
    API_VERSION_2_5: "current_weather",
    API_VERSION_3_0: "current",
    API_VERSION_4_0: "current",
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
