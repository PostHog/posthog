import dataclasses
from typing import Any, Optional

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import BasePaginator
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.float_app.settings import (
    DELETE_LOG_LIMIT,
    FLOAT_ENDPOINTS,
    PER_PAGE,
)

FLOAT_BASE_URL = "https://api.float.com/v3"
# Float rejects requests without a User-Agent that identifies the app and a contact email. This is a
# static integration identifier, not user data, so it's hardcoded rather than surfaced as a form field.
USER_AGENT = "PostHog Data Warehouse (hey@posthog.com)"


@dataclasses.dataclass
class FloatAppResumeConfig:
    # Page-number endpoints resume from `next_page` (1-indexed); Delete Log endpoints resume from the
    # opaque `next_cursor`. Only one is set per endpoint. None means "start from the beginning".
    next_page: int | None = None
    next_cursor: str | None = None


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


def float_app_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[FloatAppResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = FLOAT_ENDPOINTS[endpoint]

    paginator: BasePaginator
    if config.pagination == "cursor":
        paginator = FloatCursorPaginator(limit=DELETE_LOG_LIMIT)
    else:
        paginator = FloatPagePaginator(per_page=PER_PAGE)

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
                "endpoint": {
                    "path": config.path,
                    # Float list endpoints return a bare JSON array; the whole body is the row list.
                    "data_selector": None,
                },
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
        headers={"Authorization": f"Bearer {api_key}", **_non_auth_headers()},
    )
