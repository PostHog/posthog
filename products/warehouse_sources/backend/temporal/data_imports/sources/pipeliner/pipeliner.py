import re
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional

import requests
from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import _is_host_safe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import BasePaginator
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.pipeliner.settings import PIPELINER_ENDPOINTS

# Pipeliner caps list pages at 100 records (default 30); the largest page minimizes round trips.
PAGE_SIZE = 100

HOST_NOT_ALLOWED_ERROR = "Pipeliner service URL is not allowed"

# Cheap collection used to confirm the API key pair is genuine. The keys are space-wide, so one
# probe validates access to every entity collection.
DEFAULT_PROBE_ENTITY = "Clients"

# The default cursor advertised in settings.py; every Pipeliner entity carries `modified`.
DEFAULT_INCREMENTAL_FIELD = "modified"


class PipelinerHostNotAllowedError(Exception):
    pass


@dataclasses.dataclass
class PipelinerResumeConfig:
    # `page_info.end_cursor` of the last page yielded; passed back via `after` to resume from the
    # next page. Merge dedupes any re-pulled rows on the primary key.
    cursor: str | None = None
    # The formatted incremental filter value the cursor was minted under. Reapplied verbatim on
    # resume so the resumed query walks the same result set even if the stored watermark advanced
    # while earlier batches were being persisted.
    filter_value: str | None = None


class PipelinerCursorPaginator(BasePaginator):
    """Cursor pagination over Pipeliner list endpoints.

    The next cursor lives in the response body at ``page_info.end_cursor`` and is sent back as the
    ``after`` query param. Unlike a plain cursor paginator, termination is driven by the body's
    ``page_info.has_next_page`` flag (the last page still carries an ``end_cursor``), and an empty
    page stops the walk defensively even when ``has_next_page`` is set.
    """

    def __init__(self, cursor_param: str = "after") -> None:
        super().__init__()
        self.cursor_param = cursor_param
        self._cursor_value: Optional[str] = None

    def _apply_cursor(self, request: Request) -> None:
        if self._cursor_value is not None:
            if request.params is None:
                request.params = {}
            request.params[self.cursor_param] = self._cursor_value

    def init_request(self, request: Request) -> None:
        # Seed a resumed run at the saved cursor.
        self._apply_cursor(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        try:
            body = response.json()
        except Exception:
            body = None
        page_info = body.get("page_info") if isinstance(body, dict) else None
        if not isinstance(page_info, dict):
            page_info = {}
        end_cursor = page_info.get("end_cursor")
        has_next_page = bool(page_info.get("has_next_page"))

        # `has_next_page` false (or an empty / cursor-less page, defensively) ends the collection.
        if not has_next_page or not isinstance(end_cursor, str) or not end_cursor or not data:
            self._has_next_page = False
            self._cursor_value = None
        else:
            self._cursor_value = end_cursor
            self._has_next_page = True

    def update_request(self, request: Request) -> None:
        self._apply_cursor(request)

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {"cursor": self._cursor_value} if self._has_next_page and self._cursor_value is not None else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        cursor = state.get("cursor")
        if cursor is not None:
            self._cursor_value = cursor
            self._has_next_page = True

    def __str__(self) -> str:
        return f"PipelinerCursorPaginator(cursor_param={self.cursor_param})"


def normalize_service_url(service_url: str) -> str:
    """Turn whatever the user typed into a bare API host.

    Accepts values like ``us-east.api.pipelinersales.com``,
    ``https://us-east.api.pipelinersales.com/``, or a full base URL including the
    ``/api/v100/rest/spaces/...`` path, and returns just the host.
    """
    service_url = service_url.strip()
    service_url = re.sub(r"^https?://", "", service_url, flags=re.IGNORECASE)
    return service_url.split("/")[0].strip()


def _base_url(service_url: str, space_id: str) -> str:
    return f"https://{normalize_service_url(service_url)}/api/v100/rest/spaces/{space_id.strip()}"


def _make_session(username: str, password: str) -> requests.Session:
    # allow_redirects=False: the service URL is user-controlled, so never follow a redirect that
    # could point at an internal address (SSRF).
    session = make_tracked_session(
        headers={"Accept": "application/json"},
        redact_values=(username, password),
        allow_redirects=False,
    )
    session.auth = (username, password)
    return session


def _format_incremental_value(value: Any) -> str:
    """Pipeliner stores every timestamp in UTC and accepts ISO 8601 values in filters."""
    if isinstance(value, datetime):
        utc_dt = value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
        return utc_dt.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d 00:00:00")
    return str(value)


def pipeliner_source(
    service_url: str,
    space_id: str,
    username: str,
    password: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[PipelinerResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = PIPELINER_ENDPOINTS[endpoint]

    def items() -> Iterator[list[dict[str, Any]]]:
        # Re-check at run time (not just at source-create) in case the service URL was edited or now
        # resolves to an internal address (SSRF / DNS rebinding). Only enforced on cloud.
        host_ok, host_err = _is_host_safe(normalize_service_url(service_url), team_id)
        if not host_ok:
            raise PipelinerHostNotAllowedError(host_err or HOST_NOT_ALLOWED_ERROR)

        cursor_field = incremental_field or DEFAULT_INCREMENTAL_FIELD
        filter_value: str | None = None
        if should_use_incremental_field and db_incremental_field_last_value is not None:
            filter_value = _format_incremental_value(db_incremental_field_last_value)

        resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
        initial_paginator_state: Optional[dict[str, Any]] = None
        if resume is not None:
            # A watermark that advanced mid-job must not replace the filter the cursor was minted under.
            filter_value = resume.filter_value
            if resume.cursor is not None:
                initial_paginator_state = {"cursor": resume.cursor}

        # Ascending sort on a monotonic field keeps page boundaries stable, and for incremental syncs
        # matches sort_mode="asc" so the pipeline's watermark checkpoints correctly. `filter`,
        # `order-by`, and the `after` cursor are re-sent on every page, so the time window applies to
        # the whole walk, not just page one.
        order_by = cursor_field if should_use_incremental_field else config.partition_key

        params: dict[str, Any] = {"first": PAGE_SIZE, "order-by": order_by}
        if filter_value is not None:
            params[f"filter[{cursor_field}]"] = filter_value
            params[f"filter-op[{cursor_field}]"] = "gte"

        def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
            # Persist AFTER a page is yielded and only while a next page remains, so a crash
            # re-fetches from the next page (already-yielded pages are persisted); merge dedupes.
            if state and state.get("cursor") is not None:
                resumable_source_manager.save_state(
                    PipelinerResumeConfig(cursor=state["cursor"], filter_value=filter_value)
                )

        rest_config: RESTAPIConfig = {
            "client": {
                "base_url": _base_url(service_url, space_id),
                "headers": {"Accept": "application/json"},
                # Auth via the framework config so the API key pair is redacted from error messages.
                "auth": {"type": "http_basic", "username": username, "password": password},
                # The service URL is user-controlled; a followed 3xx could point at an internal
                # address (SSRF), so reject redirects rather than following them.
                "allow_redirects": False,
                "paginator": PipelinerCursorPaginator(),
            },
            "resource_defaults": {},
            "resources": [
                {
                    "name": endpoint,
                    "endpoint": {
                        "path": f"/entities/{config.entity}",
                        "params": params,
                        "data_selector": "data",
                        # A 200 whose body isn't the expected {"data": [...]} envelope is treated as a
                        # transient bad payload and retried, rather than ingested as a stray row.
                        "data_selector_malformed_retryable": True,
                    },
                }
            ],
        }

        resource = rest_api_resource(
            rest_config,
            team_id,
            job_id,
            db_incremental_field_last_value,
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_paginator_state,
        )
        yield from resource

    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=config.primary_keys,
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="month",
        partition_keys=[config.partition_key],
    )


def check_access(
    service_url: str,
    space_id: str,
    username: str,
    password: str,
    entity: str = DEFAULT_PROBE_ENTITY,
) -> tuple[int, Optional[str]]:
    """Probe a single entity collection to validate the API key pair.

    Returns ``(status, message)``: ``200`` reachable, ``401``/``403`` auth failure, ``0`` for a
    connection problem, other HTTP status otherwise.
    """
    session = _make_session(username, password)
    url = f"{_base_url(service_url, space_id)}/entities/{entity}"
    try:
        response = session.get(url, params={"first": 1}, timeout=15)
    except Exception as e:
        return 0, f"Could not connect to Pipeliner: {e}"

    if response.is_redirect or response.is_permanent_redirect:
        return 0, HOST_NOT_ALLOWED_ERROR

    if response.status_code in (401, 403):
        return response.status_code, None

    if not response.ok:
        # Error responses carry {"code", "name", "message", ...}; surface the message when present.
        try:
            message = response.json().get("message")
        except Exception:
            message = None
        return response.status_code, message or f"Pipeliner returned HTTP {response.status_code}"

    return 200, None


def validate_credentials(
    service_url: str,
    space_id: str,
    username: str,
    password: str,
    schema_name: Optional[str] = None,
    team_id: Optional[int] = None,
) -> tuple[bool, str | None]:
    host = normalize_service_url(service_url)
    if not host or not re.match(r"^[A-Za-z0-9.\-]+$", host):
        return False, "Invalid Pipeliner service URL"

    if not space_id.strip() or not re.match(r"^[A-Za-z0-9\-]+$", space_id.strip()):
        return False, "Invalid Pipeliner space ID"

    # The service URL is fully customer-controlled, so block hosts that resolve to private/
    # internal addresses (SSRF). Only enforced on cloud — see _is_host_safe.
    if team_id is not None:
        host_ok, host_err = _is_host_safe(host, team_id)
        if not host_ok:
            return False, host_err or HOST_NOT_ALLOWED_ERROR

    status, message = check_access(service_url, space_id, username, password)
    if status == 200:
        return True, None
    if status == 401:
        return False, "Invalid Pipeliner API credentials"
    if status == 403:
        if schema_name is None:
            # Valid credentials, missing permission for this probe — let source creation through.
            return True, None
        return False, "Your Pipeliner API application lacks the required permissions for this endpoint"
    return False, message or "Could not validate Pipeliner API credentials"
