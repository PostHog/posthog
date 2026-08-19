import json
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any, Optional, cast

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    OffsetPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.zero.settings import (
    ENDPOINT_CONFIGS,
    ZERO_BASE_URL,
)

PAGE_LIMIT = 100


@frozen
class ZeroResumeConfig:
    offset: int


def _format_zero_datetime(value: Any) -> str:
    """Format an incremental cursor as the ISO 8601 string Zero's `$gt` date operator expects."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).isoformat()
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).isoformat()
    return str(value)


def _build_where(workspace_id: Optional[str], date_field: Optional[str]) -> Callable[[Any], str]:
    """Build the `convert` callable for the declarative incremental `where` param.

    Zero's `where` filter is a single JSON-encoded object, so the static workspace scope and the
    dynamic incremental cursor have to be merged into one value here rather than sent as two
    separate query params.
    """

    def convert(last_value: Any) -> str:
        where: dict[str, Any] = {}
        if workspace_id is not None:
            where["workspaceId"] = workspace_id
        if date_field is not None and last_value is not None:
            where[date_field] = {"$gt": _format_zero_datetime(last_value)}
        return json.dumps(where)

    return convert


def get_resource(
    endpoint: str,
    workspace_id: str,
    should_use_incremental_field: bool,
    incremental_field: Optional[str],
) -> EndpointResource:
    config = ENDPOINT_CONFIGS[endpoint]
    is_incremental = should_use_incremental_field and bool(config.incremental_fields)
    scoped_workspace_id = workspace_id if config.scoped_by_workspace else None

    # Stable, ascending sort so offset pagination doesn't skip or duplicate rows as new records
    # are created mid-sync — createdAt never changes, so new rows always land after the current
    # offset. Incremental syncs instead sort on the cursor field, matching SourceResponse.sort_mode.
    sort_field = "createdAt"
    params: dict[str, Any] = {}

    if is_incremental:
        advertised = {incremental["field"] for incremental in config.incremental_fields}
        cursor = (
            incremental_field
            if incremental_field is not None and incremental_field in advertised
            else config.incremental_fields[0]["field"]
        )
        sort_field = cursor
        params["where"] = {
            "type": "incremental",
            "cursor_path": cursor,
            "initial_value": None,
            "convert": _build_where(scoped_workspace_id, cursor),
        }
    elif scoped_workspace_id is not None:
        params["where"] = json.dumps({"workspaceId": scoped_workspace_id})

    params["orderBy"] = json.dumps({sort_field: "asc"})

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
            "paginator": OffsetPaginator(limit=PAGE_LIMIT, total_path="total"),
        },
        "table_format": "delta",
    }


def resolve_workspace_id(api_key: str) -> str:
    """Resolve the workspace this API key belongs to.

    Most Zero resources are workspace-scoped and require an explicit `where={"workspaceId": ...}`
    filter, so the sync resolves the workspace once up front. `GET /api/workspaces` returns every
    workspace the key can see, unfiltered — for a key with access to more than one, taking the
    first result would pick an unintended workspace boundary silently, so this fails loud instead
    and asks for a key scoped to a single workspace.
    """
    session = make_tracked_session(redact_values=(api_key,))
    response = session.get(
        f"{ZERO_BASE_URL}/api/workspaces",
        headers={"Authorization": f"Bearer {api_key}"},
        params={"fields": "id"},
        timeout=10,
    )
    response.raise_for_status()
    data = response.json().get("data") or []
    if not data:
        raise ValueError("This Zero API key isn't a member of any workspace.")
    if len(data) > 1:
        raise ValueError(
            "This Zero API key has access to multiple workspaces. Use an API key scoped to a "
            "single workspace so PostHog imports data from the intended workspace only."
        )
    return cast(str, data[0]["id"])


def validate_credentials(api_key: str) -> bool:
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{ZERO_BASE_URL}/api/workspaces",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    return ok


def zero_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[ZeroResumeConfig],
    db_incremental_field_last_value: Optional[Any],
    incremental_field: Optional[str] = None,
    should_use_incremental_field: bool = False,
) -> Resource:
    workspace_id = resolve_workspace_id(api_key)

    config: RESTAPIConfig = {
        "client": {
            "base_url": ZERO_BASE_URL,
            "auth": {"type": "bearer", "token": api_key},
        },
        "resource_defaults": {
            "write_disposition": {"disposition": "merge", "strategy": "upsert"}
            if should_use_incremental_field
            else "replace",
        },
        "resources": [get_resource(endpoint, workspace_id, should_use_incremental_field, incremental_field)],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = {"offset": resume_config.offset}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state and "offset" in state:
            resumable_source_manager.save_state(ZeroResumeConfig(offset=int(state["offset"])))

    return rest_api_resource(
        config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
