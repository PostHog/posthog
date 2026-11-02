from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# How an endpoint is fetched:
# - "list": a top-level paginated list (e.g. /v3/locations). Full refresh.
# - "sensors": derived by walking /v3/locations and flattening each location's embedded
#   `sensors` array into one row per sensor. Full refresh (single locations walk, cheap).
# - "measurement": fanned out per sensor (/v3/sensors/{sensors_id}/...). Incremental via the
#   API's server-side datetime filter. Request-heavy (one paginated fetch per sensor), so opt-in.
# - "location_fanout" / "sensor_fanout": fanned out per location (/v3/locations/{locations_id}/...)
#   or per sensor (/v3/sensors/{sensors_id}/...). Full refresh. Request-heavy, so opt-in.
EndpointKind = Literal["list", "sensors", "measurement", "location_fanout", "sensor_fanout"]


def _datetime_incremental_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


@dataclass(frozen=True)
class OpenAQEndpointConfig:
    name: str
    kind: EndpointKind
    # API path. Fan-out endpoints use a `{sensors_id}` or `{locations_id}` placeholder.
    path: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    partition_key: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Query-param prefix for the measurement time filter. The raw + hourly endpoints use
    # `datetime_from`/`datetime_to`; the daily + yearly aggregates use `date_from`/`date_to`.
    time_param_prefix: Optional[str] = None
    should_sync_default: bool = True
    sort_mode: Optional[Literal["asc", "desc"]] = "asc"


OPENAQ_ENDPOINTS: dict[str, OpenAQEndpointConfig] = {
    "locations": OpenAQEndpointConfig(name="locations", kind="list", path="/v3/locations"),
    "parameters": OpenAQEndpointConfig(name="parameters", kind="list", path="/v3/parameters"),
    "countries": OpenAQEndpointConfig(name="countries", kind="list", path="/v3/countries"),
    "providers": OpenAQEndpointConfig(name="providers", kind="list", path="/v3/providers"),
    "instruments": OpenAQEndpointConfig(name="instruments", kind="list", path="/v3/instruments"),
    "manufacturers": OpenAQEndpointConfig(name="manufacturers", kind="list", path="/v3/manufacturers"),
    "owners": OpenAQEndpointConfig(name="owners", kind="list", path="/v3/owners"),
    "licenses": OpenAQEndpointConfig(name="licenses", kind="list", path="/v3/licenses"),
    # Sensors have no top-level list endpoint, so we materialize them from the embedded
    # `sensors` array on each location. Sensor ids are globally unique, so ["id"] is table-wide unique.
    "sensors": OpenAQEndpointConfig(name="sensors", kind="sensors", path="/v3/locations"),
    # Per-sensor measurement streams. A measurement has no id of its own, so the primary key is
    # (sensor_id, period start). Partition/incremental on `datetime_from` — the reading's period
    # start, a stable time-ending value that never shifts once written.
    "measurements": OpenAQEndpointConfig(
        name="measurements",
        kind="measurement",
        path="/v3/sensors/{sensors_id}/measurements",
        primary_keys=["sensor_id", "datetime_from"],
        partition_key="datetime_from",
        incremental_fields=[_datetime_incremental_field("datetime_from")],
        time_param_prefix="datetime",
        should_sync_default=False,
    ),
    "measurements_hourly": OpenAQEndpointConfig(
        name="measurements_hourly",
        kind="measurement",
        path="/v3/sensors/{sensors_id}/hours",
        primary_keys=["sensor_id", "datetime_from"],
        partition_key="datetime_from",
        incremental_fields=[_datetime_incremental_field("datetime_from")],
        time_param_prefix="datetime",
        should_sync_default=False,
    ),
    "measurements_daily": OpenAQEndpointConfig(
        name="measurements_daily",
        kind="measurement",
        path="/v3/sensors/{sensors_id}/days",
        primary_keys=["sensor_id", "datetime_from"],
        partition_key="datetime_from",
        incremental_fields=[_datetime_incremental_field("datetime_from")],
        time_param_prefix="date",
        should_sync_default=False,
    ),
    "measurements_yearly": OpenAQEndpointConfig(
        name="measurements_yearly",
        kind="measurement",
        path="/v3/sensors/{sensors_id}/years",
        primary_keys=["sensor_id", "datetime_from"],
        partition_key="datetime_from",
        incremental_fields=[_datetime_incremental_field("datetime_from")],
        time_param_prefix="date",
        should_sync_default=False,
        # Rows are paged per sensor, so the run is not one ascending series across the table.
        sort_mode=None,
    ),
    # One row per sensor holding its most recent reading. The reading time moves on every sync, so the
    # table is not partitioned.
    "location_latest": OpenAQEndpointConfig(
        name="location_latest",
        kind="location_fanout",
        path="/v3/locations/{locations_id}/latest",
        primary_keys=["location_id", "sensor_id"],
        should_sync_default=False,
        sort_mode=None,
    ),
    # Flags carry no id. A flag is a period of a given type, so (parent, flag type, period start) keys it.
    # Full refresh only: an open flag's end moves forward, and the API's datetime filter applies to the
    # flag period, so an incremental read on the start would miss those updates.
    "location_flags": OpenAQEndpointConfig(
        name="location_flags",
        kind="location_fanout",
        path="/v3/locations/{locations_id}/flags",
        primary_keys=["location_id", "flag_type_id", "datetime_from"],
        partition_key="datetime_from",
        should_sync_default=False,
        sort_mode=None,
    ),
    "sensor_flags": OpenAQEndpointConfig(
        name="sensor_flags",
        kind="sensor_fanout",
        path="/v3/sensors/{sensors_id}/flags",
        primary_keys=["sensor_id", "flag_type_id", "datetime_from"],
        partition_key="datetime_from",
        should_sync_default=False,
        sort_mode=None,
    ),
}

ENDPOINTS = tuple(OPENAQ_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in OPENAQ_ENDPOINTS.items()
}
