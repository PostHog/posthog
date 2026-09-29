import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import BasePaginator
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import Endpoint
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.float_app.settings import (
    DELETE_LOG_LIMIT,
    FLOAT_ENDPOINTS,
    PER_PAGE,
    PUBLIC_HOLIDAY_YEARS_AHEAD,
    PUBLIC_HOLIDAY_YEARS_BACK,
    REPORT_LOOKBACK_MONTHS,
    FloatEndpointConfig,
)

FLOAT_BASE_URL = "https://api.float.com/v3"
# Float rejects requests without a User-Agent that identifies the app and a contact email. This is a
# static integration identifier, not user data, so it's hardcoded rather than surfaced as a form field.
USER_AGENT = "PostHog Data Warehouse (hey@posthog.com)"


@dataclasses.dataclass
class FloatAppResumeConfig:
    # Page-number endpoints resume from `next_page` (1-indexed); Delete Log endpoints resume from the
    # opaque `next_cursor`; report endpoints resume from the first day of the next unfetched month.
    # Only one is set per endpoint. None means "start from the beginning".
    next_page: int | None = None
    next_cursor: str | None = None
    next_window_start: str | None = None


def _non_auth_headers() -> dict[str, str]:
    # Auth (Bearer) is supplied via the framework auth config so its value is redacted from logs and
    # raised errors; only the non-secret accept/user-agent headers are set here.
    return {"Accept": "application/json", "User-Agent": USER_AGENT}


def _header_int(headers: Any, name: str) -> int | None:
    raw = headers.get(name)
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


class FloatPagePaginator(BasePaginator):
    """Page-number pagination for Float's core resources.

    Total pages come from the `X-Pagination-Pages` response header; when it's absent we fall back to a
    full-page heuristic (a page of exactly `per-page` items may be followed by another). Resumes from a
    saved 1-indexed page.
    """

    def __init__(self, per_page: int = PER_PAGE) -> None:
        super().__init__()
        self.per_page = per_page
        self.page = 1

    def init_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["per-page"] = self.per_page
        request.params["page"] = self.page

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        items = data or []
        if not items:
            self._has_next_page = False
            return

        total_pages = _header_int(response.headers, "X-Pagination-Pages")
        has_more = self.page < total_pages if total_pages is not None else len(items) >= self.per_page
        self._has_next_page = has_more
        if has_more:
            self.page += 1

    def update_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["page"] = self.page

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {"next_page": self.page} if self._has_next_page else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        next_page = state.get("next_page")
        if next_page is not None:
            self.page = int(next_page)
            self._has_next_page = True


class FloatCursorPaginator(BasePaginator):
    """Cursor pagination for Float's Delete Log endpoints.

    Termination is defensive: stop on a missing/blank/repeated `X-Pagination-Next-Cursor`, an explicit
    `X-Pagination-Has-More=false`, or a short page. That guarantees the loop ends even if the delete-log
    pagination header names differ from the documented ones (they can't be verified without a live token).
    """

    def __init__(self, limit: int = DELETE_LOG_LIMIT) -> None:
        super().__init__()
        self.limit = limit
        # Cursor to send on the NEXT request (None on the first page); the cursor actually sent on the
        # current request is tracked separately so we can detect a non-advancing cursor.
        self._cursor: Optional[str] = None
        self._current_cursor: Optional[str] = None

    def init_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["limit"] = self.limit
        if self._cursor is not None:
            request.params["cursor"] = self._cursor
        self._current_cursor = self._cursor

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        items = data or []
        next_cursor = response.headers.get("X-Pagination-Next-Cursor") or None
        has_more_header = response.headers.get("X-Pagination-Has-More")
        has_more_false = has_more_header is not None and str(has_more_header).strip().lower() in ("false", "0", "no")

        page_full = len(items) >= self.limit
        advances = bool(next_cursor) and next_cursor != self._current_cursor
        keep_going = page_full and advances and not has_more_false

        self._has_next_page = keep_going
        if keep_going:
            self._cursor = next_cursor

    def update_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["limit"] = self.limit
        if self._cursor is not None:
            request.params["cursor"] = self._cursor
        self._current_cursor = self._cursor

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {"next_cursor": self._cursor} if self._has_next_page and self._cursor is not None else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        next_cursor = state.get("next_cursor")
        if next_cursor is not None:
            self._cursor = str(next_cursor)
            self._has_next_page = True


def _auth_headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}", **_non_auth_headers()}


def _public_holiday_window(today: date) -> dict[str, Any]:
    start = date(today.year - PUBLIC_HOLIDAY_YEARS_BACK, 1, 1)
    end = date(today.year + PUBLIC_HOLIDAY_YEARS_AHEAD, 12, 31)
    return {"start_date": start.isoformat(), "end_date": end.isoformat()}


def _month_windows(today: date, lookback_months: int) -> list[tuple[str, str]]:
    """Calendar months from `lookback_months` before this month through this month, oldest first."""
    month_index = today.year * 12 + (today.month - 1)
    windows: list[tuple[str, str]] = []
    for offset in range(lookback_months, -1, -1):
        year, month = divmod(month_index - offset, 12)
        start = date(year, month + 1, 1)
        next_year, next_month = divmod(month_index - offset + 1, 12)
        end = date(next_year, next_month + 1, 1) - timedelta(days=1)
        windows.append((start.isoformat(), end.isoformat()))
    return windows


def _report_window_pages(
    api_key: str,
    config: FloatEndpointConfig,
    resumable_source_manager: ResumableSourceManager[FloatAppResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    """Walk an unpaginated report endpoint one calendar month at a time.

    Float's report endpoints take a required `start_date`/`end_date`, return the aggregate over that
    window under a single envelope key, and expose no pagination. Each window is one request, so the
    resume cursor is the next month still to fetch.
    """
    windows = _month_windows(datetime.now(UTC).date(), REPORT_LOOKBACK_MONTHS)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.next_window_start is not None:
        windows = [window for window in windows if window[0] >= resume.next_window_start]

    # The envelope key matches the last path segment, e.g. `/reports/people` -> {"people": [...]}.
    envelope_key = config.path.rsplit("/", 1)[-1]
    session = make_tracked_session(redact_values=(api_key,))
    headers = _auth_headers(api_key)

    for index, (start, end) in enumerate(windows):
        response = session.get(
            f"{FLOAT_BASE_URL}{config.path}",
            headers=headers,
            params={"start_date": start, "end_date": end},
        )
        response.raise_for_status()
        rows = response.json().get(envelope_key) or []
        # Stamp the window on every row: the figures are an aggregate over it, so without these the
        # months are indistinguishable and every row collides on the primary key.
        for row in rows:
            row["start_date"] = start
            row["end_date"] = end

        if rows:
            yield rows

        remaining = windows[index + 1 :]
        if remaining:
            resumable_source_manager.save_state(FloatAppResumeConfig(next_window_start=remaining[0][0]))


def float_app_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[FloatAppResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = FLOAT_ENDPOINTS[endpoint]

    if config.pagination == "report_window":
        return SourceResponse(
            name=endpoint,
            items=lambda: _report_window_pages(api_key, config, resumable_source_manager),
            primary_keys=config.primary_keys,
            partition_count=1,
            partition_size=1,
            partition_mode="datetime",
            partition_format="month",
            partition_keys=[config.partition_key] if config.partition_key else None,
        )

    paginator: BasePaginator
    if config.pagination == "cursor":
        paginator = FloatCursorPaginator(limit=DELETE_LOG_LIMIT)
    else:
        paginator = FloatPagePaginator(per_page=PER_PAGE)

    endpoint_config: Endpoint = {
        "path": config.path,
        # Float list endpoints return a bare JSON array; the whole body is the row list.
        "data_selector": None,
    }
    if config.date_window:
        endpoint_config["params"] = _public_holiday_window(datetime.now(UTC).date())

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": FLOAT_BASE_URL,
            "headers": _non_auth_headers(),
            "auth": {"type": "bearer", "token": api_key},
            "paginator": paginator,
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": endpoint_config,
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            if config.pagination == "cursor":
                if resume.next_cursor is not None:
                    initial_paginator_state = {"next_cursor": resume.next_cursor}
            elif resume.next_page is not None:
                initial_paginator_state = {"next_page": resume.next_page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields the
        # last page (merge dedupes on the primary key) rather than skipping it.
        if not state:
            return
        if state.get("next_page") is not None:
            resumable_source_manager.save_state(FloatAppResumeConfig(next_page=int(state["next_page"])))
        elif state.get("next_cursor") is not None:
            resumable_source_manager.save_state(FloatAppResumeConfig(next_cursor=str(state["next_cursor"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )


def validate_credentials(api_key: str) -> tuple[bool, int | None]:
    """Probe Float's `/accounts` endpoint to confirm the token is genuine.

    Returns ``(ok, status_code)``. ``status_code`` is ``None`` on a transport error. Float uses a single
    account-owner token with full access, so a 200 means the whole API is reachable.
    """
    return validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{FLOAT_BASE_URL}/accounts?per-page=1",
        headers=_auth_headers(api_key),
    )
