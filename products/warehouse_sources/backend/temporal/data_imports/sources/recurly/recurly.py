import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import BasePaginator
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.recurly.settings import (
    RECURLY_BASE_URLS,
    RECURLY_ENDPOINTS,
)

# Pinning the API version is required — Recurly rejects requests without it.
RECURLY_API_VERSION = "v2021-02-25"
# Recurly caps list endpoints at 200 records per page.
PAGE_LIMIT = 200
DEFAULT_SORT_FIELD = "updated_at"
# `sort` and `begin_time` only accept these timestamp columns.
VALID_SORT_FIELDS = ("created_at", "updated_at")


@dataclasses.dataclass
class RecurlyResumeConfig:
    next_cursor: str


def _headers() -> dict[str, str]:
    return {"Accept": f"application/vnd.recurly.{RECURLY_API_VERSION}"}


def _base_url(region: str) -> str:
    return RECURLY_BASE_URLS.get(region, RECURLY_BASE_URLS["us"])


def _format_datetime(value: Any) -> Optional[str]:
    """Format an incremental cursor value as an ISO8601 timestamp for `begin_time`.

    Recurly treats a partial timestamp without a timezone as UTC, so we always
    emit an explicit UTC value.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        utc_value = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return utc_value.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    if isinstance(value, date):
        # Promote a bare date to midnight UTC so begin_time is always a full datetime.
        return datetime(value.year, value.month, value.day, tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    return str(value)


def _extract_cursor(next_path: Optional[str]) -> Optional[str]:
    """Pull the `cursor` query param out of the `next` path Recurly returns."""
    if not next_path:
        return None
    cursors = parse_qs(urlparse(next_path).query).get("cursor")
    return cursors[0] if cursors else None


class RecurlyPaginator(BasePaginator):
    """Cursor pagination for Recurly's list endpoints.

    Recurly returns ``{"has_more": bool, "next": "<path>?cursor=...", "data": [...]}``.
    The ``next`` value is a relative path, so rather than chasing the URL we extract
    its ``cursor`` and re-apply it as a query param on the same request — this keeps
    the original ``sort``/``order``/``begin_time`` params intact and makes the cursor
    trivially resumable.
    """

    def __init__(self) -> None:
        super().__init__()
        self._next_cursor: Optional[str] = None

    def init_request(self, request: Request) -> None:
        # Honour a seeded resume cursor on the first request.
        if self._next_cursor is not None:
            if request.params is None:
                request.params = {}
            request.params["cursor"] = self._next_cursor

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        self._next_cursor = None
        try:
            body = response.json()
        except ValueError:
            body = None

        if not isinstance(body, dict) or not body.get("has_more"):
            self._has_next_page = False
            return

        cursor = _extract_cursor(body.get("next"))
        if cursor:
            self._next_cursor = cursor
            self._has_next_page = True
        else:
            self._has_next_page = False

    def update_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        if self._next_cursor is not None:
            request.params["cursor"] = self._next_cursor

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        if self._next_cursor is not None and self._has_next_page:
            return {"next_cursor": self._next_cursor}
        return None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        next_cursor = state.get("next_cursor")
        if next_cursor is not None:
            self._next_cursor = str(next_cursor)
            self._has_next_page = True


def get_resource(
    endpoint: str,
    should_use_incremental_field: bool,
    incremental_field: Optional[str],
    db_incremental_field_last_value: Optional[Any],
) -> EndpointResource:
    config = RECURLY_ENDPOINTS[endpoint]
    incremental = should_use_incremental_field and config.supports_incremental

    if incremental:
        # Sort by the cursor the user chose so `begin_time` and the watermark agree.
        # Ascending order is mandatory: Recurly warns that descending `updated_at`
        # lets concurrently-updated rows slip behind the cursor and never return.
        sort_field = incremental_field if incremental_field in VALID_SORT_FIELDS else DEFAULT_SORT_FIELD
    else:
        # Full refresh: a stable ascending `created_at` sort avoids page-boundary
        # skips/duplicates if rows are inserted mid-sync.
        sort_field = "created_at"

    params: dict[str, Any] = {
        "limit": PAGE_LIMIT,
        "sort": sort_field,
        "order": "asc",
    }
    if incremental and db_incremental_field_last_value is not None:
        params["begin_time"] = _format_datetime(db_incremental_field_last_value)

    return {
        "name": endpoint,
        "table_name": endpoint,
        "write_disposition": {"disposition": "merge", "strategy": "upsert"} if incremental else "replace",
        "endpoint": {
            "data_selector": "data",
            "path": config.path,
            "params": params,
        },
        "table_format": "delta",
    }


def recurly_source(
    api_key: str,
    region: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[RecurlyResumeConfig],
    db_incremental_field_last_value: Optional[Any],
    should_use_incremental_field: bool = False,
    incremental_field: Optional[str] = None,
) -> Resource:
    incremental = should_use_incremental_field and RECURLY_ENDPOINTS[endpoint].supports_incremental

    config: RESTAPIConfig = {
        "client": {
            "base_url": _base_url(region),
            "headers": _headers(),
            "auth": {
                "type": "http_basic",
                "username": api_key,
                "password": "",
            },
            "paginator": RecurlyPaginator(),
        },
        "resource_defaults": {
            "write_disposition": {"disposition": "merge", "strategy": "upsert"} if incremental else "replace",
        },
        "resources": [
            get_resource(endpoint, should_use_incremental_field, incremental_field, db_incremental_field_last_value)
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = {"next_cursor": resume_config.next_cursor}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when there's a next page; the Redis TTL handles cleanup on completion.
        if state and state.get("next_cursor"):
            resumable_source_manager.save_state(RecurlyResumeConfig(next_cursor=str(state["next_cursor"])))

    return rest_api_resource(
        config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


def validate_credentials(api_key: str, region: str) -> tuple[bool, Optional[str]]:
    try:
        res = make_tracked_session().get(
            f"{_base_url(region)}/accounts",
            params={"limit": 1},
            headers=_headers(),
            auth=(api_key, ""),
            timeout=30,
        )
    except Exception as e:
        return False, f"Could not reach Recurly ({e}). Please check your network and region, then try again."

    if res.status_code == 200:
        return True, None
    if res.status_code == 401:
        return (
            False,
            "Recurly rejected the API key (401 Unauthorized). Create a private API key under "
            "Integrations > API Credentials in Recurly and confirm the selected region matches your site.",
        )
    if res.status_code == 403:
        return (
            False,
            "The Recurly API key is valid but lacks permission to read this site (403 Forbidden). "
            "Check the key's permissions and try again.",
        )
    return False, f"Recurly returned an unexpected status ({res.status_code}) while validating credentials."
