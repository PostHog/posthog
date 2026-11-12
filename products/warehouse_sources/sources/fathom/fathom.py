import dataclasses
from typing import Any, Optional

from requests.exceptions import RequestException

from products.warehouse_sources.sources.fathom.settings import FATHOM_BASE_URL, FATHOM_ENDPOINTS, FathomEndpointConfig
from products.warehouse_sources.sources.sdk import (
    ClientConfig,
    Endpoint,
    EndpointResource,
    JSONResponseCursorPaginator,
    RESTAPIConfig,
    ResumableSourceManager,
    SourceResponse,
    coerce_datetime_to_utc,
    make_tracked_session,
    rest_api_resource,
)

API_KEY_HEADER = "X-Api-Key"
VALIDATION_TIMEOUT_SECONDS = 30


@dataclasses.dataclass(frozen=True)
class FathomResumeConfig:
    cursor: str


def format_created_after(value: Any) -> str:
    """Format the watermark as the ISO 8601 UTC timestamp that `created_after` takes."""
    normalized = coerce_datetime_to_utc(value)
    if normalized is None:
        return str(value)
    return normalized.strftime("%Y-%m-%dT%H:%M:%SZ")


def _project(columns: tuple[str, ...]):
    def project(row: dict[str, Any]) -> dict[str, Any]:
        return {column: row.get(column) for column in columns}

    return project


def _client_config(api_key: str) -> ClientConfig:
    return {
        "base_url": FATHOM_BASE_URL,
        "auth": {"type": "api_key", "name": API_KEY_HEADER, "api_key": api_key, "location": "header"},
        "headers": {"Accept": "application/json"},
        "paginator": JSONResponseCursorPaginator(cursor_path="next_cursor", cursor_param="cursor"),
        # `requests` keeps a custom auth header on a cross-origin redirect, so a 3xx could send the
        # key to another host. Refuse redirects so the key only goes to api.fathom.ai.
        "allow_redirects": False,
        # Rows hold meeting content, attendee emails and transcripts.
        "capture": False,
    }


def get_resource(
    config: FathomEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
) -> EndpointResource:
    use_incremental = should_use_incremental_field and bool(config.incremental_fields)

    endpoint: Endpoint = {
        "path": config.path,
        "data_selector": "items",
        "params": dict(config.params),
    }
    # The first incremental sync sends no filter, so it reads the full history. Later syncs only
    # ask for meetings created after the watermark.
    if use_incremental and db_incremental_field_last_value is not None:
        endpoint["incremental"] = {
            "cursor_path": "created_at",
            "start_param": "created_after",
            "initial_value": None,
            "convert": format_created_after,
        }

    resource: EndpointResource = {
        "name": config.name,
        "table_name": config.name,
        "primary_key": config.primary_keys,
        "write_disposition": {"disposition": "merge", "strategy": "upsert"} if use_incremental else "replace",
        "endpoint": endpoint,
        "table_format": "delta",
    }
    if config.columns is not None:
        resource["data_map"] = _project(config.columns)
    return resource


def fathom_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[FathomResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    endpoint_config = FATHOM_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": _client_config(api_key),
        "resource_defaults": {},
        "resources": [get_resource(endpoint_config, should_use_incremental_field, db_incremental_field_last_value)],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = {"cursor": resume_config.cursor}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state and state.get("cursor"):
            resumable_source_manager.save_state(FathomResumeConfig(cursor=str(state["cursor"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    partition_key = endpoint_config.partition_key
    return SourceResponse(
        name=endpoint_config.name,
        items=lambda: resource,
        primary_keys=endpoint_config.primary_keys,
        # Fathom does not document the order of `/meetings`, so the order is not known.
        sort_mode=None,
        partition_count=1 if partition_key else None,
        partition_size=1 if partition_key else None,
        partition_mode="datetime" if partition_key else None,
        partition_format="month" if partition_key else None,
        partition_keys=[partition_key] if partition_key else None,
    )


def probe_status(api_key: str, path: str) -> Optional[int]:
    """Send one request to `path` and return the HTTP status, or None when the request failed."""
    try:
        response = make_tracked_session(redact_values=(api_key,)).get(
            f"{FATHOM_BASE_URL}{path}",
            headers={API_KEY_HEADER: api_key, "Accept": "application/json"},
            timeout=VALIDATION_TIMEOUT_SECONDS,
            allow_redirects=False,
        )
    except RequestException:
        return None
    return response.status_code
