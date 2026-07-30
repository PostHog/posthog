import dataclasses
from datetime import UTC, date, datetime
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
from products.warehouse_sources.backend.temporal.data_imports.sources.sprig.settings import (
    DEFAULT_PAGE_SIZE,
    SPRIG_API_BASE_URL,
    SPRIG_ENDPOINTS,
)


@dataclasses.dataclass
class SprigResumeConfig:
    next_cursor: str


def _format_incremental_value(value: Any) -> Optional[int]:
    """Format an incremental cursor value as milliseconds since epoch for Sprig's `start` filter.

    The incremental field is always a datetime, but `date`/numeric/string values are handled
    defensively. `None` (initial sync, no watermark yet) returns `None` so the REST client drops
    the param and the first sync walks the full history.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        utc_dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return int(utc_dt.timestamp() * 1000)
    if isinstance(value, date):
        return int(datetime.combine(value, datetime.min.time(), tzinfo=UTC).timestamp() * 1000)
    if isinstance(value, int | float):
        return int(value)
    try:
        return int(datetime.fromisoformat(str(value)).timestamp() * 1000)
    except (TypeError, ValueError):
        return None


def _incremental_param_config(incremental_field: str) -> dict[str, Any]:
    return {
        "type": "incremental",
        "cursor_path": incremental_field,
        "initial_value": None,
        "convert": _format_incremental_value,
    }


def get_resource(name: str, should_use_incremental_field: bool) -> EndpointResource:
    cfg = SPRIG_ENDPOINTS[name]

    params: dict[str, Any] = {"limit": DEFAULT_PAGE_SIZE}
    if should_use_incremental_field:
        params["start"] = _incremental_param_config("createdAt")

    return {
        "name": cfg.name,
        "table_name": cfg.table_name,
        "write_disposition": {"disposition": "merge", "strategy": "upsert"}
        if should_use_incremental_field
        else "replace",
        "endpoint": {
            "data_selector": "data",
            "path": cfg.path,
            "params": params,
        },
        "table_format": "delta",
    }


def sprig_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[SprigResumeConfig],
    db_incremental_field_last_value: Optional[Any],
    should_use_incremental_field: bool = False,
) -> SourceResponse:
    cfg = SPRIG_ENDPOINTS[endpoint]

    config: RESTAPIConfig = {
        "client": {
            "base_url": SPRIG_API_BASE_URL,
            "auth": {
                "type": "bearer",
                "token": api_key,
            },
            # Sprig returns `{"data": [...], "cursor": "<base64>"|null}` — the same field name
            # both as the response's next-page pointer and the request's pagination param.
            "paginator": JSONResponseCursorPaginator(cursor_path="cursor", cursor_param="cursor"),
        },
        "resource_defaults": None,
        "resources": [get_resource(endpoint, should_use_incremental_field)],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = {"cursor": resume_config.next_cursor}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Only persist when there's a next page to resume to; the Redis TTL handles cleanup on
        # completion. Saving after each yielded batch means a crash re-yields the last page
        # (merge dedupes on the primary key) rather than skipping it.
        if state and state.get("cursor"):
            resumable_source_manager.save_state(SprigResumeConfig(next_cursor=str(state["cursor"])))

    resource = rest_api_resource(
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
        primary_keys=cfg.primary_keys,
        column_hints=resource.column_hints,
        # Sprig's docs don't state the default sort order of `data`, and there's no `sort`
        # query param to force one. The `start`/`end` window is documented as a created-since
        # filter meant to be advanced forward for incremental sync, so we assume ascending
        # creation order. Verify against a live account before relying on this in production —
        # if the API actually returns newest-first, this must switch to sort_mode="desc" (see
        # orb/orb.py) or the incremental watermark will skip data.
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if cfg.partition_key else None,
        partition_format="week" if cfg.partition_key else None,
        partition_keys=[cfg.partition_key] if cfg.partition_key else None,
    )


def validate_credentials(api_key: str) -> bool:
    """Cheap probe against `/v1/surveys` to confirm the Bearer token is genuine.

    Returns False only for auth failures (401/403). Transient or unexpected statuses (429,
    5xx, ...) are raised via `raise_for_status()` so they surface as a real error rather than
    being misreported to the user as an invalid API key.
    """
    response = make_tracked_session().get(
        f"{SPRIG_API_BASE_URL}/v1/surveys",
        params={"limit": 1},
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=30,
    )
    if response.status_code in (401, 403):
        return False
    response.raise_for_status()
    return True
