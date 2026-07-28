import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.appstack.settings import (
    APPSTACK_API_BASE_URL,
    APPSTACK_ENDPOINTS,
    PAGE_SIZE,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    OffsetPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

VALIDATION_PROBE_WINDOW_SECONDS = 24 * 60 * 60


@dataclasses.dataclass
class AppstackResumeConfig:
    # Next `offset` to request, as reported by the paginator after the last yielded page.
    offset: int
    # The export window's `timestamp` param, pinned at walk start. Offsets are positions within
    # one window, so a resumed attempt must replay the exact same window rather than re-deriving
    # it from a watermark that advanced while the walk ran.
    window_start: int


def _to_unix_seconds(value: Any) -> int:
    """Coerce an incremental watermark (datetime, date, epoch number, or string) to Unix seconds."""
    if isinstance(value, datetime):
        utc_dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return max(0, int(utc_dt.timestamp()))
    if isinstance(value, date):
        return _to_unix_seconds(datetime.combine(value, datetime.min.time(), tzinfo=UTC))
    if isinstance(value, int | float):
        return max(0, int(value))
    if isinstance(value, str):
        try:
            return _to_unix_seconds(datetime.fromisoformat(value.replace("Z", "+00:00")))
        except ValueError:
            pass
        try:
            return max(0, int(float(value)))
        except ValueError:
            return 0
    return 0


def _export_window_start(should_use_incremental_field: bool, db_incremental_field_last_value: Any) -> int:
    """`timestamp` (Unix seconds) the export window starts at.

    The param is required, so a full refresh (or first incremental sync with no watermark yet)
    passes 0 to export the app's full history. The pipeline already shifts the watermark back by
    the schema's lookback window before it reaches this function.
    """
    if should_use_incremental_field and db_incremental_field_last_value is not None:
        return _to_unix_seconds(db_incremental_field_last_value)
    return 0


def get_resource(name: str, should_use_incremental_field: bool, window_start: int) -> EndpointResource:
    cfg = APPSTACK_ENDPOINTS[name]

    return {
        "name": cfg.name,
        "table_name": cfg.name,
        "write_disposition": {"disposition": "merge", "strategy": "upsert"}
        if should_use_incremental_field
        else "replace",
        "endpoint": {
            "data_selector": "data",
            "path": cfg.path,
            "params": {"timestamp": window_start},
        },
        # Parse ISO 8601 event_time strings into real timestamps so the incremental watermark and
        # the datetime partition key operate on a datetime column.
        "columns": {"event_time": {"data_type": "timestamp"}},
        "table_format": "delta",
    }


def appstack_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[AppstackResumeConfig],
    db_incremental_field_last_value: Optional[Any],
    should_use_incremental_field: bool = False,
) -> SourceResponse:
    cfg = APPSTACK_ENDPOINTS[endpoint]

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    initial_paginator_state: Optional[dict[str, Any]] = None
    if resume is not None:
        window_start = resume.window_start
        initial_paginator_state = {"offset": resume.offset}
    else:
        window_start = _export_window_start(should_use_incremental_field, db_incremental_field_last_value)

    config: RESTAPIConfig = {
        "client": {
            "base_url": APPSTACK_API_BASE_URL,
            # Appstack expects the raw API key in the Authorization header, no Bearer prefix.
            "auth": {
                "type": "api_key",
                "name": "Authorization",
                "location": "header",
                "api_key": api_key,
            },
            # The response's `total_count` counts the current page, not the whole window, so it
            # must never be used as a grand total; the walk ends when a page comes back short.
            "paginator": OffsetPaginator(limit=PAGE_SIZE, total_path=None),
            # Export rows can carry device/user identifiers (idfv, maid, customer_user_id) the
            # name-based sample scrubbers don't recognise, so keep response bodies out of shared
            # HTTP sample storage. Requests are still metered and logged (with the key redacted).
            "session": make_tracked_session(capture=False, redact_values=(api_key,)),
        },
        "resource_defaults": None,
        "resources": [get_resource(endpoint, should_use_incremental_field, window_start)],
    }

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Called after each yielded page; persist only while a next page exists (the Redis TTL
        # cleans up on completion). A crash re-yields the last page and merge dedupes on the
        # primary key rather than skipping rows.
        if state and state.get("offset") is not None:
            resumable_source_manager.save_state(
                AppstackResumeConfig(offset=int(state["offset"]), window_start=window_start)
            )

    resource = rest_api_resource(
        config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=resource.name,
        items=lambda: resource,
        primary_keys=cfg.primary_keys,
        column_hints=resource.column_hints,
        # Documented: exports are ordered by event_time ascending.
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if cfg.partition_key else None,
        partition_format="month" if cfg.partition_key else None,
        partition_keys=[cfg.partition_key] if cfg.partition_key else None,
    )


def validate_credentials(api_key: str) -> bool:
    """Cheap one-row probe against GET /export to confirm the API key is genuine.

    Returns False only for auth failures (401/403). Transient or unexpected statuses (429,
    5xx, ...) are raised via `raise_for_status()` so they surface as a real error rather than
    being misreported to the user as an invalid API key.
    """
    window_start = int(datetime.now(UTC).timestamp()) - VALIDATION_PROBE_WINDOW_SECONDS
    response = make_tracked_session(capture=False, redact_values=(api_key,)).get(
        f"{APPSTACK_API_BASE_URL}/export",
        params={"timestamp": window_start, "limit": 1},
        headers={"Authorization": api_key},
        timeout=30,
    )
    if response.status_code in (401, 403):
        return False
    response.raise_for_status()
    return True
