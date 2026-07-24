import dataclasses
from datetime import UTC, datetime
from typing import Any, Optional

from dateutil import parser as date_parser

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.courier.settings import (
    COURIER_BASE_URL,
    COURIER_PAGE_SIZE,
    ENDPOINTS_CONFIG,
)

# Courier returns HTTP 403 (not 401) for both a missing and an invalid bearer token, with this
# message in the body — confirmed by probing the live API with no/bad credentials.
AUTH_ERROR_MESSAGE = "Invalid or missing authentication credentials"

DEFAULT_INCREMENTAL_START = "1970-01-01T00:00:00Z"


@dataclasses.dataclass
class CourierResumeConfig:
    cursor: str


def _to_iso8601(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _normalize_row(item: dict[str, Any], timestamp_fields: tuple[str, ...]) -> dict[str, Any]:
    """Convert Courier's epoch-millisecond and ISO-8601 date fields to real datetimes.

    The warehouse then types these columns as timestamps (useful for querying) and the
    partitioner reads the datetime directly rather than misinterpreting raw millis as epoch
    seconds or leaving a string uninterpreted.
    """
    for name in timestamp_fields:
        value = item.get(name)
        if value is None:
            continue
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            item[name] = datetime.fromtimestamp(value / 1000, tz=UTC)
        elif isinstance(value, str):
            try:
                item[name] = date_parser.isoparse(value)
            except ValueError:
                pass
    return item


def get_resource(name: str, should_use_incremental_field: bool) -> EndpointResource:
    config = ENDPOINTS_CONFIG[name]

    params: dict[str, Any] = {"limit": COURIER_PAGE_SIZE}
    if should_use_incremental_field and config.incremental_param and config.incremental_fields:
        params[config.incremental_param] = {
            "type": "incremental",
            "cursor_path": config.incremental_fields[0]["field"],
            "initial_value": DEFAULT_INCREMENTAL_START,
            "convert": _to_iso8601,
        }

    def data_map(item: dict[str, Any]) -> dict[str, Any]:
        return _normalize_row(item, config.timestamp_fields)

    endpoint_resource: EndpointResource = {
        "name": name,
        "table_name": name,
        "write_disposition": {
            "disposition": "merge",
            "strategy": "upsert",
        }
        if should_use_incremental_field
        else "replace",
        "endpoint": {
            "path": config.path,
            "params": params,
            "data_selector": config.data_selector,
            # Fail loud if Courier ever changes the response envelope key instead of silently
            # syncing 0 rows.
            "data_selector_required": True,
        },
        "table_format": "delta",
    }
    if config.timestamp_fields:
        endpoint_resource["data_map"] = data_map
    return endpoint_resource


def courier_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[CourierResumeConfig],
    db_incremental_field_last_value: Optional[Any],
    should_use_incremental_field: bool = False,
) -> SourceResponse:
    config = ENDPOINTS_CONFIG[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": COURIER_BASE_URL,
            "auth": {
                "type": "bearer",
                "token": api_key,
            },
            "headers": {"Accept": "application/json"},
            "paginator": {
                "type": "cursor",
                "cursor_path": config.cursor_path,
                "cursor_param": "cursor",
            },
        },
        "resource_defaults": {},
        "resources": [get_resource(endpoint, should_use_incremental_field)],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = {"cursor": resume_config.cursor}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Only persist when there's a next page to resume to; the Redis TTL handles cleanup on
        # completion.
        if state and state.get("cursor"):
            resumable_source_manager.save_state(CourierResumeConfig(cursor=str(state["cursor"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    has_partition_key = config.partition_key is not None

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=list(config.primary_keys),
        partition_count=1 if has_partition_key else None,
        partition_size=1 if has_partition_key else None,
        partition_mode="datetime" if has_partition_key else None,
        partition_format="month" if has_partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode=config.sort_mode,
        column_hints=resource.column_hints,
    )


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{COURIER_BASE_URL}/messages?limit=1",
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        ok_statuses=(200,),
        # Courier's bearer auth carries the token in the standard `Authorization` header, which
        # `requests` already strips on cross-origin redirects.
        allow_redirects=True,
    )
    if ok:
        return True, None

    if status == 403:
        return False, f"Courier authentication failed: {AUTH_ERROR_MESSAGE}. Please check your API key."

    return False, f"Courier API returned an unexpected response (HTTP {status})"
