import dataclasses
from datetime import date, datetime
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.mercury.settings import (
    DEFAULT_PAGE_SIZE,
    MERCURY_BASE_URL,
    MERCURY_ENDPOINTS,
)


@dataclasses.dataclass
class MercuryResumeConfig:
    # `page.nextPage` cursor from the last fully-yielded page, replayed as `start_after`.
    cursor: str


def format_incremental_value(value: Any) -> str | None:
    """Format the incremental watermark as a date-only ``YYYY-MM-DD`` string.

    Mercury's ``start`` filter on ``/transactions`` only accepts a date, not a full
    ISO 8601 datetime — sending the latter gets the request rejected with a 400.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def get_resource(name: str, should_use_incremental_field: bool) -> EndpointResource:
    config = MERCURY_ENDPOINTS[name]

    params: dict[str, Any] = {}
    if config.paginated:
        params["limit"] = DEFAULT_PAGE_SIZE
        # Explicit ascending order so cursor pages arrive oldest-first and the incremental
        # watermark only ever advances.
        params["order"] = "asc"

    if should_use_incremental_field and config.incremental_param is not None:
        params[config.incremental_param] = {
            "type": "incremental",
            "cursor_path": "createdAt",
            "initial_value": None,
            "convert": format_incremental_value,
        }

    endpoint: Endpoint = {
        "path": config.path,
        "data_selector": config.data_selector,
        "params": params,
        "paginator": JSONResponseCursorPaginator(cursor_path="page.nextPage", cursor_param="start_after")
        if config.paginated
        else SinglePagePaginator(),
    }

    resource: EndpointResource = {
        "name": config.name,
        "table_name": config.name.lower(),
        "write_disposition": {
            "disposition": "merge",
            "strategy": "upsert",
        }
        if should_use_incremental_field
        else "replace",
        "endpoint": endpoint,
        "table_format": "delta",
    }

    if config.timestamp_columns:
        resource["columns"] = {column: {"data_type": "timestamp"} for column in config.timestamp_columns}

    return resource


def mercury_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[MercuryResumeConfig],
    db_incremental_field_last_value: Optional[Any],
    should_use_incremental_field: bool = False,
) -> Resource:
    config: RESTAPIConfig = {
        "client": {
            "base_url": MERCURY_BASE_URL,
            "auth": {
                "type": "bearer",
                "token": api_key,
            },
            "headers": {
                "Accept": "application/json",
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
        # Only persist when there's a next page to resume to; the Redis TTL
        # handles cleanup on completion.
        if state and state.get("cursor"):
            resumable_source_manager.save_state(MercuryResumeConfig(cursor=str(state["cursor"])))

    return rest_api_resource(
        config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


def check_credentials(api_key: str) -> int:
    """Probe the cheapest authenticated endpoint and return the HTTP status code."""
    response = make_tracked_session(redact_values=(api_key,)).get(
        f"{MERCURY_BASE_URL}/accounts",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
        },
        params={"limit": 1},
        timeout=30,
    )
    return response.status_code
