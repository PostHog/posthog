from dataclasses import dataclass
from datetime import date
from typing import Literal

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField

BASE_URL = "https://meteostat.p.rapidapi.com"
API_HOST = "meteostat.p.rapidapi.com"

HOURLY_ENDPOINT = "Hourly"
DAILY_ENDPOINT = "Daily"
MONTHLY_ENDPOINT = "Monthly"
POINT_HOURLY_ENDPOINT = "PointHourly"
POINT_DAILY_ENDPOINT = "PointDaily"
POINT_MONTHLY_ENDPOINT = "PointMonthly"
STATIONS_ENDPOINT = "Stations"
NORMALS_ENDPOINT = "Normals"
POINT_NORMALS_ENDPOINT = "PointNormals"

# Station endpoints take a configured station ID; point endpoints take configured coordinates.
MeteostatTarget = Literal["station", "point"]


@dataclass(frozen=True)
class MeteostatEndpointConfig:
    name: str
    path: str
    target: MeteostatTarget
    date_field: str
    # Per-request date-range cap the vendor enforces, expressed as a chunk size so a
    # multi-year backfill is split into requests the API will actually accept.
    window_days: int
    primary_keys: list[str]
    description: str


METEOSTAT_ENDPOINTS: dict[str, MeteostatEndpointConfig] = {
    HOURLY_ENDPOINT: MeteostatEndpointConfig(
        name=HOURLY_ENDPOINT,
        path="/stations/hourly",
        target="station",
        date_field="time",
        # Vendor docs: "Hourly data can be queried for a maximum of 30 days per request."
        window_days=30,
        primary_keys=["station_id", "time"],
        description="Historical hourly weather observations for a station, with optional model gap-filling.",
    ),
    DAILY_ENDPOINT: MeteostatEndpointConfig(
        name=DAILY_ENDPOINT,
        path="/stations/daily",
        target="station",
        date_field="date",
        # Vendor docs: "Daily data can be queried for a maximum of 10 years per request."
        window_days=365 * 10,
        primary_keys=["station_id", "date"],
        description="Historical daily weather statistics for a station, aggregated from observations and model data.",
    ),
    MONTHLY_ENDPOINT: MeteostatEndpointConfig(
        name=MONTHLY_ENDPOINT,
        path="/stations/monthly",
        target="station",
        date_field="date",
        # The vendor's monthly docs don't publish an explicit per-request range cap; reuse the
        # documented daily cap as a conservative window size rather than guessing a larger one.
        window_days=365 * 10,
        primary_keys=["station_id", "date"],
        description="Historical monthly weather statistics for a station, aggregated from observations, daily records, and model data.",
    ),
    POINT_HOURLY_ENDPOINT: MeteostatEndpointConfig(
        name=POINT_HOURLY_ENDPOINT,
        path="/point/hourly",
        target="point",
        date_field="time",
        # Vendor docs: "Hourly data can be queried for a maximum of 30 days per request."
        window_days=30,
        primary_keys=["latitude", "longitude", "time"],
        description="Historical hourly weather observations for a geographic location, interpolated from nearby stations.",
    ),
    POINT_DAILY_ENDPOINT: MeteostatEndpointConfig(
        name=POINT_DAILY_ENDPOINT,
        path="/point/daily",
        target="point",
        date_field="date",
        # Vendor docs: "Daily data can be queried for a maximum of 10 years per request."
        window_days=365 * 10,
        primary_keys=["latitude", "longitude", "date"],
        description="Historical daily weather statistics for a geographic location, interpolated from nearby stations.",
    ),
    POINT_MONTHLY_ENDPOINT: MeteostatEndpointConfig(
        name=POINT_MONTHLY_ENDPOINT,
        path="/point/monthly",
        target="point",
        date_field="date",
        # No documented cap, as for the station monthly endpoint.
        window_days=365 * 10,
        primary_keys=["latitude", "longitude", "date"],
        description="Historical monthly weather statistics for a geographic location, interpolated from nearby stations.",
    ),
}


@dataclass(frozen=True)
class MeteostatSnapshotEndpointConfig:
    """An endpoint that returns the full dataset for a target in one request, with no date range."""

    name: str
    path: str
    target: MeteostatTarget
    # Query parameter that carries the station ID. Unused for point endpoints.
    station_param: str
    supports_units: bool
    primary_keys: list[str]
    description: str


METEOSTAT_SNAPSHOT_ENDPOINTS: dict[str, MeteostatSnapshotEndpointConfig] = {
    STATIONS_ENDPOINT: MeteostatSnapshotEndpointConfig(
        name=STATIONS_ENDPOINT,
        path="/stations/meta",
        target="station",
        station_param="id",
        supports_units=False,
        primary_keys=["station_id"],
        description="Meta data for each configured weather station: name, country, region, identifiers, location, time zone, and data inventory.",
    ),
    NORMALS_ENDPOINT: MeteostatSnapshotEndpointConfig(
        name=NORMALS_ENDPOINT,
        path="/stations/normals",
        target="station",
        station_param="station",
        supports_units=True,
        # Without a start and end year the API returns twelve monthly rows for every reference period.
        primary_keys=["station_id", "start", "end", "month"],
        description="Climate normals for a station: long-term monthly averages for each reference period.",
    ),
    POINT_NORMALS_ENDPOINT: MeteostatSnapshotEndpointConfig(
        name=POINT_NORMALS_ENDPOINT,
        path="/point/normals",
        target="point",
        station_param="station",
        supports_units=True,
        primary_keys=["latitude", "longitude", "start", "end", "month"],
        description="Climate normals for a geographic location: long-term monthly averages for each reference period.",
    ),
}

ENDPOINTS = (
    HOURLY_ENDPOINT,
    DAILY_ENDPOINT,
    MONTHLY_ENDPOINT,
    STATIONS_ENDPOINT,
    NORMALS_ENDPOINT,
    POINT_HOURLY_ENDPOINT,
    POINT_DAILY_ENDPOINT,
    POINT_MONTHLY_ENDPOINT,
    POINT_NORMALS_ENDPOINT,
)

POINT_ENDPOINTS = frozenset(
    [name for name, config in METEOSTAT_ENDPOINTS.items() if config.target == "point"]
    + [name for name, config in METEOSTAT_SNAPSHOT_ENDPOINTS.items() if config.target == "point"]
)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: [incremental_field(config.date_field)] for name, config in METEOSTAT_ENDPOINTS.items()
}

UNITS_OPTIONS = (
    ("metric", "Metric (°C, mm, km/h)"),
    ("imperial", "Imperial (°F, in, mph)"),
    ("scientific", "Scientific (K, mm, m/s)"),
)
DEFAULT_UNITS = "metric"

# A weather station has no PostHog-visible creation date, so there's no vendor-documented
# earliest-record date to default to. This bounds how far back a first (full-refresh) sync
# reaches, keeping the request count predictable against the RapidAPI free tier's 500
# requests/month cap. Users can set an earlier start date once they've sized their plan.
DEFAULT_START_DATE = date(2015, 1, 1)

# Hard floor for any configured start date, including previously stored configurations. Without
# this, an authenticated user (or a stale stored config) can set an arbitrarily old start date —
# e.g. `0001-01-01` — and, fanned out across MAX_STATIONS, schedule an effectively unbounded
# number of sequential request windows and Redis checkpoints against a single resumable sync.
# Automated station networks with any meaningful density don't predate this by much, so it costs
# little real history while keeping the worst case bounded and predictable.
MINIMUM_START_DATE = date(1950, 1, 1)

# Historical values can be revised by the underlying weather services for several days after
# they first land, so incremental syncs re-fetch a trailing window instead of resuming exactly
# at the last synced date.
INCREMENTAL_OVERLAP_DAYS = 7

# Each station costs at least one request per date window; an unbounded list can silently burn
# a whole month's free-tier quota in a single sync.
MAX_STATIONS = 25
MAX_LOCATIONS = 25
