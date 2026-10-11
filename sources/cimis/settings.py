from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# CIMIS (California Irrigation Management Information System) Web API base URL.
# https://et.water.ca.gov/Rest/Index
CIMIS_BASE_URL = "https://et.water.ca.gov/api"

# CIMIS rejects a single /api/data request that would return more than ~1750 records (ERR2112).
# We chunk by date window and target set to stay comfortably under that ceiling.
CIMIS_RECORD_CAP = 1700

# Earliest date CIMIS has data for. Used as the backfill floor when the user doesn't pin a start date.
CIMIS_DATA_EPOCH = "1982-06-07"

# Default measurement items requested per scope when the user doesn't override them. These are the
# core, broadly-available CIMIS data item codes; the response flattener handles whatever the API
# actually returns, so this list only governs which measurements we ask for.
DEFAULT_DAILY_DATA_ITEMS = [
    "day-asce-eto",
    "day-eto",
    "day-precip",
    "day-sol-rad-avg",
    "day-vap-pres-avg",
    "day-air-tmp-max",
    "day-air-tmp-min",
    "day-air-tmp-avg",
    "day-rel-hum-max",
    "day-rel-hum-min",
    "day-rel-hum-avg",
    "day-dew-pnt",
    "day-wind-spd-avg",
    "day-wind-run",
    "day-soil-tmp-avg",
]
DEFAULT_HOURLY_DATA_ITEMS = [
    "hly-air-tmp",
    "hly-dew-pnt",
    "hly-eto",
    "hly-asce-eto",
    "hly-precip",
    "hly-rel-hum",
    "hly-res-wind",
    "hly-soil-tmp",
    "hly-sol-rad",
    "hly-vap-pres",
    "hly-wind-dir",
    "hly-wind-spd",
]


@dataclass
class CimisEndpointConfig:
    name: str
    path: str
    primary_keys: list[str]
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # JSON key wrapping the list of rows in the response body (e.g. "Stations", "ZipCodes").
    response_key: str = ""
    # /api/data endpoints are date-windowed pulls keyed by station targets; the metadata endpoints
    # are single full-refresh requests.
    is_data_endpoint: bool = False
    # "daily" or "hourly" — only meaningful for data endpoints.
    scope: Optional[str] = None
    partition_key: Optional[str] = None
    should_sync_default: bool = True


_DATE_INCREMENTAL_FIELD: IncrementalField = {
    "label": "Date",
    "type": IncrementalFieldType.Date,
    "field": "Date",
    "field_type": IncrementalFieldType.Date,
}


CIMIS_ENDPOINTS: dict[str, CimisEndpointConfig] = {
    "stations": CimisEndpointConfig(
        name="stations",
        path="/station",
        response_key="Stations",
        primary_keys=["StationNbr"],
    ),
    "station_zipcodes": CimisEndpointConfig(
        name="station_zipcodes",
        path="/stationzipcode",
        response_key="ZipCodes",
        # A zip code maps to one station, but the same station owns many zip codes, so the row is
        # only unique on the pair.
        primary_keys=["StationNbr", "ZipCode"],
    ),
    "spatial_zipcodes": CimisEndpointConfig(
        name="spatial_zipcodes",
        path="/spatialzipcode",
        response_key="ZipCodes",
        primary_keys=["ZipCode"],
    ),
    "daily_data": CimisEndpointConfig(
        name="daily_data",
        path="/data",
        is_data_endpoint=True,
        scope="daily",
        # One record per station per day. Date is a stable, monotonic field.
        primary_keys=["Station", "Date"],
        partition_key="Date",
        incremental_fields=[_DATE_INCREMENTAL_FIELD],
    ),
    "hourly_data": CimisEndpointConfig(
        name="hourly_data",
        path="/data",
        is_data_endpoint=True,
        scope="hourly",
        # One record per station per hour. Hour disambiguates within a day.
        primary_keys=["Station", "Date", "Hour"],
        partition_key="Date",
        incremental_fields=[_DATE_INCREMENTAL_FIELD],
    ),
}

ENDPOINTS = tuple(CIMIS_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in CIMIS_ENDPOINTS.items()
}
