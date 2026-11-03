import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional

from requests import Request, Response
from requests.auth import HTTPBasicAuth

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import (
    default_request_timeout,
    make_tracked_session,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.onfleet.settings import (
    ONFLEET_ENDPOINTS,
    OnfleetEndpointConfig,
)

ONFLEET_BASE_URL = "https://onfleet.com/api/v2"
# `/tasks/all` requires a `from` param; epoch 0 pulls the full history on the initial/full sync.
DEFAULT_FROM_MS = 0
# Key carrying the `lastId` cursor in the `/tasks/all` response body and the query param used to
# continue after it on the next page.
_CURSOR_KEY = "lastId"
# `/routePlans` returns at most this many rows per request (its max `limit`) and has no cursor.
ROUTE_PLANS_LIMIT = 500


@dataclasses.dataclass(frozen=True)
class OnfleetResumeConfig:
    # `/tasks/all`: the `lastId` cursor returned by the previous page; the next request continues after it.
    last_id: Optional[str] = None
    # `/tasks/all`: the `from` epoch-ms lower bound in effect for this sync, re-sent on every page so
    # the server-side window stays applied across the whole paginated walk.
    # `/routePlans`: the epoch-ms start of the next created-time window.
    from_ms: int = 0
    # `/routePlans`: the width of the next created-time window, in milliseconds.
    window_ms: Optional[int] = None


def _to_epoch_ms(value: Any) -> Optional[int]:
    """Coerce an incremental cursor value to UNIX epoch milliseconds for Onfleet's `from` filter.

    Onfleet stores and filters timestamps as epoch milliseconds, so the persisted watermark is
    already an int in the common case; datetimes/dates are accepted defensively.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, datetime):
        dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return int(dt.timestamp() * 1000)
    if isinstance(value, date):
        return int(datetime.combine(value, datetime.min.time(), tzinfo=UTC).timestamp() * 1000)
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class OnfleetTasksPaginator(BasePaginator):
    """Cursor paginator for `/tasks/all`: the response body carries the next `lastId`, which is
    sent back as a query param to fetch the following page.

    Termination matches the hand-rolled walk it replaces: stop on a missing OR non-advancing
    cursor (the server echoing the same `lastId` must not loop forever). Resume state is only
    reported after a page that actually yielded rows, so a crash re-yields the last non-empty page
    (merge dedupes) rather than checkpointing an empty page.
    """

    def __init__(self) -> None:
        super().__init__()
        # The `lastId` that the NEXT request should carry (None on the first page).
        self._cursor: Optional[str] = None
        # Whether the most recent page returned any rows — gates whether a checkpoint is offered.
        self._last_page_had_data = False

    def init_request(self, request: Request) -> None:
        # Apply a seeded resume cursor to the first request.
        if self._cursor is not None:
            request.params = request.params or {}
            request.params[_CURSOR_KEY] = self._cursor

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        self._last_page_had_data = bool(data)
        try:
            next_cursor = response.json().get(_CURSOR_KEY)
        except Exception:
            next_cursor = None
        if next_cursor and next_cursor != self._cursor:
            self._cursor = next_cursor
            self._has_next_page = True
        else:
            self._has_next_page = False

    def update_request(self, request: Request) -> None:
        if self._has_next_page and self._cursor is not None:
            request.params = request.params or {}
            request.params[_CURSOR_KEY] = self._cursor

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        # Only checkpoint after a page that yielded rows, mirroring the old "save after yielding
        # items" behavior — an empty page with an advancing cursor is re-walked on resume.
        if self._has_next_page and self._cursor is not None and self._last_page_had_data:
            return {"cursor": self._cursor}
        return None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        cursor = state.get("cursor")
        if cursor is not None:
            self._cursor = cursor
            self._has_next_page = True


def _paginated_source(
    api_key: str,
    endpoint: str,
    config: OnfleetEndpointConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[OnfleetResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Any:
    from_ms = _to_epoch_ms(db_incremental_field_last_value) if should_use_incremental_field else None
    if from_ms is None:
        from_ms = DEFAULT_FROM_MS

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.last_id is not None:
            initial_paginator_state = {"cursor": resume.last_id}
            # Re-apply the window the interrupted sync used so resumed pages stay on it.
            from_ms = resume.from_ms

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": ONFLEET_BASE_URL,
            "headers": {"Accept": "application/json"},
            # Onfleet uses HTTP Basic auth with the API key as the username and an empty password.
            "auth": {"type": "http_basic", "username": api_key, "password": ""},
            "paginator": OnfleetTasksPaginator(),
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    # `from` is a static server-side window re-sent on every page; the paginator
                    # only adds the `lastId` cursor.
                    "params": {"from": from_ms},
                    "data_selector": config.data_key,
                },
            }
        ],
    }

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state and state.get("cursor") is not None:
            resumable_source_manager.save_state(OnfleetResumeConfig(last_id=state["cursor"], from_ms=from_ms))

    return rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


def _single_batch_source(
    api_key: str,
    endpoint: str,
    config: OnfleetEndpointConfig,
    team_id: int,
    job_id: str,
    db_incremental_field_last_value: Any,
) -> Any:
    # Every non-`/tasks/all` endpoint returns its whole collection in one response with no
    # pagination: a bare JSON array, or a single object (`/organization`) the framework wraps.
    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": ONFLEET_BASE_URL,
            "headers": {"Accept": "application/json"},
            "auth": {"type": "http_basic", "username": api_key, "password": ""},
            "paginator": SinglePagePaginator(),
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {"path": config.path},
            }
        ],
    }

    return rest_api_resource(rest_config, team_id, job_id, db_incremental_field_last_value)


def _now_ms() -> int:
    return int(datetime.now(UTC).timestamp() * 1000)


def _created_before(row: dict[str, Any], end_ms: int) -> bool:
    created_ms = _to_epoch_ms(row.get("timeCreated"))
    return created_ms is None or created_ms < end_ms


def _iter_route_plans(
    api_key: str,
    config: OnfleetEndpointConfig,
    resumable_source_manager: ResumableSourceManager[OnfleetResumeConfig],
    from_ms: int,
) -> Iterator[list[dict[str, Any]]]:
    """Walk `/routePlans` in `createdTimeFrom`/`createdTimeTo` windows.

    A window that returns a full page can be truncated, so it is halved and fetched again. A window
    that returns less is complete, and the next window is twice as wide. The docs don't say whether
    `createdTimeTo` is inclusive, so each window keeps only the rows created before its end, and the
    next window starts at that end.
    """
    session = make_tracked_session(redact_values=(api_key,))
    auth = HTTPBasicAuth(api_key, "")
    until_ms = _now_ms()
    window_start = from_ms
    window_ms = max(until_ms - window_start, 1)

    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.window_ms is not None:
            window_start = resume.from_ms
            window_ms = max(resume.window_ms, 1)

    while True:
        window_end = min(window_start + window_ms, until_ms)
        is_last_window = window_end >= until_ms
        response = session.get(
            f"{ONFLEET_BASE_URL}{config.path}",
            params={"createdTimeFrom": window_start, "createdTimeTo": window_end, "limit": ROUTE_PLANS_LIMIT},
            auth=auth,
            timeout=default_request_timeout(),
        )
        response.raise_for_status()
        rows = response.json()
        # A full refresh replaces the table, so a malformed response must fail the sync rather than
        # silently drop rows.
        if not isinstance(rows, list):
            raise ValueError(f"Onfleet returned a non-list response for {config.path}")

        if len(rows) >= ROUTE_PLANS_LIMIT:
            if window_end - window_start > 1:
                window_ms = max((window_end - window_start) // 2, 1)
                resumable_source_manager.safe_point()
                continue
            # A 1 ms window can't be split further, so advancing past it would silently drop rows.
            raise ValueError(
                f"Onfleet returned {ROUTE_PLANS_LIMIT} or more route plans created between {window_start} and "
                f"{window_end} (epoch ms), which can't be fetched completely"
            )

        if is_last_window:
            if rows:
                yield rows
            return

        rows = [row for row in rows if _created_before(row, window_end)]
        window_ms = (window_end - window_start) * 2
        window_start = window_end
        resumable_source_manager.save_state(OnfleetResumeConfig(from_ms=window_start, window_ms=window_ms))
        if rows:
            yield rows
        else:
            resumable_source_manager.safe_point()


def onfleet_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[OnfleetResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = ONFLEET_ENDPOINTS[endpoint]

    if config.created_time_windowed:
        from_ms = _to_epoch_ms(db_incremental_field_last_value) if should_use_incremental_field else None
        windowed_from_ms = DEFAULT_FROM_MS if from_ms is None else from_ms
        return SourceResponse(
            name=endpoint,
            items=lambda: _iter_route_plans(api_key, config, resumable_source_manager, windowed_from_ms),
            primary_keys=config.primary_keys,
            # Windows are walked in ascending order, but rows inside a window are unordered.
            sort_mode=None,
        )

    if config.paginated:
        resource = _paginated_source(
            api_key=api_key,
            endpoint=endpoint,
            config=config,
            team_id=team_id,
            job_id=job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        )
    else:
        resource = _single_batch_source(
            api_key=api_key,
            endpoint=endpoint,
            config=config,
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=db_incremental_field_last_value,
        )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        # `/tasks/all` returns rows ascending by creation time; the single-batch endpoints are
        # order-insensitive. Onfleet timestamps are epoch-ms integers, which the datetime
        # partitioner would misbucket (it treats ints as epoch seconds), so partitioning is off.
        sort_mode="asc",
    )


def get_credentials_status(api_key: str) -> Optional[int]:
    """Return the HTTP status of a cheap authenticated probe, or None on transport failure.

    `/organization` returns the caller's own organization — a light authenticated endpoint that
    only confirms the API key is genuine, not per-endpoint scope.
    """
    _ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{ONFLEET_BASE_URL}/organization",
        auth=HTTPBasicAuth(api_key, ""),
    )
    return status
