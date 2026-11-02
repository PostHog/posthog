from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Every row carries `dt_iso`, a derived ISO 8601 UTC timestamp describing the point in time the
# observation/forecast slot refers to (parsed from the API's `dateTime` string or `date` object). It
# never changes for a given row, so it doubles as the append cursor and a stable partition key.
_DT_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "dt_iso",
        "type": IncrementalFieldType.DateTime,
        "field": "dt_iso",
        "field_type": IncrementalFieldType.DateTime,
    },
]


@dataclass
class BreezometerEndpointConfig:
    name: str
    # "air_quality" -> POST with a JSON body; "pollen" -> GET with query params.
    request_kind: Literal["air_quality", "pollen"]
    base_url: str
    path: str
    # Where rows live in the JSON response. ``None`` means the response *is* the row (current
    # conditions), otherwise rows are the elements of the array under this key.
    data_key: Optional[str]
    # Raw field on each row carrying the timestamp, and how to parse it into `dt_iso`.
    timestamp_field: str
    timestamp_kind: Literal["datetime_str", "date_obj"]
    # Extra computations requested from the Air Quality API to enrich the response (ignored for pollen).
    extra_computations: list[str] = field(default_factory=list)
    incremental_fields: list[IncrementalField] = field(default_factory=lambda: list(_DT_INCREMENTAL_FIELDS))
    # `dt_iso` alone is not unique table-wide because rows aggregate across every configured location,
    # so the requested coordinates are part of the key.
    primary_keys: list[str] = field(default_factory=lambda: ["latitude", "longitude", "dt_iso"])
    # Stable datetime column used for partitioning (derived from the raw timestamp).
    partition_key: str = "dt_iso"
    should_sync_default: bool = True
    description: Optional[str] = None


# Common Air Quality extra computations. Kept to widely-supported values; the API enriches the
# response with these where available. Based on the public Air Quality API docs — see the PR notes:
# the exact accepted enum could not be curl-verified without a key.
_AIR_QUALITY_EXTRA_COMPUTATIONS = [
    "HEALTH_RECOMMENDATIONS",
    "DOMINANT_POLLUTANT_CONCENTRATION",
    "POLLUTANT_CONCENTRATION",
    "LOCAL_AQI",
    "POLLUTANT_ADDITIONAL_INFO",
]


BREEZOMETER_ENDPOINTS: dict[str, BreezometerEndpointConfig] = {
    "air_quality_current": BreezometerEndpointConfig(
        name="air_quality_current",
        request_kind="air_quality",
        base_url="https://airquality.googleapis.com",
        path="/v1/currentConditions:lookup",
        data_key=None,
        timestamp_field="dateTime",
        timestamp_kind="datetime_str",
        extra_computations=_AIR_QUALITY_EXTRA_COMPUTATIONS,
        description="Current air-quality conditions (AQI indexes and pollutant concentrations) for each "
        "configured location. One row per location per sync; use append sync to accumulate a time series.",
    ),
    "air_quality_forecast": BreezometerEndpointConfig(
        name="air_quality_forecast",
        request_kind="air_quality",
        base_url="https://airquality.googleapis.com",
        path="/v1/forecast:lookup",
        data_key="hourlyForecasts",
        timestamp_field="dateTime",
        timestamp_kind="datetime_str",
        extra_computations=_AIR_QUALITY_EXTRA_COMPUTATIONS,
        description="Hourly air-quality forecast (up to 96 hours ahead) for each configured location. "
        "One row per forecast hour.",
    ),
    "air_quality_history": BreezometerEndpointConfig(
        name="air_quality_history",
        request_kind="air_quality",
        base_url="https://airquality.googleapis.com",
        path="/v1/history:lookup",
        data_key="hoursInfo",
        timestamp_field="dateTime",
        timestamp_kind="datetime_str",
        extra_computations=_AIR_QUALITY_EXTRA_COMPUTATIONS,
        description="Historical hourly air quality (the last 24 hours) for each configured location. One row per hour.",
    ),
    "pollen_forecast": BreezometerEndpointConfig(
        name="pollen_forecast",
        request_kind="pollen",
        base_url="https://pollen.googleapis.com",
        path="/v1/forecast:lookup",
        data_key="dailyInfo",
        timestamp_field="date",
        timestamp_kind="date_obj",
        description="Daily pollen forecast (up to 5 days ahead) for each configured location, covering "
        "pollen types and plant-level indexes. One row per day.",
    ),
}

ENDPOINTS = tuple(BREEZOMETER_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in BREEZOMETER_ENDPOINTS.items()
}
