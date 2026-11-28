from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial
from typing import Any

from products.warehouse_sources.sources.schematic.settings import (
    FEATURE_USAGE_HISTORY,
    HISTORY_LOOKBACK,
    HISTORY_START,
    HISTORY_WINDOW,
    SCHEMATIC_BASE_URL,
    SCHEMATIC_ENDPOINTS,
    SchematicEndpointConfig,
)
from products.warehouse_sources.sources.sdk import (
    ClientConfig,
    PaginatorConfig,
    Resource,
    RESTAPIConfig,
    ResumableSourceManager,
    SourceResponse,
    build_dependent_resource,
    format_datetime,
    frozen,
    make_tracked_session,
    resolve_incremental_start,
    rest_api_resource,
    validate_via_probe,
)

API_KEY_HEADER = "X-Schematic-Api-Key"


@dataclass(frozen=True)
class SchematicResumeConfig:
    offset: int = 0
    # Which `is_active` pass the offset belongs to, for endpoints read in an active and an inactive pass.
    is_active: bool | None = None
    # Feature usage history: the start of the time window the offset belongs to.
    window_start: str | None = None
    # Feature usage history: the end of the whole read, so a resume walks the same windows.
    history_end: str | None = None
    # Feature usage: the state `build_dependent_resource` checkpoints over the companies listing.
    fanout_state: dict[str, Any] | None = None


@frozen
class HistoryWindow:
    start: datetime
    end: datetime


def _client_config(api_key: str) -> ClientConfig:
    return {
        "base_url": SCHEMATIC_BASE_URL,
        "headers": {"Accept": "application/json"},
        "auth": {"type": "api_key", "api_key": api_key, "name": API_KEY_HEADER, "location": "header"},
        # `requests` keeps a custom header on a cross-origin redirect, so a redirect would replay the key.
        "allow_redirects": False,
        "allowed_hosts": [],
    }


def _offset_paginator(config: SchematicEndpointConfig) -> PaginatorConfig:
    # The response carries no total, so the walk ends on the first short page.
    return {"type": "offset", "limit": config.page_size, "total_path": None}


def _resource(
    api_key: str,
    config: SchematicEndpointConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[SchematicResumeConfig],
    is_active: bool | None,
    initial_offset: int | None,
    window: HistoryWindow | None = None,
    history_end: str | None = None,
) -> Resource:
    params: dict[str, Any] = dict(config.extra_params)
    if is_active is not None:
        params["is_active"] = "true" if is_active else "false"
    window_start: str | None = None
    if window is not None:
        window_start = format_datetime(window.start, "iso_z")
        params["start_time"] = window_start
        params["end_time"] = format_datetime(window.end, "iso_z")
    rest_config: RESTAPIConfig = {
        "client": _client_config(api_key),
        "resource_defaults": {},
        "resources": [
            {
                "name": config.name,
                "table_name": config.name,
                "write_disposition": "replace",
                "table_format": "delta",
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    "data_selector": "data",
                    "data_selector_required": True,
                    "paginator": _offset_paginator(config),
                },
            }
        ],
    }

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state is not None:
            resumable_source_manager.save_state(
                SchematicResumeConfig(
                    offset=int(state["offset"]),
                    is_active=is_active,
                    window_start=window_start,
                    history_end=history_end,
                )
            )

    return rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value=None,
        resume_hook=save_checkpoint,
        initial_paginator_state=None if initial_offset is None else {"offset": initial_offset},
    )


def _active_then_inactive(
    build: Callable[[bool, int | None], Resource],
    resumable_source_manager: ResumableSourceManager[SchematicResumeConfig],
    resume: SchematicResumeConfig | None,
) -> Iterator[Any]:
    if resume is None or resume.is_active is not False:
        yield from build(True, resume.offset if resume is not None else None)
        # Every active row is handed on, so a resume from here starts the inactive pass.
        resumable_source_manager.save_state(SchematicResumeConfig(offset=0, is_active=False))
        yield from build(False, None)
    else:
        yield from build(False, resume.offset)


def _history_windows(start: datetime, end: datetime) -> list[HistoryWindow]:
    windows = []
    while start < end:
        window_end = min(start + HISTORY_WINDOW, end)
        windows.append(HistoryWindow(start=start, end=window_end))
        start = window_end
    return windows


def _history_start(should_use_incremental_field: bool, db_incremental_field_last_value: Any, now: datetime) -> datetime:
    start = resolve_incremental_start(
        should_use_incremental_field,
        db_incremental_field_last_value,
        default=HISTORY_START,
        lookback=HISTORY_LOOKBACK,
        floor=HISTORY_START,
        now=now,
    )
    # Daily buckets start at midnight UTC, so a window that starts mid-day would split a day in two.
    return start.replace(hour=0, minute=0, second=0, microsecond=0)


def _windows_in_order(
    build: Callable[[HistoryWindow, int | None], Resource],
    resumable_source_manager: ResumableSourceManager[SchematicResumeConfig],
    windows: list[HistoryWindow],
    initial_offset: int | None,
    history_end: str,
) -> Iterator[Any]:
    for index, window in enumerate(windows):
        if index > 0:
            # Every row of the earlier windows is handed on, so a resume from here starts this window.
            resumable_source_manager.save_state(
                SchematicResumeConfig(
                    offset=0, window_start=format_datetime(window.start, "iso_z"), history_end=history_end
                )
            )
        yield from build(window, initial_offset if index == 0 else None)


def _feature_usage_history_resource(
    api_key: str,
    config: SchematicEndpointConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[SchematicResumeConfig],
    resume: SchematicResumeConfig | None,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Resource:
    now = datetime.now(UTC)
    # Both bounds must fall on an hour boundary, and the end is exclusive.
    end = now.replace(minute=0, second=0, microsecond=0)
    if resume is not None and resume.window_start is not None:
        start = datetime.fromisoformat(resume.window_start)
        # A later end would change the result set the saved offset pages through.
        if resume.history_end is not None:
            end = datetime.fromisoformat(resume.history_end)
        initial_offset: int | None = resume.offset
    else:
        start = _history_start(should_use_incremental_field, db_incremental_field_last_value, now)
        initial_offset = None

    windows = _history_windows(start, end)
    history_end = format_datetime(end, "iso_z")
    build = partial(_resource, api_key, config, team_id, job_id, resumable_source_manager, None)

    def build_window(window: HistoryWindow, offset: int | None) -> Resource:
        return build(offset, window, history_end)

    hints_from = build_window(windows[0] if windows else HistoryWindow(start=start, end=start + HISTORY_WINDOW), None)
    # The chain hands each page on unchanged and holds no rows, so as a `Resource` it keeps the
    # framework's checkpoints.
    return Resource(
        partial(_windows_in_order, build_window, resumable_source_manager, windows, initial_offset, history_end),
        name=config.name,
        hints=hints_from._hints,
    )


def _feature_usage_resource(
    api_key: str,
    endpoint: str,
    config: SchematicEndpointConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[SchematicResumeConfig],
    resume: SchematicResumeConfig | None,
) -> Any:
    assert config.fanout is not None
    parent_config = SCHEMATIC_ENDPOINTS[config.fanout.parent_name]

    def save_fanout_state(state: dict[str, Any] | None) -> None:
        if state:
            resumable_source_manager.save_state(SchematicResumeConfig(fanout_state=state))

    return build_dependent_resource(
        endpoint_configs=SCHEMATIC_ENDPOINTS,
        child_endpoint=endpoint,
        fanout=config.fanout,
        client_config=_client_config(api_key),
        path_format_values={},
        team_id=team_id,
        job_id=job_id,
        db_incremental_field_last_value=None,
        # The offset paginators send the page size.
        page_size_param=None,
        parent_endpoint_extra={
            "data_selector": "data",
            "data_selector_required": True,
            "paginator": _offset_paginator(parent_config),
        },
        child_endpoint_extra={
            "data_selector": "data",
            "data_selector_required": True,
            "paginator": _offset_paginator(config),
        },
        resume_hook=save_fanout_state,
        initial_paginator_state=resume.fanout_state if resume is not None else None,
        # The companies listing saves its page, so a resume starts there instead of keeping every
        # finished company in the state.
        resume_parent_pagination=True,
    )


def schematic_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[SchematicResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> SourceResponse:
    config = SCHEMATIC_ENDPOINTS[endpoint]
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    resource: Any
    if config.fanout is not None:
        resource = _feature_usage_resource(api_key, endpoint, config, team_id, job_id, resumable_source_manager, resume)
    elif endpoint == FEATURE_USAGE_HISTORY:
        resource = _feature_usage_history_resource(
            api_key,
            config,
            team_id,
            job_id,
            resumable_source_manager,
            resume,
            should_use_incremental_field,
            db_incremental_field_last_value,
        )
    elif config.include_inactive:
        build = partial(_resource, api_key, config, team_id, job_id, resumable_source_manager)
        first = build(True, None)
        # The chain hands each page on unchanged and holds no rows, so as a `Resource` it keeps the
        # framework's checkpoints.
        resource = Resource(
            partial(_active_then_inactive, build, resumable_source_manager, resume),
            name=endpoint,
            hints=first._hints,
        )
    else:
        resource = _resource(
            api_key,
            config,
            team_id,
            job_id,
            resumable_source_manager,
            None,
            resume.offset if resume is not None else None,
        )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=list(config.primary_keys),
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )


def validate_credentials(api_key: str) -> tuple[bool, int | None]:
    return validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{SCHEMATIC_BASE_URL}/companies?limit=1",
        headers={API_KEY_HEADER: api_key, "Accept": "application/json"},
        timeout=15,
        allow_redirects=False,
    )
