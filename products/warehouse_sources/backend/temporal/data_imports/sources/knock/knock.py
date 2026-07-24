import dataclasses
from datetime import datetime
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.knock.settings import (
    ENDPOINTS_CONFIG,
    KNOCK_BASE_URL,
    KNOCK_PAGE_SIZE,
)

DEFAULT_INCREMENTAL_START = "1970-01-01T00:00:00Z"


@dataclasses.dataclass
class KnockResumeConfig:
    after: str


def _to_iso8601(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def get_resource(endpoint: str, should_use_incremental_field: bool) -> EndpointResource:
    config = ENDPOINTS_CONFIG[endpoint]

    params: dict[str, Any] = {"page_size": KNOCK_PAGE_SIZE}
    if should_use_incremental_field and config.incremental_param and config.incremental_fields:
        params[config.incremental_param] = {
            "type": "incremental",
            "cursor_path": config.incremental_fields[0]["field"],
            "initial_value": DEFAULT_INCREMENTAL_START,
            "convert": _to_iso8601,
        }

    return {
        "name": endpoint,
        "table_name": endpoint,
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
            # Fail loud if Knock ever changes the response envelope key instead of
            # silently syncing 0 rows.
            "data_selector_required": True,
        },
        "table_format": "delta",
    }


def knock_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[KnockResumeConfig],
    db_incremental_field_last_value: Optional[Any],
    should_use_incremental_field: bool = False,
) -> SourceResponse:
    endpoint_config = ENDPOINTS_CONFIG[endpoint]

    config: RESTAPIConfig = {
        "client": {
            "base_url": KNOCK_BASE_URL,
            "auth": {
                "type": "bearer",
                "token": api_key,
            },
            "headers": {"Accept": "application/json"},
            "paginator": JSONResponseCursorPaginator(cursor_path="page_info.after", cursor_param="after"),
        },
        "resource_defaults": {},
        "resources": [get_resource(endpoint, should_use_incremental_field)],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = {"cursor": resume_config.after}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Only persist when there's a next page to resume to; the Redis TTL
        # handles cleanup on completion.
        if state and state.get("cursor"):
            resumable_source_manager.save_state(KnockResumeConfig(after=str(state["cursor"])))

    resource = rest_api_resource(
        config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    has_partition_key = endpoint_config.partition_key is not None

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=list(endpoint_config.primary_keys),
        partition_count=1 if has_partition_key else None,
        partition_size=1 if has_partition_key else None,
        partition_mode="datetime" if has_partition_key else None,
        partition_format="month" if has_partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
        sort_mode=endpoint_config.sort_mode,
    )


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    session = make_tracked_session(redact_values=(api_key,))
    res = session.get(
        f"{KNOCK_BASE_URL}/v1/users",
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        params={"page_size": 1},
        timeout=30,
    )

    if res.status_code == 200:
        return True, None

    if res.status_code in (401, 403):
        # Knock returns {"code": "api_key_invalid", "message": "..."} on auth failures.
        try:
            message = res.json().get("message")
        except Exception:
            message = None
        return False, message or "Invalid Knock API key"

    return False, f"Knock API returned an unexpected response (HTTP {res.status_code})"
