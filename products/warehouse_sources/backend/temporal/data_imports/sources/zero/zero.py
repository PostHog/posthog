import json
from datetime import UTC, date, datetime
from typing import Any, Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.zero.settings import (
    CREATED_AT,
    ENDPOINT_CONFIGS,
    PAGE_LIMIT,
    ZERO_BASE_URL,
)


@frozen
class ZeroResumeConfig:
    offset: int


@frozen
class ZeroCredentialCheck:
    status: int | None
    workspace_ids: tuple[str, ...] = ()


def _format_zero_datetime(value: Any) -> str:
    """Format an incremental cursor as the ISO 8601 string Zero's `$gt` date operator expects."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).isoformat()
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).isoformat()
    return str(value)


def get_resource(
    endpoint: str,
    workspace_id: Optional[str],
    incremental_field: Optional[str],
    db_incremental_field_last_value: Optional[Any],
) -> EndpointResource:
    """Build the resource for one endpoint.

    ``incremental_field`` is the cursor field for an incremental sync and ``None`` for a full refresh.
    """
    config = ENDPOINT_CONFIGS[endpoint]
    advertised = {incremental["field"] for incremental in config.incremental_fields}
    is_incremental = incremental_field is not None and bool(advertised)

    # Zero takes one JSON `where` object, so the workspace scope and the cursor go in together.
    where: dict[str, Any] = {}
    if workspace_id and config.workspace_filter_key is not None:
        where[config.workspace_filter_key] = workspace_id
    if is_incremental and db_incremental_field_last_value is not None:
        cursor = incremental_field if incremental_field in advertised else config.incremental_fields[0]["field"]
        where[cursor] = {"$gt": _format_zero_datetime(db_incremental_field_last_value)}

    # Sort on the immutable createdAt, also for incremental syncs. A row updated mid-sync moves to
    # the end of an updatedAt order and shifts every later offset page back by one row, which skips
    # a row. New rows land after the current offset in a createdAt order.
    params: dict[str, Any] = {"orderBy": json.dumps({CREATED_AT: "asc"})}
    if where:
        params["where"] = json.dumps(where)

    return {
        "name": config.name,
        "table_name": config.table_name,
        "primary_key": ["id"],
        "write_disposition": {"disposition": "merge", "strategy": "upsert"} if is_incremental else "replace",
        "endpoint": {
            "path": config.path,
            "data_selector": "data",
            "data_selector_required": True,
            "params": params,
            "paginator": {"type": "offset", "limit": PAGE_LIMIT, "total_path": "total"},
        },
        "table_format": "delta",
    }


def check_credentials(api_key: str) -> ZeroCredentialCheck:
    """List the workspaces the key can reach, and report the probe status."""
    try:
        response = make_tracked_session(redact_values=(api_key,)).get(
            f"{ZERO_BASE_URL}/api/workspaces",
            headers={"Authorization": f"Bearer {api_key}"},
            params={"fields": "id"},
            timeout=10,
        )
    except Exception:
        return ZeroCredentialCheck(status=None)
    if response.status_code != 200:
        return ZeroCredentialCheck(status=response.status_code)
    try:
        rows = response.json().get("data") or []
    except ValueError:
        return ZeroCredentialCheck(status=response.status_code)
    return ZeroCredentialCheck(
        status=response.status_code,
        workspace_ids=tuple(str(row["id"]) for row in rows if isinstance(row, dict) and row.get("id")),
    )


def zero_source(
    api_key: str,
    workspace_id: Optional[str],
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[ZeroResumeConfig],
    incremental_field: Optional[str],
    db_incremental_field_last_value: Optional[Any],
) -> SourceResponse:
    config: RESTAPIConfig = {
        "client": {
            "base_url": ZERO_BASE_URL,
            "auth": {"type": "bearer", "token": api_key},
        },
        "resource_defaults": {},
        "resources": [get_resource(endpoint, workspace_id, incremental_field, db_incremental_field_last_value)],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = {"offset": resume_config.offset}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state and "offset" in state:
            resumable_source_manager.save_state(ZeroResumeConfig(offset=int(state["offset"])))

    resource: Resource = rest_api_resource(
        config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=resource.name,
        items=lambda: resource,
        primary_keys=["id"],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="month",
        partition_keys=[CREATED_AT],
        column_hints=resource.column_hints,
    )
