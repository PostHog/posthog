import dataclasses
from collections.abc import Callable, Iterable, Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional

from requests import Request, Response

from products.warehouse_sources.sources.sdk import (
    BasePaginator,
    Endpoint,
    EndpointResource,
    HttpBasicAuth,
    IncrementalConfig,
    PageNumberPaginator,
    ResponseAction,
    RESTAPIConfig,
    RESTClient,
    ResumableSourceManager,
    SinglePagePaginator,
    SourceResponse,
    create_response_hooks,
    frozen,
    make_tracked_session,
    parse_datetime_value,
    rename_parent_fields,
    rest_api_resources,
    validate_via_probe,
)
from products.warehouse_sources.sources.toggl.settings import (
    API_V9_PREFIX,
    PAGE_SIZE,
    REPORTS_PAGE_SIZE,
    REPORTS_TIME_ENTRIES_PATH,
    REPORTS_WINDOW_DAYS,
    TOGGL_BASE_URL,
    TOGGL_ENDPOINTS,
    TogglEndpointConfig,
)

# Toggl Track launched in 2006, so no workspace holds a time entry before this date.
TIME_ENTRIES_EARLIEST_DATE = date(2006, 1, 1)
# The Reports API matches `start_date` in each entry creator's own time zone. A one-day overlap on
# incremental runs keeps entries near the watermark that a time zone ahead of UTC would move.
TIME_ENTRIES_INCREMENTAL_OVERLAP = timedelta(days=1)
# Toggl gives every API token the literal password `api_token` for basic auth.
API_TOKEN_PASSWORD = "api_token"
# Workspace fields that hold credentials: a deprecated workspace API token, and a calendar feed URL
# that embeds a private token.
_WORKSPACE_SECRET_FIELDS = ("api_token", "ical_url")
# Toggl answers 402 for two reasons: the hourly request quota ran out, which a later run recovers
# from, or the workspace's plan lacks the feature the request needs, which no retry fixes. Only the
# second carries this text. That workspace is skipped, so one workspace on a smaller plan does not
# stop the table for the others.
_SKIP_WORKSPACE_WITHOUT_FEATURE: ResponseAction = {
    "status_code": 402,
    "content": "feature enabled",
    "action": "ignore",
}


@dataclasses.dataclass(frozen=False)
class TogglResumeConfig:
    # Fan-out progress from the rest_source framework, for the v9 workspace children.
    fanout_state: Optional[dict[str, Any]] = None
    # Progress through the time entries search: finished workspaces, then the window and row the
    # current workspace continues from.
    completed_workspace_ids: list[int] = dataclasses.field(default_factory=list)
    workspace_id: Optional[int] = None
    window_start: Optional[str] = None
    first_row_number: Optional[int] = None


class TogglPageNumberPaginator(PageNumberPaginator):
    """`page`/`per_page` pagination over a bare JSON array that also stops on a short page.

    Only for endpoints with a documented page size cap. The request asks for that cap, so a shorter
    page is the last one and the empty-page request the base paginator needs is saved.
    """

    def __init__(self, page_size: int) -> None:
        super().__init__(base_page=1, page_param="page")
        self._page_size = page_size

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        if self._has_next_page and data is not None and len(data) < self._page_size:
            self._has_next_page = False


class TogglTotalCountPaginator(PageNumberPaginator):
    """`page`/`per_page` pagination for an envelope with `total_count` and the page size it used.

    The tasks endpoint documents no page size cap, so the page size comes from the response.
    """

    def __init__(self) -> None:
        super().__init__(base_page=1, page_param="page")

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        current_page = self.page
        super().update_state(response, data)
        if not self._has_next_page:
            return
        body = response.json()
        total_count = body.get("total_count") if isinstance(body, dict) else None
        per_page = body.get("per_page") if isinstance(body, dict) else None
        if isinstance(total_count, int) and isinstance(per_page, int) and per_page > 0:
            if current_page * per_page >= total_count:
                self._has_next_page = False


class TogglReportsPaginator(BasePaginator):
    """Paginates a Reports API search with the row number in the `X-Next-Row-Number` header.

    The header is absent on the last page. The row number goes back in the POST body as
    `first_row_number`.
    """

    def __init__(self) -> None:
        super().__init__()
        self._next_row_number: Optional[int] = None

    def init_request(self, request: Request) -> None:
        if self._next_row_number is not None:
            request.json = {**(request.json or {}), "first_row_number": self._next_row_number}

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        header = response.headers.get("X-Next-Row-Number")
        self._next_row_number = int(header) if header and header.strip().isdigit() else None
        self._has_next_page = self._next_row_number is not None

    def update_request(self, request: Request) -> None:
        if self._next_row_number is not None:
            request.json = {**(request.json or {}), "first_row_number": self._next_row_number}

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        if self._has_next_page and self._next_row_number is not None:
            return {"first_row_number": self._next_row_number}
        return None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        row_number = state.get("first_row_number")
        if row_number is not None:
            self._next_row_number = int(row_number)
            self._has_next_page = True


def _auth(api_token: str) -> HttpBasicAuth:
    return HttpBasicAuth(username=api_token, password=API_TOKEN_PASSWORD)


def _to_unix_seconds(value: Any) -> Any:
    parsed = parse_datetime_value(value)
    return int(parsed.timestamp()) if parsed is not None else value


def _strip_workspace_secrets(row: dict[str, Any]) -> dict[str, Any]:
    for key in _WORKSPACE_SECRET_FIELDS:
        row.pop(key, None)
    return row


_rename_workspace = rename_parent_fields("workspaces", {"id": "workspace_id"})


def _paginator(config: TogglEndpointConfig) -> BasePaginator:
    if config.pagination == "page_short_stop":
        return TogglPageNumberPaginator(PAGE_SIZE)
    if config.pagination == "page_total_count":
        return TogglTotalCountPaginator()
    if config.pagination == "page_empty_stop":
        return PageNumberPaginator(base_page=1, page_param="page")
    return SinglePagePaginator()


def _endpoint_spec(config: TogglEndpointConfig, extra_params: dict[str, Any]) -> Endpoint:
    params: dict[str, Any] = {**extra_params, **config.extra_params}
    if config.pagination != "single":
        params["per_page"] = PAGE_SIZE
    endpoint: Endpoint = {
        "path": config.path,
        "params": params,
        "paginator": _paginator(config),
        "data_selector_required": config.data_selector is not None,
    }
    if config.data_selector is not None:
        endpoint["data_selector"] = config.data_selector
    if config.name != "workspaces":
        response_actions: list[ResponseAction] = [_SKIP_WORKSPACE_WITHOUT_FEATURE]
        if config.skip_forbidden_workspaces:
            response_actions.append({"status_code": 403, "action": "ignore"})
        endpoint["response_actions"] = response_actions
    return endpoint


def _workspaces_resource() -> EndpointResource:
    return {
        "name": "workspaces",
        "endpoint": _endpoint_spec(TOGGL_ENDPOINTS["workspaces"], {}),
        "data_map": _strip_workspace_secrets,
    }


def _incremental_config(
    config: TogglEndpointConfig, should_use_incremental_field: bool, db_incremental_field_last_value: Any
) -> Optional[IncrementalConfig]:
    # `since` filters on the last change time, so it is sent only once a watermark exists.
    if not config.incremental_fields or not should_use_incremental_field or db_incremental_field_last_value is None:
        return None
    return {"start_param": "since", "cursor_path": "at", "convert": _to_unix_seconds}


def _workspace_child_resource(
    config: TogglEndpointConfig, should_use_incremental_field: bool, db_incremental_field_last_value: Any
) -> EndpointResource:
    endpoint = _endpoint_spec(config, {"workspace_id": {"type": "resolve", "resource": "workspaces", "field": "id"}})
    incremental = _incremental_config(config, should_use_incremental_field, db_incremental_field_last_value)
    if incremental is not None:
        endpoint["incremental"] = incremental
    return {
        "name": config.name,
        "include_from_parent": ["id"],
        "endpoint": endpoint,
        "data_map": _rename_workspace,
    }


def _source_response(config: TogglEndpointConfig, items: Callable[[], Iterable[Any]]) -> SourceResponse:
    return SourceResponse(
        name=config.name,
        items=items,
        primary_keys=config.primary_keys,
        partition_count=1 if config.partition_key else None,
        partition_size=1 if config.partition_key else None,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def _v9_source(
    api_token: str,
    config: TogglEndpointConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[TogglResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> SourceResponse:
    resources: list[str | EndpointResource] = [_workspaces_resource()]
    if config.name != "workspaces":
        resources.append(
            _workspace_child_resource(config, should_use_incremental_field, db_incremental_field_last_value)
        )

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": TOGGL_BASE_URL,
            "auth": {"type": "http_basic", "username": api_token, "password": API_TOKEN_PASSWORD},
            # Every v9 table reads `/me/workspaces`, whose rows hold workspace tokens. The sample
            # scrubber does not know those field names, and `data_map` runs after capture.
            "capture": False,
        },
        "resource_defaults": {},
        "resources": resources,
    }

    initial_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_state = resume.fanout_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state is not None:
            resumable_source_manager.save_state(TogglResumeConfig(fanout_state=state))

    resource = next(
        r
        for r in rest_api_resources(
            rest_config,
            team_id,
            job_id,
            db_incremental_field_last_value,
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_state,
        )
        if r.name == config.name
    )
    return _source_response(config, lambda: resource)


def _flatten_time_entries(groups: list[Any], workspace_id: int) -> list[dict[str, Any]]:
    """One row per time entry from the search's groups.

    Each group carries the shared fields (user, project, description, tags) and a `time_entries`
    list with the per-entry id, start, stop and duration.
    """
    rows: list[dict[str, Any]] = []
    for group in groups:
        if not isinstance(group, dict):
            continue
        shared = {key: value for key, value in group.items() if key != "time_entries"}
        for entry in group.get("time_entries") or []:
            if isinstance(entry, dict):
                rows.append({**shared, **entry, "workspace_id": workspace_id})
    return rows


def _time_entries_first_date(workspace: dict[str, Any], db_incremental_field_last_value: Any, today: date) -> date:
    first = TIME_ENTRIES_EARLIEST_DATE
    # Free workspaces only reach this many days back, so earlier windows would return nothing.
    retention_days = workspace.get("max_data_retention_days")
    if isinstance(retention_days, int) and retention_days > 0:
        first = max(first, today - timedelta(days=retention_days))
    watermark = parse_datetime_value(db_incremental_field_last_value)
    if watermark is not None:
        first = max(first, (watermark - TIME_ENTRIES_INCREMENTAL_OVERLAP).date())
    return first


@frozen
class DateWindow:
    """An inclusive date range for one time entries search."""

    start: date
    end: date


def _windows(first: date, last: date) -> Iterator[DateWindow]:
    """Inclusive date windows of at most `REPORTS_WINDOW_DAYS` from `first` to `last`.

    The search needs an end date after its start date, so a window never has one day only.
    """
    start = first
    while start <= last:
        end = max(min(start + timedelta(days=REPORTS_WINDOW_DAYS - 1), last), start + timedelta(days=1))
        yield DateWindow(start=start, end=end)
        start = end + timedelta(days=1)


def _search_pages(
    client: RESTClient, workspace_id: int, window: DateWindow, first_row_number: Optional[int]
) -> Iterator[tuple[list[Any], Optional[int]]]:
    """Yield each page of one time entries search, with the row number of the page after it."""
    next_rows: list[Optional[int]] = []

    def record_next_row(state: Optional[dict[str, Any]], _has_next_page: bool) -> None:
        next_rows.append(state["first_row_number"] if state else None)

    pages = client.paginate(
        REPORTS_TIME_ENTRIES_PATH.format(workspace_id=workspace_id),
        method="post",
        json={
            "start_date": window.start.isoformat(),
            "end_date": window.end.isoformat(),
            "order_by": "date",
            "order_dir": "ASC",
            "page_size": REPORTS_PAGE_SIZE,
            "grouped": False,
            "enrich_response": True,
        },
        paginator=TogglReportsPaginator(),
        hooks=create_response_hooks([_SKIP_WORKSPACE_WITHOUT_FEATURE]),
        initial_paginator_state={"first_row_number": first_row_number} if first_row_number is not None else None,
        page_state_hook=record_next_row,
    )
    for page in pages:
        yield page, next_rows[-1]


def _time_entries_source(
    api_token: str,
    config: TogglEndpointConfig,
    resumable_source_manager: ResumableSourceManager[TogglResumeConfig],
    db_incremental_field_last_value: Any,
) -> SourceResponse:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    def items() -> Iterator[list[dict[str, Any]]]:
        client = RESTClient(base_url=TOGGL_BASE_URL, auth=_auth(api_token))
        # Workspace rows hold workspace tokens, so this read stays out of HTTP sample capture.
        workspaces_client = RESTClient(base_url=TOGGL_BASE_URL, auth=_auth(api_token), capture=False)
        workspaces = [
            workspace
            for page in workspaces_client.paginate(f"{API_V9_PREFIX}/me/workspaces", paginator=SinglePagePaginator())
            for workspace in page
            if isinstance(workspace, dict) and isinstance(workspace.get("id"), int)
        ]
        completed = list(resume.completed_workspace_ids) if resume else []
        today = datetime.now(UTC).date()
        # Tomorrow, so entries that start today in a time zone ahead of UTC are included.
        last_date = today + timedelta(days=1)

        for workspace in workspaces:
            workspace_id: int = workspace["id"]
            if workspace_id in completed:
                continue

            first_date = _time_entries_first_date(workspace, db_incremental_field_last_value, today)
            first_row_number: Optional[int] = None
            if resume is not None and resume.workspace_id == workspace_id and resume.window_start:
                saved_window_start = date.fromisoformat(resume.window_start)
                # A row number counts from the start of its window. When retention has since moved
                # the first date past that start, the window differs and the row number with it.
                if saved_window_start >= first_date:
                    first_date = saved_window_start
                    first_row_number = resume.first_row_number

            windows = list(_windows(first_date, last_date))
            for index, window in enumerate(windows):
                next_window_start = windows[index + 1].start if index + 1 < len(windows) else None
                for groups, next_row_number in _search_pages(client, workspace_id, window, first_row_number):
                    if next_row_number is not None:
                        state = TogglResumeConfig(
                            completed_workspace_ids=list(completed),
                            workspace_id=workspace_id,
                            window_start=window.start.isoformat(),
                            first_row_number=next_row_number,
                        )
                    elif next_window_start is not None:
                        state = TogglResumeConfig(
                            completed_workspace_ids=list(completed),
                            workspace_id=workspace_id,
                            window_start=next_window_start.isoformat(),
                        )
                    else:
                        state = TogglResumeConfig(completed_workspace_ids=[*completed, workspace_id])
                    resumable_source_manager.save_state(state)

                    rows = _flatten_time_entries(groups, workspace_id)
                    if rows:
                        yield rows
                    else:
                        resumable_source_manager.safe_point()
                first_row_number = None

            completed.append(workspace_id)

    return _source_response(config, items)


def toggl_source(
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[TogglResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = TOGGL_ENDPOINTS[endpoint]
    if endpoint == "time_entries":
        return _time_entries_source(
            api_token,
            config,
            resumable_source_manager,
            db_incremental_field_last_value if should_use_incremental_field else None,
        )
    return _v9_source(
        api_token,
        config,
        team_id,
        job_id,
        resumable_source_manager,
        should_use_incremental_field,
        db_incremental_field_last_value,
    )


def validate_credentials(api_token: str) -> tuple[bool, Optional[int]]:
    """A Toggl API token reads what its user can, with no scopes, so one `/me` probe checks it."""
    return validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_token,)),
        f"{TOGGL_BASE_URL}{API_V9_PREFIX}/me",
        auth=_auth(api_token),
    )
