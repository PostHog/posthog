import dataclasses
from typing import Any, Optional

from requests import Request, Response, Session

from products.warehouse_sources.backend.temporal.data_imports.sources.browser_use.settings import (
    BROWSER_USE_API_VERSION_V3,
    BrowserUseEndpointConfig,
    endpoints_for_version,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import BasePaginator
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

BROWSER_USE_API_HOST = "https://api.browser-use.com"
API_KEY_HEADER = "X-Browser-Use-API-Key"


def _base_url(api_version: str) -> str:
    # The version is a URL path segment; auth and host are identical across versions.
    return f"{BROWSER_USE_API_HOST}/api/{api_version}"


# v3 base URL, kept as a module constant: it's what the credential probe and non-retryable error
# matcher pin to (both are host-scoped, so v3 stands in for every version there).
BROWSER_USE_BASE_URL = _base_url(BROWSER_USE_API_VERSION_V3)


@dataclasses.dataclass
class BrowserUseResumeConfig:
    # Next 1-indexed page/pageNumber to fetch for an offset-paged top-level endpoint. None otherwise.
    page: int | None = None
    # Next opaque keyset cursor for a v4 top-level endpoint (sessions, runs). None otherwise.
    cursor: str | None = None
    # Legacy fan-out bookmark fields (session id + `after` message cursor). Kept with defaults so
    # state saved before the framework migration still parses; such state restarts the fan-out
    # fresh (merge dedupes the re-pulled rows on the [sessionId, id] primary key).
    session_id: str | None = None
    after: str | None = None
    # Framework fan-out checkpoint for session_messages (completed/current child paths plus the
    # in-progress child paginator state).
    fanout_state: dict[str, Any] | None = None


class BrowserUsePagePaginator(BasePaginator):
    """1-indexed page-number pagination with a total-ITEMS stop and a short-page stop.

    The built-in ``PageNumberPaginator`` interprets ``total_path`` as a page count and pays one
    extra empty-page request when no total is present; Browser Use reports the total number of
    ITEMS (``total`` / ``totalItems``) and its lists guarantee full pages until the last, so a
    short page also terminates without an extra request.
    """

    def __init__(self, page_param: str, page_size: int, total_key: str) -> None:
        super().__init__()
        self.page_param = page_param
        self.page_size = page_size
        self.total_key = total_key
        self.page = 1

    def _inject(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params[self.page_param] = self.page

    def init_request(self, request: Request) -> None:
        self._inject(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        if data is None or len(data) == 0:
            self._has_next_page = False
            return

        self.page += 1

        total: Any = None
        try:
            body = response.json()
            if isinstance(body, dict):
                total = body.get(self.total_key)
        except Exception:
            total = None

        if isinstance(total, int):
            # self.page now points at the NEXT page; the one just fetched is self.page - 1.
            self._has_next_page = (self.page - 1) * self.page_size < total
            return

        # No total reported: a short page means the end was reached.
        self._has_next_page = len(data) >= self.page_size

    def update_request(self, request: Request) -> None:
        self._inject(request)

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        # self.page already points at the next page to fetch (update_state incremented it).
        return {"page": self.page} if self._has_next_page else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        page = state.get("page")
        if page is not None:
            self.page = int(page)
            self._has_next_page = True

    def __str__(self) -> str:
        return f"BrowserUsePagePaginator(page_param={self.page_param}, page={self.page})"


class BrowserUseMessagesPaginator(BasePaginator):
    """`after`-cursor pagination for GET /sessions/{id}/messages.

    The cursor is the id of the last message on the page (not a body field a jsonpath could
    select), and the stop signal is the body's ``hasMore`` flag — a page with rows but
    ``hasMore: false`` must terminate, which the built-in cursor paginator can't express.
    """

    def __init__(self) -> None:
        super().__init__()
        self._after: Optional[str] = None

    def _inject(self, request: Request) -> None:
        if self._after is not None:
            if request.params is None:
                request.params = {}
            request.params["after"] = self._after

    def init_request(self, request: Request) -> None:
        self._inject(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        has_more = False
        try:
            body = response.json()
            if isinstance(body, dict):
                has_more = bool(body.get("hasMore"))
        except Exception:
            has_more = False

        if has_more and data:
            self._after = data[-1]["id"]
            self._has_next_page = True
        else:
            self._has_next_page = False

    def update_request(self, request: Request) -> None:
        self._inject(request)

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {"after": self._after} if self._has_next_page and self._after is not None else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        after = state.get("after")
        if after is not None:
            self._after = after
            self._has_next_page = True

    def __str__(self) -> str:
        return f"BrowserUseMessagesPaginator(after={self._after})"


class BrowserUseKeysetPaginator(BasePaginator):
    """Keyset cursor pagination for the v4 list endpoints (`GET /sessions`, `GET /runs`).

    The cursor is an opaque server token echoed back in the body as ``nextCursor`` (not the last
    row's id, unlike ``BrowserUseMessagesPaginator``), and ``hasMore`` is the stop signal — a page
    with rows but ``hasMore: false`` terminates.
    """

    def __init__(self, cursor_param: str = "cursor", next_cursor_key: str = "nextCursor") -> None:
        super().__init__()
        self.cursor_param = cursor_param
        self.next_cursor_key = next_cursor_key
        self._cursor: Optional[str] = None

    def _inject(self, request: Request) -> None:
        if self._cursor is not None:
            if request.params is None:
                request.params = {}
            request.params[self.cursor_param] = self._cursor

    def init_request(self, request: Request) -> None:
        self._inject(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        has_more = False
        next_cursor: Any = None
        try:
            body = response.json()
            if isinstance(body, dict):
                has_more = bool(body.get("hasMore"))
                next_cursor = body.get(self.next_cursor_key)
        except Exception:
            has_more = False

        if has_more and next_cursor:
            self._cursor = str(next_cursor)
            self._has_next_page = True
        else:
            self._has_next_page = False

    def update_request(self, request: Request) -> None:
        self._inject(request)

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {"cursor": self._cursor} if self._has_next_page and self._cursor is not None else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        cursor = state.get("cursor")
        if cursor is not None:
            self._cursor = str(cursor)
            self._has_next_page = True

    def __str__(self) -> str:
        return f"BrowserUseKeysetPaginator(cursor={self._cursor})"


# Params the offset-paging styles use: (page param, page-size param, total-items body key).
_PAGINATION_PARAMS: dict[str, tuple[str, str, str]] = {
    "page": ("page", "page_size", "total"),
    "pageNumber": ("pageNumber", "pageSize", "totalItems"),
}


def _list_size_param(config: BrowserUseEndpointConfig) -> str:
    # The page-size query param name for a list endpoint, keyed off its pagination style.
    if config.pagination == "keyset":
        return "limit"
    return _PAGINATION_PARAMS[config.pagination][1]


def _make_session(api_key: str) -> Session:
    # capture=False: session titles and session_messages.data hold arbitrary user/agent content the
    # name-based scrubbers can't recognise, so exclude the bodies from HTTP sample capture entirely.
    # allow_redirects=False: the API key rides in a custom header that `requests` preserves across
    # cross-host 3xx (it only strips `Authorization`), so pin redirects off to keep it from
    # replaying to a redirect target. The fixed API host never needs redirects.
    return make_tracked_session(redact_values=(api_key,), capture=False, allow_redirects=False)


def _client_config(api_key: str, base_url: str) -> ClientConfig:
    return {
        "base_url": base_url,
        "headers": {"Accept": "application/json"},
        # Auth via the framework config so the key is registered for log redaction.
        "auth": {"type": "api_key", "api_key": api_key, "name": API_KEY_HEADER, "location": "header"},
        "session": _make_session(api_key),
    }


def _list_endpoint_resource(config: BrowserUseEndpointConfig) -> EndpointResource:
    if config.pagination == "keyset":
        return {
            "name": config.name,
            "endpoint": {
                "path": config.path,
                "params": {_list_size_param(config): config.page_size},
                "data_selector": config.data_key,
                "paginator": BrowserUseKeysetPaginator(),
            },
        }

    page_param, size_param, total_key = _PAGINATION_PARAMS[config.pagination]
    return {
        "name": config.name,
        "endpoint": {
            "path": config.path,
            "params": {size_param: config.page_size},
            # A missing data key is treated as an empty page (matching the API's envelope for
            # zero rows), which terminates pagination.
            "data_selector": config.data_key,
            "paginator": BrowserUsePagePaginator(
                page_param=page_param, page_size=config.page_size, total_key=total_key
            ),
        },
    }


def _stamp_parent_session_id(row: dict[str, Any]) -> dict[str, Any]:
    # The child endpoint may omit the session id from each message, but it's half of the declared
    # [sessionId, id] primary key, so the merge needs it present. `pop` without a default on
    # purpose: a silent None here would collapse rows across sessions.
    row["sessionId"] = row.pop("_sessions_id")
    return row


def browser_use_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[BrowserUseResumeConfig],
    api_version: str,
) -> SourceResponse:
    catalog = endpoints_for_version(api_version)
    config = catalog[endpoint]
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    rest_config: RESTAPIConfig = {
        "client": _client_config(api_key, _base_url(api_version)),
        "resource_defaults": {},
        "resources": [],
    }

    resource: Resource
    if config.fan_out_over_sessions:
        # session_messages: fan out one cursor-paginated request per agent session. The framework
        # checkpoints completed child paths and the in-progress child cursor; the (cheap) parent
        # session list is re-fetched on every attempt.
        def save_fanout_checkpoint(state: Optional[dict[str, Any]]) -> None:
            if state is not None:
                resumable_source_manager.save_state(BrowserUseResumeConfig(fanout_state=state))

        sessions_config = catalog["sessions"]
        rest_config["resources"] = [
            _list_endpoint_resource(sessions_config),
            {
                "name": config.name,
                "include_from_parent": ["id"],
                "data_map": _stamp_parent_session_id,
                "endpoint": {
                    "path": config.path,
                    "params": {
                        "session_id": {"type": "resolve", "resource": sessions_config.name, "field": "id"},
                        "limit": config.page_size,
                    },
                    "data_selector": config.data_key,
                    "paginator": BrowserUseMessagesPaginator(),
                },
            },
        ]
        resources = rest_api_resources(
            rest_config,
            team_id,
            job_id,
            None,
            resume_hook=save_fanout_checkpoint,
            initial_paginator_state=resume.fanout_state if resume is not None else None,
        )
        resource = next(r for r in resources if r.name == config.name)
    else:
        # Keyset (v4) and offset (v3) top-level lists checkpoint different state shapes. Both hooks
        # fire AFTER a page is yielded and persist only when a next page remains, so a crash
        # re-yields the last page (merge dedupes) rather than skipping it.
        initial_paginator_state: Optional[dict[str, Any]]
        if config.pagination == "keyset":
            initial_paginator_state = {"cursor": resume.cursor} if resume is not None and resume.cursor else None

            def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
                if state and state.get("cursor") is not None:
                    resumable_source_manager.save_state(BrowserUseResumeConfig(cursor=str(state["cursor"])))
        else:
            initial_paginator_state = {"page": resume.page} if resume is not None and resume.page else None

            def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
                if state and state.get("page") is not None:
                    resumable_source_manager.save_state(BrowserUseResumeConfig(page=int(state["page"])))

        rest_config["resources"] = [_list_endpoint_resource(config)]
        resource = rest_api_resource(
            rest_config,
            team_id,
            job_id,
            None,
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_paginator_state,
        )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        # Full-refresh endpoints with no guaranteed API ordering; the watermark is not used, but
        # the batches arrive oldest-first within each page so "asc" is the honest default.
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )


def validate_credentials(api_key: str, api_version: str) -> bool:
    # The cheapest genuine token probe: list a single session on the pinned version. 200 means the
    # key is accepted. `/sessions` exists in every version, and the size-param name is derived from
    # that version's own config (v3 page_size, v4 limit). The probe session shares the export
    # path's capture/redirect posture (see _make_session).
    sessions = endpoints_for_version(api_version)["sessions"]
    url = f"{_base_url(api_version)}{sessions.path}?{_list_size_param(sessions)}=1"
    ok, _status = validate_via_probe(
        lambda: _make_session(api_key),
        url,
        headers={API_KEY_HEADER: api_key, "Accept": "application/json"},
    )
    return ok
