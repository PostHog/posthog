import dataclasses
from datetime import UTC, date, datetime
from functools import partial
from typing import Any, Optional

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.openaq.settings import (
    OPENAQ_ENDPOINTS,
    OpenAQEndpointConfig,
)

OPENAQ_BASE_URL = "https://api.openaq.org"

# The v3 API caps page size at 1000 and rejects requests where page * limit exceeds 100_000
# (offset ceiling). We page in 1000s and stop each per-sensor fan-out at MAX_PAGES so we never
# cross that ceiling; ascending order + the incremental datetime filter means a truncated sensor
# resumes from its last synced value on the next sync rather than losing data.
OPENAQ_PAGE_SIZE: int = 1000
MAX_PAGES: int = 100

# The only sort field every v3 list endpoint accepts is `id`; sorting ascending gives page-stable
# pagination for the full-refresh reference tables.
_LIST_SORT_PARAMS = {"order_by": "id", "sort_order": "asc"}

# Name of the internal parent resource that enumerates sensor ids for the measurement fan-out.
_SENSOR_IDS_RESOURCE = "sensor_ids"
# Key the framework injects a parent field under: `_{parent_resource}_{field}`.
_PARENT_SENSOR_ID_KEY = f"_{_SENSOR_IDS_RESOURCE}_id"


@dataclasses.dataclass
class OpenAQResumeConfig:
    # Next page to fetch (1-based) for the list/sensors endpoints — seeded into the page paginator.
    page: int = 1
    # Legacy field from the hand-rolled measurement resume (stable sensor bookmark). Kept so old saved
    # state still deserializes; the fan-out now checkpoints under `fanout_state` instead.
    parent_sensor_id: int | None = None
    # Framework fan-out resume state for the measurement endpoints:
    # {"completed": [child_path, ...], "current": child_path | None, "child_state": {...} | None}.
    fanout_state: dict[str, Any] | None = None


class OpenAQPageNumberPaginator(PageNumberPaginator):
    """Page-number pagination that also stops on a short page.

    OpenAQ v3 paginates with `page`/`limit` and returns rows under `results`; a page shorter than
    `limit` is the last one. The built-in stops only on an empty page, so we add the short-page check
    to match the API's "fewer than a full page means done" contract without paying an extra request.
    `maximum_page` caps the walk before `page * limit` crosses the v3 offset ceiling.
    """

    def __init__(self, page_size: int, maximum_page: int) -> None:
        super().__init__(base_page=1, page=1, page_param="page", maximum_page=maximum_page)
        self._page_size = page_size

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        if self._has_next_page and data is not None and len(data) < self._page_size:
            self._has_next_page = False


def _format_time_value(value: Any, prefix: str) -> str:
    """Format an incremental cursor value for the OpenAQ measurement time filter.

    The raw/hourly endpoints take an ISO-8601 datetime (`datetime_from`); the daily/yearly
    aggregates take a calendar date (`date_from`).
    """
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        if prefix == "date":
            return aware.date().isoformat()
        return aware.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return value.isoformat() if prefix == "date" else f"{value.isoformat()}T00:00:00Z"
    return str(value)


def _flatten_sensor(location: dict[str, Any], sensor: dict[str, Any]) -> dict[str, Any]:
    """Shape one embedded location sensor into a flat row with its parent-location context."""
    parameter = sensor.get("parameter") or {}
    return {
        # Direct access on the primary key so a malformed row fails fast rather than merging
        # every id-less sensor into one null-keyed row.
        "id": sensor["id"],
        "name": sensor.get("name"),
        "parameter_id": parameter.get("id"),
        "parameter_name": parameter.get("name"),
        "parameter_units": parameter.get("units"),
        "parameter_display_name": parameter.get("displayName"),
        "location_id": location.get("id"),
        "location_name": location.get("name"),
        "locality": location.get("locality"),
        "timezone": location.get("timezone"),
        "coordinates": location.get("coordinates"),
        "country": location.get("country"),
        "provider": location.get("provider"),
    }


def _flatten_measurement(item: dict[str, Any], sensor_id: int) -> dict[str, Any]:
    """Shape one measurement into a flat row keyed by (sensor_id, period start).

    A measurement carries no id of its own; its period start (`datetime_from`) plus the sensor it
    belongs to uniquely identify it, so both are lifted to the top level for the primary key.
    """
    period = item.get("period") or {}
    datetime_from = (period.get("datetimeFrom") or {}).get("utc")
    datetime_to = (period.get("datetimeTo") or {}).get("utc")
    parameter = item.get("parameter") or {}
    return {
        "sensor_id": sensor_id,
        "datetime_from": datetime_from,
        "datetime_to": datetime_to,
        "value": item.get("value"),
        "parameter_id": parameter.get("id"),
        "parameter_name": parameter.get("name"),
        "parameter_units": parameter.get("units"),
        "coordinates": item.get("coordinates"),
        "coverage": item.get("coverage"),
        "summary": item.get("summary"),
        "flag_info": item.get("flagInfo"),
    }


def _explode_location_sensors(location: dict[str, Any]) -> list[dict[str, Any]]:
    """Materialize the `sensors` endpoint: one flattened row per embedded sensor of a location."""
    return [_flatten_sensor(location, sensor) for sensor in location.get("sensors") or []]


def _explode_location_sensor_ids(location: dict[str, Any]) -> list[dict[str, Any]]:
    """Drive the measurement fan-out: yield each embedded sensor id (skipping id-less sensors)."""
    return [
        {"id": sensor_id} for sensor in (location.get("sensors") or []) if (sensor_id := sensor.get("id")) is not None
    ]


def _reshape_measurement(item: dict[str, Any]) -> dict[str, Any]:
    """Flatten a fanned-out measurement, taking its sensor id from the parent-injected field."""
    return _flatten_measurement(item, item[_PARENT_SENSOR_ID_KEY])


def _client_config(api_key: str) -> ClientConfig:
    return {
        "base_url": OPENAQ_BASE_URL,
        # Auth (X-API-Key) is supplied via the framework auth config so its value is redacted from
        # logged URLs, headers, sampled bodies, and raised error messages; only the non-secret Accept
        # header is set here.
        "headers": {"Accept": "application/json"},
        "auth": {"type": "api_key", "api_key": api_key, "name": "X-API-Key", "location": "header"},
    }


def _list_resource(endpoint: str, config: OpenAQEndpointConfig, page_size: int) -> EndpointResource:
    resource: EndpointResource = {
        "name": endpoint,
        "endpoint": {
            "path": config.path,
            "params": {**_LIST_SORT_PARAMS, "limit": page_size},
            # A missing `results` key is treated as an empty page (the paginator then stops), matching
            # the hand-rolled `data.get("results", [])`.
            "data_selector": "results",
            "paginator": OpenAQPageNumberPaginator(page_size, MAX_PAGES),
        },
    }
    if config.kind == "sensors":
        resource["data_map"] = _explode_location_sensors
    return resource


def _measurement_resources(
    endpoint: str,
    config: OpenAQEndpointConfig,
    page_size: int,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> list[EndpointResource | str]:
    parent: EndpointResource = {
        "name": _SENSOR_IDS_RESOURCE,
        "endpoint": {
            "path": "/v3/locations",
            "params": {**_LIST_SORT_PARAMS, "limit": page_size},
            "data_selector": "results",
            "paginator": OpenAQPageNumberPaginator(page_size, MAX_PAGES),
        },
        "data_map": _explode_location_sensor_ids,
    }

    child_endpoint: Endpoint = {
        "path": config.path,
        "params": {
            "sensors_id": {"type": "resolve", "resource": _SENSOR_IDS_RESOURCE, "field": "id"},
            "limit": page_size,
        },
        "data_selector": "results",
        "paginator": OpenAQPageNumberPaginator(page_size, MAX_PAGES),
    }
    # Only inject the server-side time filter when incremental syncing with a real watermark — a first
    # sync (no last value) fetches the full history, matching the hand-rolled guard.
    if should_use_incremental_field and db_incremental_field_last_value and config.time_param_prefix:
        prefix = config.time_param_prefix
        child_endpoint["incremental"] = {
            "start_param": f"{prefix}_from",
            "cursor_path": f"{prefix}_from",
            "convert": partial(_format_time_value, prefix=prefix),
        }

    child: EndpointResource = {
        "name": endpoint,
        "endpoint": child_endpoint,
        "include_from_parent": ["id"],
        "data_map": _reshape_measurement,
    }
    return [parent, child]


def openaq_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[OpenAQResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = OPENAQ_ENDPOINTS[endpoint]
    page_size = OPENAQ_PAGE_SIZE
    client_config = _client_config(api_key)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    if config.kind == "measurement":
        rest_config: RESTAPIConfig = {
            "client": client_config,
            "resource_defaults": {},
            "resources": _measurement_resources(
                endpoint, config, page_size, should_use_incremental_field, db_incremental_field_last_value
            ),
        }

        initial_fanout_state = resume.fanout_state if resume is not None else None

        def save_fanout(state: Optional[dict[str, Any]]) -> None:
            if state is not None:
                resumable_source_manager.save_state(OpenAQResumeConfig(fanout_state=state))

        resources = rest_api_resources(
            rest_config,
            team_id,
            job_id,
            db_incremental_field_last_value,
            resume_hook=save_fanout,
            initial_paginator_state=initial_fanout_state,
        )
        resource: Resource = next(r for r in resources if r.name == endpoint)
    else:
        rest_config = {
            "client": client_config,
            "resource_defaults": {},
            "resources": [_list_resource(endpoint, config, page_size)],
        }

        initial_page_state = {"page": resume.page} if (resume is not None and resume.page) else None

        def save_page(state: Optional[dict[str, Any]]) -> None:
            # Persist only when a next page remains; save AFTER a page yields so a crash re-yields the
            # last page (merge dedupes) rather than skipping it.
            if state and state.get("page") is not None:
                resumable_source_manager.save_state(OpenAQResumeConfig(page=int(state["page"])))

        resource = rest_api_resource(
            rest_config,
            team_id,
            job_id,
            None,
            resume_hook=save_page,
            initial_paginator_state=initial_page_state,
        )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # Measurements come back oldest-first (ascending period start) per the v3 docs, which the
        # incremental watermark relies on. Unverified against the live API (no key available); noted
        # in the PR. If this proves wrong, the datetime_from server filter still bounds each fetch, so
        # completeness holds — only mid-sync watermark checkpointing would need sort_mode="desc".
        sort_mode="asc",
        column_hints=resource.column_hints,
    )


def validate_credentials(api_key: str) -> bool:
    # /v3/parameters is a small reference list reachable by any valid key, so it's the cheapest
    # probe that the token itself is genuine.
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{OPENAQ_BASE_URL}/v3/parameters?limit=1",
        headers={"X-API-Key": api_key, "Accept": "application/json"},
    )
    return ok
