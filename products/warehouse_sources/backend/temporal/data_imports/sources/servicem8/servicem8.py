"""ServiceM8 API client: header-cursor pagination, `$filter` incremental sync, and rest_source wiring."""

from datetime import date, datetime
from typing import Any, Optional

from requests import Request, Response

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import BasePaginator
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.servicem8.settings import ENDPOINT_PATHS

BASE_URL = "https://api.servicem8.com/api_1.0"
# The cursor value ServiceM8 requires on the very first request of every list endpoint.
INITIAL_CURSOR = "-1"
# Response header carrying the cursor for the next page; absent on the last page.
NEXT_CURSOR_HEADER = "x-next-cursor"


@frozen
class ServiceM8ResumeConfig:
    cursor: str


def _format_filter_datetime(value: Any) -> str:
    """Render an incremental cursor value as the quoted datetime `$filter` expects.

    ServiceM8's filtering docs don't state a timezone convention for `edit_date`; this
    follows the vendor's own example filters (`$filter=create_date gt '2023-01-01'`) and
    passes the value through as a naive local-looking timestamp.
    """
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d 00:00:00")
    return str(value)


def _build_filter_param(should_use_incremental_field: bool, db_incremental_field_last_value: Any) -> Optional[str]:
    if not should_use_incremental_field or db_incremental_field_last_value is None:
        return None
    # Only `eq`/`ne`/`gt`/`lt` are supported (no `ge`/`le`). `gt` can re-fetch a record whose
    # edit_date exactly equals the watermark, but the merge upserts on `uuid` so that's a
    # harmless duplicate rather than a data-quality issue.
    return f"edit_date gt '{_format_filter_datetime(db_incremental_field_last_value)}'"


def get_resource(
    name: str,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> EndpointResource:
    object_name = ENDPOINT_PATHS[name]
    return {
        "name": name,
        "table_name": object_name,
        "write_disposition": {
            "disposition": "merge",
            "strategy": "upsert",
        }
        if should_use_incremental_field
        else "replace",
        "endpoint": {
            "path": f"/{object_name}.json",
            "params": {
                "$filter": _build_filter_param(should_use_incremental_field, db_incremental_field_last_value),
            },
        },
        "table_format": "delta",
    }


class ServiceM8Paginator(BasePaginator):
    """Cursor pagination via the `x-next-cursor` response header.

    ServiceM8 requires `cursor=-1` on the first request; every subsequent request passes the
    UUID from the previous response's `x-next-cursor` header. That header is absent on the
    last page. See https://developer.servicem8.com/docs/pagination.
    """

    def __init__(self) -> None:
        super().__init__()
        self._cursor: str = INITIAL_CURSOR

    def init_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["cursor"] = self._cursor

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        next_cursor = response.headers.get(NEXT_CURSOR_HEADER)
        if next_cursor:
            self._cursor = next_cursor
            self._has_next_page = True
        else:
            self._has_next_page = False

    def update_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["cursor"] = self._cursor

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        if self._has_next_page:
            return {"cursor": self._cursor}
        return None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        cursor = state.get("cursor")
        if cursor is not None:
            self._cursor = str(cursor)
            self._has_next_page = True


def servicem8_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[ServiceM8ResumeConfig],
    db_incremental_field_last_value: Optional[Any],
    should_use_incremental_field: bool = False,
) -> Resource:
    config: RESTAPIConfig = {
        "client": {
            "base_url": BASE_URL,
            "auth": {
                "type": "api_key",
                "name": "X-Api-Key",
                "api_key": api_key,
                "location": "header",
            },
            "paginator": ServiceM8Paginator(),
            # X-Api-Key isn't the standard Authorization header, which `requests` strips on a
            # cross-origin redirect, so a spoofed cursor/redirect target could otherwise harvest
            # the ServiceM8 key. `allowed_hosts=[]` pins every request (including pagination) to
            # base_url's host, and `allow_redirects=False` refuses any 3xx outright.
            "allowed_hosts": [],
            "allow_redirects": False,
            # `capture=False`: rows carry client/job PII (contact details, addresses, work notes)
            # the name-based sample scrubbers aren't built to catch, so keep them out of HTTP
            # diagnostic sample storage entirely, same as the other PII/free-text sources.
            "capture": False,
        },
        "resource_defaults": {
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
        },
        "resources": [get_resource(endpoint, should_use_incremental_field, db_incremental_field_last_value)],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = {"cursor": resume_config.cursor}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Only persist when there's a next page to resume to; the Redis TTL handles cleanup
        # on completion.
        if state and state.get("cursor"):
            resumable_source_manager.save_state(ServiceM8ResumeConfig(cursor=str(state["cursor"])))

    return rest_api_resource(
        config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


def validate_credentials(api_key: str) -> bool:
    # allow_redirects=False: X-Api-Key isn't the standard Authorization header, so `requests`
    # would forward it across a cross-origin redirect; capture=False: /staff.json returns the
    # same PII-carrying shape as the real sync, so keep it out of HTTP sample storage too.
    response = make_tracked_session(redact_values=(api_key,), allow_redirects=False, capture=False).get(
        f"{BASE_URL}/staff.json",
        headers={"X-Api-Key": api_key},
        params={"cursor": INITIAL_CURSOR},
    )
    return response.status_code == 200
