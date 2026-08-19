"""Twenty transport layer.

Twenty is an open-source CRM offered both as hosted cloud (``https://api.twenty.com``) and
self-hosted (a customer-supplied host), so the API base URL is a configurable field. Auth is a
single ``Authorization: Bearer <api key>`` header; every request must be made over HTTPS.

List endpoints are cursor paginated: ``limit`` caps the page size (documented default 60, server
max 200 per ``QUERY_MAX_RECORDS``), ``starting_after`` advances to the next page, and each
response carries ``pageInfo.hasNextPage`` / ``pageInfo.endCursor``. Records for object
``<namePlural>`` arrive wrapped as ``{"data": {"<namePlural>": [...]}, "pageInfo": {...},
"totalCount": ...}`` — verified against the REST controller source
(``rest-api-find-many.handler.ts`` / ``parse-core-path.utils.ts``) rather than the vendor's own
OpenAPI description text, which documents a ``/rest/core/...`` path that the actual routing
(``/rest/<namePlural>``) does not implement.

List endpoints accept ``filter=<field>[gte]:"<ISO 8601 value>"`` and
``order_by=<field>[AscNullsFirst]``, both combinable with cursor pagination, so incremental sync
on ``updatedAt`` / ``createdAt`` is a genuine server-side filter rather than a client-side skip.
"""

import re
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlparse

from requests import Request, Response

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import _is_host_safe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import BasePaginator
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.twenty.settings import (
    PAGE_SIZE,
    REQUEST_TIMEOUT,
    TWENTY_ENDPOINTS,
)

DEFAULT_BASE_URL = "https://api.twenty.com"
DEFAULT_INCREMENTAL_FIELD = "updatedAt"
HOST_NOT_ALLOWED_ERROR = "Twenty instance URL is not allowed"
HTTP_NOT_ALLOWED_ERROR = "Twenty instance URL must use HTTPS"


class TwentyHostNotAllowedError(Exception):
    pass


@frozen
class TwentyResumeConfig:
    # `starting_after` cursor for the next page. Persisted after each page is yielded, so a crash
    # re-fetches the last page rather than skipping rows still buffered but not yet durably
    # written (merge dedupes the re-pulled rows on `id`).
    starting_after: Optional[str] = None


def normalize_base_url(base_url: Optional[str]) -> str:
    """Turn whatever the user typed into a bare Twenty base URL.

    Blank -> Twenty Cloud. Accepts bare hosts (``twenty.example.com``), a URL with or without a
    scheme, and one that already carries a trailing ``/rest``.
    """
    raw = (base_url or "").strip()
    if not raw:
        return DEFAULT_BASE_URL
    if not re.match(r"^https?://", raw, flags=re.IGNORECASE):
        raw = f"https://{raw}"
    raw = raw.rstrip("/")
    raw = re.sub(r"/rest$", "", raw, flags=re.IGNORECASE)
    return raw.rstrip("/")


def _host_of(base_url: str) -> str:
    # A backslash in the authority — literal `\` or percent-encoded `%5c` — is an SSRF vector:
    # requests/urllib3 treat a literal `\` as a path separator and do NOT percent-decode `%5c`,
    # so `urlparse` and the HTTP client can disagree on the host. `https://safe.com%5c@169.254.169.254`
    # would validate as `safe.com` while the client connects to `169.254.169.254`. No legitimate
    # Twenty URL contains a backslash, so fail closed rather than try to mirror the client's parsing.
    if "\\" in base_url or "%5c" in base_url.lower():
        return ""
    return (urlparse(base_url).hostname or "").lower()


def _is_https(base_url: str) -> bool:
    # The API key rides in the Authorization header, so refuse plaintext HTTP to keep an on-path
    # attacker from capturing it.
    return urlparse(base_url).scheme == "https"


def _ensure_host_allowed(base_url: str, host: str, team_id: int) -> None:
    if not _is_https(base_url):
        raise TwentyHostNotAllowedError(HTTP_NOT_ALLOWED_ERROR)
    host_ok, host_err = _is_host_safe(host, team_id)
    if not host_ok:
        raise TwentyHostNotAllowedError(host_err or HOST_NOT_ALLOWED_ERROR)


def _format_filter_value(value: Any) -> Optional[str]:
    """Render an incremental watermark as the bare ISO 8601 string Twenty's filter DSL expects.

    Watermarks arrive as datetimes, dates, or already-formatted strings depending on how the
    pipeline stored them. ``None`` (no watermark yet, i.e. the first sync) is passed through so
    the caller can skip adding the filter param entirely.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        moment = value if value.tzinfo else value.replace(tzinfo=UTC)
        return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _make_filter_converter(field_name: str) -> Callable[[Any], Optional[str]]:
    """Build the `convert` callable for the `filter` incremental param.

    `requests` drops a param whose value is `None` from the query string, so returning `None`
    on the first sync (no watermark yet) omits `filter` entirely rather than sending a malformed
    value.
    """

    def convert(value: Any) -> Optional[str]:
        formatted = _format_filter_value(value)
        if formatted is None:
            return None
        return f'{field_name}[gte]:"{formatted}"'

    return convert


class TwentyCursorPaginator(BasePaginator):
    """Cursor paginator for Twenty's ``pageInfo`` envelope.

    Twenty's cursor is opaque (``pageInfo.endCursor``), and a bare "cursor present" check isn't
    sufficient to detect the last page: the final page can still carry a non-null ``endCursor``
    pointing at its own last row. ``pageInfo.hasNextPage`` is the actual termination signal, so
    both are read together.
    """

    def __init__(self, limit: int = PAGE_SIZE) -> None:
        super().__init__()
        self.limit = limit
        self._next_cursor: Optional[str] = None

    def _set_params(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["limit"] = self.limit
        if self._next_cursor is not None:
            request.params["starting_after"] = self._next_cursor

    def init_request(self, request: Request) -> None:
        self._set_params(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        try:
            page_info = (response.json() or {}).get("pageInfo") or {}
        except Exception:
            page_info = {}
        end_cursor = page_info.get("endCursor")
        # A cursor identical to the one we just followed means the host isn't advancing — a broken
        # or hostile customer-controlled server could return `hasNextPage: true` with the same
        # cursor forever, looping the sync until the week-long activity timeout. Stop instead.
        if page_info.get("hasNextPage") and end_cursor and end_cursor != self._next_cursor:
            self._next_cursor = end_cursor
            self._has_next_page = True
        else:
            self._has_next_page = False

    def update_request(self, request: Request) -> None:
        self._set_params(request)

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {"starting_after": self._next_cursor} if self._has_next_page and self._next_cursor else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        cursor = state.get("starting_after")
        if cursor:
            self._next_cursor = cursor
            self._has_next_page = True

    def __str__(self) -> str:
        return f"TwentyCursorPaginator(limit={self.limit})"


def validate_credentials(
    base_url: Optional[str], api_key: str, team_id: int, schema_name: Optional[str] = None
) -> tuple[bool, str | None]:
    """Probe the companies list — the cheapest read any workspace API key can perform."""
    resolved = normalize_base_url(base_url)
    host = _host_of(resolved)
    if not host:
        return False, "Invalid Twenty instance URL"

    host_ok, host_err = _is_host_safe(host, team_id)
    if not host_ok:
        return False, host_err or HOST_NOT_ALLOWED_ERROR
    if not _is_https(resolved):
        return False, HTTP_NOT_ALLOWED_ERROR

    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{resolved}/rest/companies?limit=1",
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        allow_redirects=False,
    )
    if ok:
        return True, None
    if status is None:
        return False, "Could not reach the Twenty API. Check the instance URL and try again."
    if status == 401:
        return False, "Invalid Twenty API key. Generate a new key in Settings > API & Webhooks and reconnect."
    if status == 403:
        # A role can restrict an API key to a subset of objects; accept at source-create and only
        # reject when probing a specific schema's scope.
        if schema_name is None:
            return True, None
        return (
            False,
            "Your Twenty API key does not have permission to read this data. Check the key's role and reconnect.",
        )
    return False, f"Twenty API returned an unexpected status ({status}) while validating credentials."


def twenty_source(
    base_url: Optional[str],
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[TwentyResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: Optional[str] = None,
) -> SourceResponse:
    config = TWENTY_ENDPOINTS[endpoint]
    resolved_base_url = normalize_base_url(base_url)
    host = _host_of(resolved_base_url)
    field_name = incremental_field or DEFAULT_INCREMENTAL_FIELD

    params: dict[str, Any] = {}
    if should_use_incremental_field:
        params["filter"] = {
            "type": "incremental",
            "cursor_path": field_name,
            "convert": _make_filter_converter(field_name),
        }
        params["order_by"] = f"{field_name}[AscNullsFirst]"
    else:
        # No incremental filter, but an explicit stable sort still keeps cursor pagination
        # deterministic across a sync's page requests.
        params["order_by"] = "id[AscNullsFirst]"

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": f"{resolved_base_url}/rest",
            "headers": {"Accept": "application/json"},
            "auth": {"type": "bearer", "token": api_key},
            "paginator": TwentyCursorPaginator(),
            # Don't follow redirects: a self-hosted host could 3xx to an internal address,
            # bypassing the host validation done before the request (SSRF).
            "allow_redirects": False,
            # Bound each request so a customer-controlled host that stalls can't hold a worker
            # until the week-long resumable activity timeout.
            "request_timeout": REQUEST_TIMEOUT,
        },
        "resource_defaults": {
            "write_disposition": {"disposition": "merge", "strategy": "upsert"}
            if should_use_incremental_field
            else "replace",
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    "data_selector": f"data.{config.path.lstrip('/')}",
                },
                "table_format": "delta",
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.starting_after:
            initial_paginator_state = {"starting_after": resume.starting_after}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Only persist when there's a next page to resume to; the Redis TTL handles cleanup on
        # completion, and `state` is None/empty on the last page.
        next_cursor = (state or {}).get("starting_after")
        if next_cursor:
            resumable_source_manager.save_state(TwentyResumeConfig(starting_after=next_cursor))

    def items() -> Any:
        # Re-check at run time (not just source-create) in case the URL was edited or now
        # resolves to an internal address (SSRF / DNS rebinding).
        _ensure_host_allowed(resolved_base_url, host, team_id)
        yield from rest_api_resource(
            rest_config,
            team_id,
            job_id,
            db_incremental_field_last_value,
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_paginator_state,
        )

    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=[config.primary_key],
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="month",
        partition_keys=[config.partition_key],
    )
