import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional

from requests import Request

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
from products.warehouse_sources.backend.temporal.data_imports.sources.orb.settings import (
    DEFAULT_PAGE_SIZE,
    ORB_API_BASE_URL,
    ORB_ENDPOINTS,
)


@dataclasses.dataclass
class OrbResumeConfig:
    next_cursor: str


def _format_incremental_value(value: Any) -> Optional[str]:
    """Format an incremental cursor value for Orb's `<field>[gt]` filters.

    Orb expects RFC 3339 date-times. The incremental field is always a datetime, but `date` and
    `str` are handled defensively. `None` (initial sync, no watermark yet) returns `None` so the
    REST client drops the param and the first sync walks the full history.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        utc_dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return utc_dt.isoformat()
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).isoformat()
    return str(value)


def _incremental_param_config(incremental_field: str) -> dict[str, Any]:
    return {
        "type": "incremental",
        "cursor_path": incremental_field,
        "initial_value": None,
        "convert": _format_incremental_value,
    }


class OrbCursorPaginator(JSONResponseCursorPaginator):
    """Cursor pagination over Orb's `pagination_metadata.next_cursor`, with resume support.

    Orb returns `{"data": [...], "pagination_metadata": {"has_more": bool, "next_cursor": str|null}}`
    and the cursor is passed back as the `cursor` query param. The opaque cursor encodes the full
    query (filters + sort), so any `created_at[gt]` filter set on the first request stays applied
    across pages and pagination terminates naturally once `has_more` is false — there's no
    unbounded walk-back past the incremental watermark.
    """

    def __init__(self) -> None:
        super().__init__(cursor_path="pagination_metadata.next_cursor", cursor_param="cursor")

    def init_request(self, request: Request) -> None:
        # Seed a resumed cursor onto the very first request.
        if self._cursor_value is not None:
            if request.params is None:
                request.params = {}
            request.params[self.cursor_param] = self._cursor_value

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        if self._cursor_value is not None and self._has_next_page:
            return {"next_cursor": self._cursor_value}
        return None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        next_cursor = state.get("next_cursor")
        if next_cursor is not None:
            self._cursor_value = str(next_cursor)
            self._has_next_page = True


def get_resource(name: str, should_use_incremental_field: bool) -> EndpointResource:
    cfg = ORB_ENDPOINTS[name]

    incremental = (
        should_use_incremental_field and cfg.incremental_param is not None and cfg.incremental_field is not None
    )

    params: dict[str, Any] = {"limit": DEFAULT_PAGE_SIZE}
    if incremental:
        assert cfg.incremental_param is not None and cfg.incremental_field is not None
        params[cfg.incremental_param] = _incremental_param_config(cfg.incremental_field)

    return {
        "name": cfg.name,
        "table_name": cfg.table_name,
        "write_disposition": {"disposition": "merge", "strategy": "upsert"} if incremental else "replace",
        "endpoint": {
            "data_selector": "data",
            "path": cfg.path,
            "params": params,
        },
        "table_format": "delta",
    }


def orb_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[OrbResumeConfig],
    db_incremental_field_last_value: Optional[Any],
    should_use_incremental_field: bool = False,
) -> SourceResponse:
    cfg = ORB_ENDPOINTS[endpoint]

    config: RESTAPIConfig = {
        "client": {
            "base_url": ORB_API_BASE_URL,
            "auth": {
                "type": "bearer",
                "token": api_key,
            },
            "paginator": OrbCursorPaginator(),
        },
        "resource_defaults": None,
        "resources": [get_resource(endpoint, should_use_incremental_field)],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = {"next_cursor": resume_config.next_cursor}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page exists; the Redis TTL cleans up on completion. Saving
        # after each yielded batch means a crash re-yields the last page (merge dedupes on the
        # primary key) rather than skipping it.
        if state and state.get("next_cursor"):
            resumable_source_manager.save_state(OrbResumeConfig(next_cursor=str(state["next_cursor"])))

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
        # Orb has no sort param — list endpoints always return newest-created first.
        sort_mode="desc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if cfg.partition_key else None,
        partition_format="week" if cfg.partition_key else None,
        partition_keys=[cfg.partition_key] if cfg.partition_key else None,
    )


def validate_credentials(api_key: str) -> bool:
    """Cheap probe against `/customers` to confirm the Bearer token is genuine.

    Returns False only for auth failures (401/403). Transient or unexpected statuses
    (429, 5xx, …) are raised via `raise_for_status()` so they surface as a real error
    rather than being misreported to the user as an invalid API key.
    """
    response = make_tracked_session().get(
        f"{ORB_API_BASE_URL}/customers",
        params={"limit": 1},
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=30,
    )
    if response.status_code in (401, 403):
        return False
    response.raise_for_status()
    return True
