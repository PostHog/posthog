from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from typing import Any, Optional, cast

from requests import Request, Response

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.datetime_utils import (
    coerce_datetime_to_utc,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import BasePaginator
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SortMode, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.yoco.settings import (
    ENDPOINT_SCOPES,
    MAX_FILTER_WINDOW,
    YOCO_BASE_URL,
    YOCO_ENDPOINTS,
    YocoEndpointConfig,
)

REQUEST_TIMEOUT_SECONDS = 30


@frozen
class YocoResumeConfig:
    """Paginator checkpoint.

    Top-level endpoints save the next `cursor` plus the date window it belongs to. The
    payout-entries fan-out saves the framework's dependent-resource shape instead: which
    parent payouts are done, which one is in flight, and that parent's cursor.
    """

    cursor: Optional[str] = None
    window_start: Optional[str] = None
    window_end: Optional[str] = None
    completed: Optional[list[str]] = None
    current: Optional[str] = None
    child_state: Optional[dict[str, Any]] = None


def _format_datetime(value: datetime) -> str:
    # Whole seconds only, which rounds the lower bound down. `__gte` is inclusive anyway, so a
    # sync re-reads a few boundary rows (the merge dedupes them) rather than skipping any.
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_datetime(value: str) -> Optional[datetime]:
    try:
        return coerce_datetime_to_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError:
        return None


class YocoCursorPaginator(BasePaginator):
    """Cursor pagination that optionally walks a date range in windows of at most 31 days.

    Yoco returns an opaque `next_cursor` alongside each page and echoes the request filters,
    so every page re-sends the window bounds together with the cursor. Because the API refuses
    a `created_at`/`updated_at` range wider than 31 days, a watermark older than that cannot be
    expressed as a single `__gte`: once a window's pages run out the paginator advances to the
    next window instead of stopping. With no window set (full refresh, or the first incremental
    sync where there is no watermark yet) it is plain cursor pagination over the whole history.
    """

    def __init__(
        self,
        limit: int,
        date_field: Optional[str] = None,
        window_start: Optional[datetime] = None,
        window_end: Optional[datetime] = None,
    ) -> None:
        super().__init__()
        self.limit = limit
        self.date_field = date_field if (window_start is not None and window_end is not None) else None
        self._final_end = window_end if self.date_field else None
        self._window_start = window_start if self.date_field else None
        self._window_end: Optional[datetime] = None
        if self._window_start is not None and self._final_end is not None:
            self._window_end = min(self._window_start + MAX_FILTER_WINDOW, self._final_end)
        self._cursor: Optional[str] = None

    def _apply_params(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["limit"] = self.limit
        if self._cursor is None:
            request.params.pop("cursor", None)
        else:
            request.params["cursor"] = self._cursor
        if self.date_field and self._window_start is not None and self._window_end is not None:
            request.params[f"{self.date_field}__gte"] = _format_datetime(self._window_start)
            request.params[f"{self.date_field}__lte"] = _format_datetime(self._window_end)

    def init_request(self, request: Request) -> None:
        self._apply_params(request)

    def update_request(self, request: Request) -> None:
        self._apply_params(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        next_cursor: Any = None
        try:
            body = response.json()
        except ValueError:
            body = None
        if isinstance(body, dict):
            next_cursor = body.get("next_cursor")

        if next_cursor:
            self._cursor = str(next_cursor)
            self._has_next_page = True
            return

        self._cursor = None
        self._has_next_page = self._advance_window()

    def _advance_window(self) -> bool:
        if self._window_end is None or self._final_end is None or self._window_end >= self._final_end:
            return False
        # Windows share their boundary instant because both bounds are inclusive; the merge on
        # primary key collapses the handful of rows that lands in two windows.
        self._window_start = self._window_end
        self._window_end = min(self._window_end + MAX_FILTER_WINDOW, self._final_end)
        return True

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        if not self._has_next_page:
            return None
        state: dict[str, Any] = {}
        if self._cursor is not None:
            state["cursor"] = self._cursor
        if self.date_field and self._window_start is not None and self._window_end is not None:
            state["window_start"] = _format_datetime(self._window_start)
            state["window_end"] = _format_datetime(self._window_end)
        return state or None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        cursor = state.get("cursor")
        self._cursor = str(cursor) if cursor else None
        window_start = state.get("window_start")
        window_end = state.get("window_end")
        if self.date_field and window_start and window_end:
            parsed_start = _parse_datetime(str(window_start))
            parsed_end = _parse_datetime(str(window_end))
            if parsed_start is not None and parsed_end is not None:
                self._window_start = parsed_start
                self._window_end = parsed_end
        self._has_next_page = True


def _client_config(api_key: str, limit: int) -> ClientConfig:
    return {
        "base_url": YOCO_BASE_URL,
        "auth": {"type": "bearer", "token": api_key},
        "headers": {"Accept": "application/json"},
        # Pin every request (and its bearer token) to api.yoco.com and refuse redirects, so a
        # server-side 3xx can never replay the credential off-host.
        "allowed_hosts": [],
        "allow_redirects": False,
        "paginator": YocoCursorPaginator(limit=limit),
        "request_timeout": REQUEST_TIMEOUT_SECONDS,
    }


def _resolve_date_field(config: YocoEndpointConfig, incremental_field: Optional[str]) -> Optional[str]:
    advertised = {f["field"] for f in config.incremental_fields}
    if incremental_field in advertised:
        return incremental_field
    return config.default_incremental_field


def get_resource(
    endpoint: str,
    should_use_incremental_field: bool,
    incremental_field: Optional[str] = None,
    db_incremental_field_last_value: Optional[Any] = None,
) -> EndpointResource:
    config = YOCO_ENDPOINTS[endpoint]
    if config.fanout:
        raise ValueError(f"Fan-out endpoint '{endpoint}' must use the fan-out path")

    use_incremental = should_use_incremental_field and bool(config.incremental_fields)
    window_start = coerce_datetime_to_utc(db_incremental_field_last_value) if use_incremental else None

    endpoint_config: Endpoint = {
        "path": config.path,
        "params": {},
        "data_selector": "data",
        # The `data` envelope is documented on every list endpoint, so a response without it
        # means the shape changed — fail loud instead of silently syncing zero rows.
        "data_selector_required": True,
        "paginator": YocoCursorPaginator(
            limit=config.page_size,
            date_field=_resolve_date_field(config, incremental_field) if use_incremental else None,
            window_start=window_start,
            window_end=datetime.now(UTC) if window_start is not None else None,
        ),
    }

    return {
        "name": config.name,
        "table_name": config.name,
        "write_disposition": {"disposition": "merge", "strategy": "upsert"} if use_incremental else "replace",
        "endpoint": endpoint_config,
        "table_format": "delta",
    }


def _source_response(
    config: YocoEndpointConfig,
    items_fn: Callable[[], Iterable[Any]],
    sort_mode: SortMode,
) -> SourceResponse:
    return SourceResponse(
        name=config.name,
        items=items_fn,
        primary_keys=config.primary_key,
        sort_mode=sort_mode,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def yoco_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: Optional[ResumableSourceManager[YocoResumeConfig]] = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: Optional[str] = None,
) -> SourceResponse:
    config = YOCO_ENDPOINTS[endpoint]
    initial_paginator_state: Optional[dict[str, Any]] = None
    resume_state: Optional[YocoResumeConfig] = None

    if resumable_source_manager is not None and resumable_source_manager.can_resume():
        resume_state = resumable_source_manager.load_state()

    if config.fanout:
        if resume_state is not None and resume_state.completed is not None:
            initial_paginator_state = {
                "completed": resume_state.completed,
                "current": resume_state.current,
                "child_state": resume_state.child_state,
            }

        def save_fanout_checkpoint(state: Optional[dict[str, Any]]) -> None:
            if resumable_source_manager is None or not state:
                return
            resumable_source_manager.save_state(
                YocoResumeConfig(
                    completed=list(state.get("completed") or []),
                    current=state.get("current"),
                    child_state=state.get("child_state"),
                )
            )

        dependent_resource = cast(
            Iterable[Any],
            build_dependent_resource(
                endpoint_configs=YOCO_ENDPOINTS,
                child_endpoint=endpoint,
                fanout=config.fanout,
                client_config=_client_config(api_key, config.page_size),
                path_format_values={},
                team_id=team_id,
                job_id=job_id,
                db_incremental_field_last_value=None,
                should_use_incremental_field=False,
                parent_endpoint_extra={"data_selector": "data", "data_selector_required": True},
                child_endpoint_extra={"data_selector": "data", "data_selector_required": True},
                # The client paginator already sends `limit`, and it is the one that knows how
                # to read `next_cursor`, so the fan-out helper must not add its own size param.
                page_size_param=None,
                resume_hook=save_fanout_checkpoint if resumable_source_manager is not None else None,
                initial_paginator_state=initial_paginator_state,
            ),
        )
        return _source_response(config, lambda: dependent_resource, sort_mode="asc")

    if resume_state is not None and (resume_state.cursor or resume_state.window_start):
        initial_paginator_state = {
            "cursor": resume_state.cursor,
            "window_start": resume_state.window_start,
            "window_end": resume_state.window_end,
        }

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Only persist while there is another page or window to resume to; the Redis TTL
        # cleans up on completion.
        if resumable_source_manager is None or not state:
            return
        resumable_source_manager.save_state(
            YocoResumeConfig(
                cursor=state.get("cursor"),
                window_start=state.get("window_start"),
                window_end=state.get("window_end"),
            )
        )

    rest_config: RESTAPIConfig = {
        "client": _client_config(api_key, config.page_size),
        "resource_defaults": {},
        "resources": [
            get_resource(endpoint, should_use_incremental_field, incremental_field, db_incremental_field_last_value)
        ],
    }

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint if resumable_source_manager is not None else None,
        initial_paginator_state=initial_paginator_state,
    )

    # Yoco documents no ordering for its cursor pages, so an incremental sync runs with desc
    # semantics: the pipeline holds the watermark until the run finishes rather than advancing
    # it per batch, and an interrupted run repeats its window instead of skipping rows it
    # never fetched.
    sort_mode: SortMode = "desc" if (should_use_incremental_field and config.incremental_fields) else "asc"
    return _source_response(config, lambda: resource, sort_mode=sort_mode)


def _probe(api_key: str, path: str) -> Response:
    session = make_tracked_session(redact_values=(api_key,), allow_redirects=False)
    return session.get(
        f"{YOCO_BASE_URL}{path}",
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        params={"limit": 1},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    response = _probe(api_key, YOCO_ENDPOINTS["payments"].path)
    # 403 means the token is genuine but lacks `business/orders:read`. Keys can legitimately be
    # scoped to only the catalogue or payouts, so that is not a bad credential — the per-table
    # check reports which tables the key can actually reach.
    if response.status_code in (200, 403):
        return True, None
    if response.status_code == 401:
        return False, "Yoco rejected the API key. Create a new key in the Yoco Developer Console and reconnect."
    return False, f"Yoco API returned an unexpected status code: {response.status_code}"


def get_endpoint_permissions(api_key: str, endpoints: list[str]) -> dict[str, str | None]:
    permissions: dict[str, str | None] = {}
    # Several endpoints share a scope, so probe each distinct path once.
    probed: dict[str, int] = {}
    for name in endpoints:
        config = YOCO_ENDPOINTS.get(name)
        if config is None:
            permissions[name] = None
            continue
        # Payout entries can only be reached through a payout id; the parent list endpoint
        # needs the same scope, so probing it answers for both.
        path = YOCO_ENDPOINTS[config.fanout.parent_name].path if config.fanout else config.path
        if path not in probed:
            try:
                probed[path] = _probe(api_key, path).status_code
            except Exception:
                # A throttle or network blip is not a missing scope — report reachable and let
                # the sync surface a real failure.
                probed[path] = 200
        status = probed[path]
        if status == 403:
            scope = ENDPOINT_SCOPES.get(name)
            permissions[name] = (
                f"Your Yoco API key is missing the `{scope}` scope." if scope else "Your Yoco API key lacks access."
            )
        else:
            permissions[name] = None
    return permissions
