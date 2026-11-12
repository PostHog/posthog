import dataclasses
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any, Optional

from products.warehouse_sources.sources.sdk import (
    BearerTokenAuth,
    JSONResponseCursorPaginator,
    RESTAPIConfig,
    RESTClient,
    ResumableSourceManager,
    SourceResponse,
    make_tracked_session,
    rest_api_resource,
    rest_api_resources,
    validate_via_probe,
)
from products.warehouse_sources.sources.todoist.settings import (
    COMPLETED_TASKS_EARLIEST,
    COMPLETED_TASKS_WINDOW,
    TODOIST_BASE_URL,
    TODOIST_ENDPOINTS,
    TodoistEndpointConfig,
    TodoistFanOut,
)

# Todoist caps list endpoints at 200 items per page. The cursor paginator follows `next_cursor`
# regardless, so an over-large value would only ever cost an extra round trip if the cap were lower.
PAGE_LIMIT = 200


@dataclasses.dataclass(frozen=False)
class TodoistResumeConfig:
    # Body cursor for the next page of a standard (non-fan-out) endpoint. None means "start at page one".
    next_cursor: str | None = None
    # Legacy field from the hand-rolled fan-out bookmark, kept so state saved by an older build still
    # parses (ResumableSourceManager does dataclass(**saved)). No longer written.
    project_id: str | None = None
    # Framework fan-out resume state for the fan-out endpoints (collaborators, comments, project_comments):
    # {"completed": [child_path, ...], "current": child_path | None, "child_state": {"cursor": ...} | None}.
    fanout_state: dict | None = None
    # The completed-tasks window to continue from. `window_until` is only set together with
    # `next_cursor`, because the cursor is tied to the exact range that issued it.
    window_since: str | None = None
    window_until: str | None = None


def _non_secret_headers() -> dict[str, str]:
    # Auth (Bearer) is supplied via the framework auth config so the token is redacted out of logs
    # and raised error messages; only the non-secret Accept header is set here.
    return {"Accept": "application/json"}


def _cursor_paginator() -> JSONResponseCursorPaginator:
    # Todoist's unified v1 API wraps lists as {"results": [...], "next_cursor": "..."} and advances
    # via the `cursor` query param.
    return JSONResponseCursorPaginator(cursor_path="next_cursor", cursor_param="cursor")


def _parent_id_mapper(fan_out: TodoistFanOut) -> Any:
    # `include_from_parent=["id"]` injects the parent's id as `_<parent>_id`; expose it under the
    # endpoint's parent id column (for collaborators this keeps the pre-migration row shape).
    injected = f"_{fan_out.parent}_id"

    def rename(row: dict[str, Any]) -> dict[str, Any]:
        if injected in row:
            row[fan_out.parent_id_column] = row.pop(injected)
        return row

    return rename


def _may_have_comments(task: dict[str, Any]) -> bool:
    # Every task costs one comments request, so skip the tasks Todoist reports as having none.
    return task.get("note_count") != 0


# Parent rows that cannot produce child rows, dropped before the child request is made.
_PARENT_FILTERS: dict[str, Any] = {"comments": _may_have_comments}


def _format_datetime(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _source_response(endpoint: str, config: TodoistEndpointConfig, items: Any) -> SourceResponse:
    return SourceResponse(
        name=endpoint,
        items=lambda: items,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def _list_source(
    api_token: str,
    endpoint: str,
    config: TodoistEndpointConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[TodoistResumeConfig],
    incremental_since: Optional[datetime],
) -> SourceResponse:
    params: dict[str, Any] = {"limit": PAGE_LIMIT}
    # Only the lower bound is sent: a cursor must be reused with the exact params that issued it,
    # and an upper bound of "now" would differ between the attempt that saved it and the resume.
    if config.incremental_param and incremental_since is not None:
        params[config.incremental_param] = _format_datetime(incremental_since)

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": TODOIST_BASE_URL,
            "headers": _non_secret_headers(),
            "auth": {"type": "bearer", "token": api_token},
            "paginator": _cursor_paginator(),
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    "data_selector": "results",
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.next_cursor:
            initial_paginator_state = {"cursor": resume.next_cursor}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields the
        # last page (merge dedupes on the primary key) rather than skipping it.
        if state and state.get("cursor"):
            resumable_source_manager.save_state(TodoistResumeConfig(next_cursor=state["cursor"]))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,  # the incremental filter is set in `params` above
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    return _source_response(endpoint, config, resource)


def _fan_out_source(
    api_token: str,
    endpoint: str,
    config: TodoistEndpointConfig,
    fan_out: TodoistFanOut,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[TodoistResumeConfig],
) -> SourceResponse:
    """Fan out over every row of the parent endpoint, writing the parent id onto each child row.

    Full refresh only. Rows read again on resume are deduped by the primary key on merge.
    """
    parent_id_column = fan_out.parent_id_column
    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": TODOIST_BASE_URL,
            "headers": _non_secret_headers(),
            "auth": {"type": "bearer", "token": api_token},
            "paginator": _cursor_paginator(),
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": fan_out.parent,
                "endpoint": {
                    "path": TODOIST_ENDPOINTS[fan_out.parent].path,
                    "params": {"limit": PAGE_LIMIT},
                    "data_selector": "results",
                },
            },
            {
                "name": endpoint,
                "include_from_parent": ["id"],
                "endpoint": {
                    "path": config.path,
                    "params": {
                        parent_id_column: {"type": "resolve", "resource": fan_out.parent, "field": "id"},
                        "limit": PAGE_LIMIT,
                    },
                    "data_selector": "results",
                    # A path that ends in a placeholder defaults to a single-page paginator, which
                    # would drop every page after the first.
                    "paginator": _cursor_paginator(),
                    # A parent deleted between enumeration and this fetch 404s. Treat it as an empty
                    # page and move on rather than failing the whole sync — its children are gone.
                    "response_actions": [{"status_code": 404, "action": "ignore"}],
                },
                "resume_parent_pagination": fan_out.resume_parent_pagination,
                "data_map": _parent_id_mapper(fan_out),
            },
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.fanout_state:
            initial_paginator_state = resume.fanout_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        resumable_source_manager.save_state(TodoistResumeConfig(fanout_state=state))

    resources = rest_api_resources(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    parent_filter = _PARENT_FILTERS.get(endpoint)
    if parent_filter is not None:
        next(resource for resource in resources if resource.name == fan_out.parent).add_filter(parent_filter)
    child = next(resource for resource in resources if resource.name == endpoint)
    return _source_response(endpoint, config, child)


def _completed_task_pages(
    client: RESTClient,
    config: TodoistEndpointConfig,
    resumable_source_manager: ResumableSourceManager[TodoistResumeConfig],
    lower_bound: datetime,
    run_end: datetime,
) -> Iterator[list[dict[str, Any]]]:
    window_since = lower_bound
    resumed_until: Optional[datetime] = None
    cursor: Optional[str] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        resumed_since = _parse_datetime(resume.window_since) if resume is not None else None
        if resume is not None and resumed_since is not None:
            window_since = resumed_since
            # A cursor is only valid with the since/until pair that issued it.
            if resume.next_cursor and resume.window_until:
                cursor = resume.next_cursor
                resumed_until = _parse_datetime(resume.window_until)

    while window_since < run_end:
        window_until = resumed_until or min(window_since + COMPLETED_TASKS_WINDOW, run_end)
        since_value = _format_datetime(window_since)
        until_value = _format_datetime(window_until)

        def stage(
            state: Optional[dict[str, Any]],
            has_next_page: bool,
            since_value: str = since_value,
            until_value: str = until_value,
        ) -> None:
            if has_next_page and state and state.get("cursor"):
                resumable_source_manager.save_state(
                    TodoistResumeConfig(next_cursor=state["cursor"], window_since=since_value, window_until=until_value)
                )
            else:
                resumable_source_manager.save_state(TodoistResumeConfig(window_since=until_value))

        for page in client.paginate(
            path=config.path,
            params={"since": since_value, "until": until_value, "limit": PAGE_LIMIT},
            paginator=_cursor_paginator(),
            data_selector="items",
            initial_paginator_state={"cursor": cursor} if cursor else None,
            page_state_hook=stage,
        ):
            if page:
                yield page
            else:
                # Most old windows are empty. The staged state already points past this page.
                resumable_source_manager.safe_point()

        window_since = window_until
        resumed_until = None
        cursor = None


def _completed_tasks_source(
    api_token: str,
    endpoint: str,
    config: TodoistEndpointConfig,
    resumable_source_manager: ResumableSourceManager[TodoistResumeConfig],
    incremental_since: Optional[datetime],
) -> SourceResponse:
    client = RESTClient(
        base_url=TODOIST_BASE_URL,
        headers=_non_secret_headers(),
        auth=BearerTokenAuth(token=api_token),
        paginator=_cursor_paginator(),
    )
    lower_bound = incremental_since or COMPLETED_TASKS_EARLIEST
    # Fixed per run, so a resumed attempt walks the same windows its cursor came from.
    run_end = datetime.now(UTC)
    return _source_response(
        endpoint,
        config,
        _completed_task_pages(client, config, resumable_source_manager, lower_bound, run_end),
    )


def todoist_source(
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[TodoistResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> SourceResponse:
    config = TODOIST_ENDPOINTS[endpoint]
    incremental_since = _parse_datetime(db_incremental_field_last_value) if should_use_incremental_field else None
    if config.fan_out is not None:
        return _fan_out_source(api_token, endpoint, config, config.fan_out, team_id, job_id, resumable_source_manager)
    if config.completion_windows:
        return _completed_tasks_source(api_token, endpoint, config, resumable_source_manager, incremental_since)
    return _list_source(api_token, endpoint, config, team_id, job_id, resumable_source_manager, incremental_since)


def validate_credentials(api_token: str) -> bool:
    # Cheapest authenticated probe: pull a single project. A genuine token returns 200; a bad/revoked
    # one returns 401. validate_via_probe swallows transport errors and maps them to "not validated".
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_token,)),
        f"{TODOIST_BASE_URL}/projects?limit=1",
        headers={"Authorization": f"Bearer {api_token}", **_non_secret_headers()},
    )
    return ok


__all__ = ["TodoistResumeConfig", "todoist_source", "validate_credentials"]
