import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import HttpBasicAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import BasePaginator
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.xendit.settings import (
    DEFAULT_INCREMENTAL_FIELD,
    PAGE_SIZE,
    XENDIT_BASE_URL,
    XENDIT_ENDPOINTS,
    XenditEndpointConfig,
)


@dataclasses.dataclass
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


class XenditCursorPaginator(BasePaginator):
    """Cursor pagination for Xendit list endpoints.

    Responses are shaped `{"data": [...], "has_more": bool, "links": [...]}`. The next page is
    requested by passing the last row's `id` as `after_id`; the `links` HATEOAS entry carries the
    same cursor but as a path-relative URL, so building it from the last row keeps every request
    anchored to our own base URL.
    """

    def __init__(self) -> None:
        super().__init__()
        self._after_id: Optional[str] = None

    def _apply_cursor(self, request: Request) -> None:
        if self._after_id is None:
            return
        if request.params is None:
            request.params = {}
        request.params["after_id"] = self._after_id

    def init_request(self, request: Request) -> None:
        # Honour a seeded resume cursor on the first request.
        self._apply_cursor(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        try:
            body = response.json()
        except Exception:
            body = {}

        rows = data if data is not None else (body.get("data") if isinstance(body, dict) else None) or []
        last_row = rows[-1] if rows else None
        next_after_id = last_row.get("id") if isinstance(last_row, dict) else None

        # A cursor identical to the one just used means the page didn't advance; stop instead of
        # refetching it until the activity times out.
        if not (isinstance(body, dict) and body.get("has_more")) or next_after_id is None:
            self._has_next_page = False
            return
        if str(next_after_id) == self._after_id:
            self._has_next_page = False
            return

        self._after_id = str(next_after_id)
        self._has_next_page = True

    def update_request(self, request: Request) -> None:
        self._apply_cursor(request)

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {"after_id": self._after_id} if self._has_next_page and self._after_id is not None else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        after_id = state.get("after_id")
        if after_id is not None:
            self._after_id = str(after_id)
            self._has_next_page = True

    def __str__(self) -> str:
        return "XenditCursorPaginator()"


def _build_params(
    config: XenditEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: Optional[str],
) -> dict[str, Any]:
    params: dict[str, Any] = {"limit": PAGE_SIZE, **config.extra_params}

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
                    "paginator": XenditCursorPaginator(),
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
