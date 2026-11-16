import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional

from requests import Request, Response

from products.warehouse_sources.sources.sdk import (
    BasePaginator,
    HttpBasicAuth,
    RESTAPIConfig,
    ResumableSourceManager,
    SourceResponse,
    make_tracked_session,
    rest_api_resource,
    validate_via_probe,
)
from products.warehouse_sources.sources.xendit.settings import (
    DEFAULT_INCREMENTAL_FIELD,
    XENDIT_BASE_URL,
    XENDIT_ENDPOINTS,
    XenditEndpointConfig,
)


@dataclasses.dataclass(frozen=False)
class XenditResumeConfig:
    after_id: str


def _format_datetime(value: Any) -> str:
    """Format an incremental cursor value as the ISO 8601 UTC string Xendit's range filters expect."""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime.combine(value, datetime.min.time())
    else:
        return str(value)

    utc_dt = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    return utc_dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _body_value(body: Any, path: tuple[str, ...]) -> Any:
    value = body
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


class XenditCursorPaginator(BasePaginator):
    """Cursor pagination for Xendit list endpoints.

    Transactions and accounts respond `{"data": [...], "has_more": bool, "links": [...]}` and take
    the last row's `id` as `after_id`; the `links` HATEOAS entry carries the same cursor but as a
    path-relative URL, so building it from the last row keeps every request anchored to our own
    base URL. Disputes and bill payment products return the next cursor in the body instead.
    """

    def __init__(
        self,
        cursor_param: str = "after_id",
        next_cursor_path: tuple[str, ...] = (),
        has_more_path: tuple[str, ...] | None = ("has_more",),
    ) -> None:
        super().__init__()
        self._cursor_param = cursor_param
        self._next_cursor_path = next_cursor_path
        self._has_more_path = has_more_path
        self._cursor: Optional[str] = None

    def _apply_cursor(self, request: Request) -> None:
        if self._cursor is None:
            return
        if request.params is None:
            request.params = {}
        request.params[self._cursor_param] = self._cursor

    def init_request(self, request: Request) -> None:
        # Honour a seeded resume cursor on the first request.
        self._apply_cursor(request)

    def _next_cursor(self, body: Any, data: Optional[list[Any]]) -> Any:
        if self._next_cursor_path:
            return _body_value(body, self._next_cursor_path)
        rows = data if data is not None else (body.get("data") if isinstance(body, dict) else None) or []
        last_row = rows[-1] if rows else None
        return last_row.get("id") if isinstance(last_row, dict) else None

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        try:
            body = response.json()
        except Exception:
            body = {}

        next_cursor = self._next_cursor(body, data)
        has_more = bool(_body_value(body, self._has_more_path)) if self._has_more_path is not None else True

        # A cursor identical to the one just used means the page didn't advance; stop instead of
        # refetching it until the activity times out.
        if not has_more or not next_cursor or str(next_cursor) == self._cursor:
            self._has_next_page = False
            return

        self._cursor = str(next_cursor)
        self._has_next_page = True

    def update_request(self, request: Request) -> None:
        self._apply_cursor(request)

    # The state key stays `after_id` for every endpoint so resume state saved by earlier runs still loads.
    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {"after_id": self._cursor} if self._has_next_page and self._cursor is not None else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        after_id = state.get("after_id")
        if after_id is not None:
            self._cursor = str(after_id)
            self._has_next_page = True

    def __str__(self) -> str:
        return f"XenditCursorPaginator(cursor_param={self._cursor_param!r})"


def _build_params(
    config: XenditEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: Optional[str],
) -> dict[str, Any]:
    params: dict[str, Any] = {"limit": config.page_size, **config.extra_params}

    if not (should_use_incremental_field and db_incremental_field_last_value is not None):
        return params

    # Only the timestamps Xendit filters on server-side may become a query param; anything else
    # would be silently ignored by the API and turn the sync into a disguised full refresh.
    cursor_field = (
        incremental_field
        if incremental_field in config.filterable_timestamps
        else (DEFAULT_INCREMENTAL_FIELD if DEFAULT_INCREMENTAL_FIELD in config.filterable_timestamps else None)
    )
    if cursor_field is not None:
        params[f"{cursor_field}[gte]"] = _format_datetime(db_incremental_field_last_value)

    return params


def _headers(for_user_id: Optional[str]) -> dict[str, str]:
    # xenPlatform only: scopes the request to one sub-account.
    return {"for-user-id": for_user_id} if for_user_id else {}


def validate_credentials(api_key: str, path: str, for_user_id: Optional[str] = None) -> tuple[bool, int | None]:
    """Probe one list endpoint and report `(reachable, status_code)`.

    403 means the key is genuine but lacks that endpoint's permission, so the caller decides
    whether to accept it (source creation) or reject it (per-schema check).
    """
    return validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{XENDIT_BASE_URL}{path}?limit=1",
        headers=_headers(for_user_id) or None,
        auth=HttpBasicAuth(username=api_key, password=""),
    )


def xendit_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[XenditResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: Optional[str] = None,
    for_user_id: Optional[str] = None,
) -> SourceResponse:
    config = XENDIT_ENDPOINTS[endpoint]
    params = _build_params(config, should_use_incremental_field, db_incremental_field_last_value, incremental_field)

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": XENDIT_BASE_URL,
            "headers": _headers(for_user_id),
            # The secret API key is the Basic auth username, which HttpBasicAuth does not treat as a
            # secret value, so redact it on the session too.
            "session": make_tracked_session(redact_values=(api_key,)),
            "auth": {"type": "http_basic", "username": api_key, "password": ""},
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    "data_selector": "data",
                    "paginator": XenditCursorPaginator(
                        cursor_param=config.cursor_param,
                        next_cursor_path=config.next_cursor_path,
                        has_more_path=config.has_more_path,
                    ),
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.after_id:
            initial_paginator_state = {"after_id": resume.after_id}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains, and only after the page was yielded, so a crash
        # re-yields the last page (merge dedupes on id) rather than skipping it.
        if state and state.get("after_id"):
            resumable_source_manager.save_state(XenditResumeConfig(after_id=str(state["after_id"])))

    # Incremental filtering is expressed as static server-side params above, so the framework's own
    # incremental injection is unused here.
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
        primary_keys=["id"],
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # Xendit documents these endpoints as "ordered by the created date" without stating a
        # direction, and offers no sort parameter. Declaring "desc" makes the pipeline commit the
        # incremental watermark once a run finishes instead of checkpointing mid-run, which is
        # correct whichever direction the rows actually arrive in.
        sort_mode="desc",
    )
