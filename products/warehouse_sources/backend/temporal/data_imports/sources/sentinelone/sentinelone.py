import re
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import parse_qsl, urlencode, urlparse

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
from products.warehouse_sources.backend.temporal.data_imports.sources.sentinelone.settings import (
    SENTINELONE_ENDPOINTS,
    SentinelOneEndpointConfig,
)

API_BASE_PATH = "/web/api/v2.1"

HOST_NOT_ALLOWED_ERROR = "SentinelOne console URL is not allowed"


class SentinelOneHostNotAllowedError(Exception):
    pass


@dataclasses.dataclass
class SentinelOneResumeConfig:
    next_url: str


def normalize_console_url(console_url: str) -> str:
    """Turn whatever the user typed into a bare SentinelOne console host.

    Accepts values like ``usea1-example.sentinelone.net``,
    ``https://usea1-example.sentinelone.net/``, or a pasted API URL with the
    ``/web/api/v2.1`` path, and returns ``usea1-example.sentinelone.net``.
    """
    console_url = console_url.strip()
    console_url = re.sub(r"^https?://", "", console_url, flags=re.IGNORECASE)
    console_url = console_url.split("/")[0]
    return console_url.strip().rstrip("/")


def _base_url(console_url: str) -> str:
    return f"https://{normalize_console_url(console_url)}{API_BASE_PATH}"


def _get_headers(api_token: str) -> dict[str, str]:
    return {
        "Authorization": f"ApiToken {api_token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _format_datetime_z(dt: datetime) -> str:
    """SentinelOne accepts ISO 8601 timestamps; use millisecond precision with a ``Z`` suffix."""
    utc_dt = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    return utc_dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _format_incremental_value(value: Any) -> str:
    if isinstance(value, datetime):
        return _format_datetime_z(value)
    if isinstance(value, date):
        return _format_datetime_z(datetime.combine(value, datetime.min.time(), tzinfo=UTC))
    return str(value)


def _build_initial_params(
    config: SentinelOneEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> dict[str, Any]:
    params: dict[str, Any] = {"limit": config.page_size}

    if config.default_incremental_field is None:
        # Full-refresh-only endpoint (groups, sites): stay on the API's default order —
        # their sortBy enums aren't verifiable without a live tenant.
        return params

    # Cursor pagination needs a deterministic ascending walk for the watermark to be
    # meaningful; sort by the field we filter on (createdAt for full refreshes, since
    # it's stable while rows are inserted mid-sync).
    sort_field = (
        (incremental_field or config.default_incremental_field) if should_use_incremental_field else "createdAt"
    )
    params["sortBy"] = sort_field
    params["sortOrder"] = "asc"

    if should_use_incremental_field and db_incremental_field_last_value:
        params[f"{sort_field}__gte"] = _format_incremental_value(db_incremental_field_last_value)

    return params


def _data_selector(config: SentinelOneEndpointConfig) -> str:
    # Most list endpoints return `data` as a plain list; sites nests it under `data.sites`.
    return f"data.{config.data_key}" if config.data_key else "data"


def _next_url_from_cursor(
    console_url: str, config: SentinelOneEndpointConfig, params: dict[str, Any], cursor: str
) -> str:
    """Rebuild the saved resume URL from the trusted console host, static params, and cursor.

    The cursor is only valid for the exact query it was minted against, so every non-cursor param
    is carried over unchanged — the same URL the old hand-rolled pager persisted, kept identical so
    previously saved ``SentinelOneResumeConfig`` state stays meaningful.
    """
    query = dict(params)
    query["cursor"] = cursor
    return f"{_base_url(console_url)}{config.path}?{urlencode(query)}"


def _is_same_host(url: str, console_url: str) -> bool:
    """Whether ``url`` points at the configured console host.

    Resume URLs come from Redis state; pin them to the validated console host so a
    poisoned entry can't point the sync at an arbitrary internal address (SSRF).
    """
    try:
        return (urlparse(url).hostname or "").lower() == normalize_console_url(console_url).lower()
    except Exception:
        return False


def _normalize_row(row: dict[str, Any], config: SentinelOneEndpointConfig) -> dict[str, Any]:
    """Hoist createdAt/updatedAt to the top level where the object nests them.

    Threats keep their timestamps under ``threatInfo``; the pipeline reads the
    incremental watermark and partition key from top-level columns.
    """
    if config.hoist_datetime_fields_from:
        nested = row.get(config.hoist_datetime_fields_from)
        if isinstance(nested, dict):
            for field in ("createdAt", "updatedAt"):
                if field not in row and nested.get(field) is not None:
                    row[field] = nested[field]
    return row


def _parse_error_message(response: requests.Response) -> str:
    """SentinelOne errors arrive as ``{"errors": [{"title": ..., "detail": ...}]}``."""
    try:
        errors = response.json().get("errors") or []
        if errors and isinstance(errors[0], dict):
            title = errors[0].get("title") or ""
            detail = errors[0].get("detail") or ""
            message = ": ".join(part for part in (title, detail) if part)
            if message:
                return message
    except Exception:
        pass
    return response.text


class SentinelOneCursorPaginator(BasePaginator):
    """Cursor pagination on ``pagination.nextCursor``, resumable via the cursor value.

    Unlike the framework's ``JSONResponseCursorPaginator``, an empty page terminates the walk
    even when the body still carries a cursor — this preserves the hand-rolled source's
    ``if not rows: break`` behavior.
    """

    def __init__(
        self, cursor_param: str = "cursor", cursor_path: tuple[str, str] = ("pagination", "nextCursor")
    ) -> None:
        super().__init__()
        self.cursor_param = cursor_param
        self.cursor_path = cursor_path
        self._cursor: Optional[str] = None

    def _apply_cursor(self, request: Request) -> None:
        if self._cursor is not None:
            if request.params is None:
                request.params = {}
            request.params[self.cursor_param] = self._cursor

    def init_request(self, request: Request) -> None:
        self._apply_cursor(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        # An empty page ends the walk regardless of any cursor the body still carries.
        if not data:
            self._has_next_page = False
            return
        try:
            body = response.json()
            outer, inner = self.cursor_path
            next_cursor = (body.get(outer) or {}).get(inner)
        except Exception:
            next_cursor = None
        if next_cursor:
            self._cursor = next_cursor
            self._has_next_page = True
        else:
            self._has_next_page = False

    def update_request(self, request: Request) -> None:
        self._apply_cursor(request)

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {"cursor": self._cursor} if self._has_next_page and self._cursor is not None else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        cursor = state.get("cursor")
        if cursor is not None:
            self._cursor = cursor
            self._has_next_page = True


def validate_credentials(
    console_url: str, api_token: str, schema_name: Optional[str] = None, team_id: Optional[int] = None
) -> tuple[bool, str | None]:
    """Probe the console to confirm the API token is genuine.

    At source-create (``schema_name is None``) we hit the cheap ``/system/info`` endpoint
    and accept 403 — the token is valid but its user's role may lack that view. A scoped
    probe (``schema_name`` set) hits the endpoint itself and treats 403 as a hard failure.
    """
    normalized = normalize_console_url(console_url)
    if not normalized or not re.match(r"^[A-Za-z0-9.\-]+$", normalized):
        return False, "Invalid SentinelOne console URL"

    # The console host is fully customer-controlled, so block hosts that resolve to
    # private/internal addresses (SSRF). Only enforced on cloud — see _is_host_safe.
    if team_id is not None:
        host_ok, host_err = _is_host_safe(normalized, team_id)
        if not host_ok:
            return False, host_err or HOST_NOT_ALLOWED_ERROR

    endpoint_config = SENTINELONE_ENDPOINTS.get(schema_name) if schema_name else None
    if endpoint_config is not None:
        url = f"{_base_url(normalized)}{endpoint_config.path}"
        params: dict[str, Any] = {"limit": 1}
    else:
        url = f"{_base_url(normalized)}/system/info"
        params = {}

    try:
        # Don't follow redirects: the validated host could 3xx to an internal address,
        # defeating the host check above (SSRF).
        response = make_tracked_session(redact_values=(api_token,), capture=False, allow_redirects=False).get(
            url, headers=_get_headers(api_token), params=params, timeout=10, allow_redirects=False
        )
    except requests.exceptions.RequestException as e:
        return False, str(e)

    if response.is_redirect or response.is_permanent_redirect:
        return False, HOST_NOT_ALLOWED_ERROR

    if response.status_code == 200:
        return True, None

    if response.status_code == 401:
        return False, "Invalid SentinelOne API token"

    if response.status_code == 403:
        if schema_name is None:
            # Valid token, missing role/scope for this probe — let source creation through.
            return True, None
        return False, "Your SentinelOne API token's user lacks the required permissions for this endpoint"

    return False, _parse_error_message(response)


def sentinelone_source(
    console_url: str,
    api_token: str,
    endpoint: str,
    resumable_source_manager: ResumableSourceManager[SentinelOneResumeConfig],
    team_id: int,
    job_id: str,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = SENTINELONE_ENDPOINTS[endpoint]

    def _items() -> Iterator[Any]:
        # Re-check at run time (not just at source-create) in case the console URL was edited
        # or now resolves to an internal address (SSRF / DNS rebinding). Only enforced on cloud.
        host_ok, host_err = _is_host_safe(normalize_console_url(console_url), team_id)
        if not host_ok:
            raise SentinelOneHostNotAllowedError(host_err or HOST_NOT_ALLOWED_ERROR)

        params = _build_initial_params(
            config, should_use_incremental_field, db_incremental_field_last_value, incremental_field
        )

        rest_config: RESTAPIConfig = {
            "client": {
                "base_url": _base_url(console_url),
                # Auth (the `ApiToken` header) is supplied via the framework auth config so its
                # value is redacted from logs/errors; only the non-secret headers are set here.
                "headers": {"Accept": "application/json", "Content-Type": "application/json"},
                "auth": {
                    "type": "api_key",
                    "api_key": f"ApiToken {api_token}",
                    "name": "Authorization",
                    "location": "header",
                },
                # An unexpected 3xx (potentially to an internal address) is rejected, not followed (SSRF).
                "allow_redirects": False,
                "paginator": SentinelOneCursorPaginator(),
            },
            "resource_defaults": {},
            "resources": [
                {
                    "name": endpoint,
                    "endpoint": {
                        "path": config.path,
                        "params": params,
                        "data_selector": _data_selector(config),
                    },
                }
            ],
        }

        initial_paginator_state: Optional[dict[str, Any]] = None
        if resumable_source_manager.can_resume():
            resume = resumable_source_manager.load_state()
            # A poisoned resume URL on a foreign host is ignored (fall back to a fresh start),
            # never followed; only the cursor is reused, rebuilt onto the trusted console host.
            if resume is not None and _is_same_host(resume.next_url, console_url):
                cursor = dict(parse_qsl(urlparse(resume.next_url).query)).get("cursor")
                if cursor:
                    initial_paginator_state = {"cursor": cursor}

        def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
            # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
            # the last page (merge dedupes) rather than skipping it.
            if state and state.get("cursor"):
                next_url = _next_url_from_cursor(console_url, config, params, state["cursor"])
                resumable_source_manager.save_state(SentinelOneResumeConfig(next_url=next_url))

        resource = rest_api_resource(
            rest_config,
            team_id,
            job_id,
            db_incremental_field_last_value,
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_paginator_state,
        )

        if config.hoist_datetime_fields_from:
            resource.add_map(lambda row: _normalize_row(row, config))

        yield from resource

    return SourceResponse(
        name=endpoint,
        items=_items,
        primary_keys=[config.primary_key],
        # Incremental-capable endpoints request sortBy=<cursor field>&sortOrder=asc, so
        # ascending order is explicit rather than assumed from the API default.
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
