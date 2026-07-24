import re
import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlparse

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import _is_host_safe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.omni.settings import (
    DEFAULT_PAGE_SIZE,
    PARTITION_KEYS,
    PRIMARY_KEYS,
    SCIM_ENDPOINTS,
)

# Loopback hosts where plaintext HTTP carries no network-exposure risk (local dev). Every other
# host is forced to HTTPS since credentials must never traverse a network in cleartext.
LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}

HOST_NOT_ALLOWED_ERROR = "Omni host is not allowed"


@dataclasses.dataclass
class OmniResumeConfig:
    # Documents/Folders/Schedules resume via an opaque `nextCursor`; the SCIM Users/UserGroups
    # endpoints resume via a numeric `startIndex`. Only one is ever populated for a given endpoint.
    cursor: Optional[str] = None
    start_index: Optional[int] = None


def normalize_host(host: str) -> str:
    """Turn whatever the user typed into a bare instance base URL (scheme + host, no path).

    Accepts ``https://acme.omniapp.co``, ``acme.omniapp.co``, and ``https://acme.omniapp.co/api``,
    returning ``https://acme.omniapp.co``. Defaults to https when no scheme is given, and forces a
    plaintext ``http://`` host to ``https://`` except for loopback hosts (local dev).
    """
    host = host.strip()
    if not re.match(r"^https?://", host, flags=re.IGNORECASE):
        host = f"https://{host}"
    parsed = urlparse(host)
    scheme = parsed.scheme.lower()
    if scheme == "http" and (parsed.hostname or "").lower() not in LOOPBACK_HOSTS:
        scheme = "https"
    return f"{scheme}://{parsed.netloc}"


def _hostname(host: str) -> str:
    return (urlparse(normalize_host(host)).hostname or "").lower()


def _base_api_url(host: str) -> str:
    return f"{normalize_host(host)}/api"


def _format_watermark(value: Any) -> Optional[str]:
    """Format an incremental cursor value as an Omni-shaped UTC timestamp (millisecond precision,
    e.g. ``2026-06-01T14:30:00.000Z``) so lexicographic comparison against Omni's ``updatedAt``
    strings is chronological."""
    if isinstance(value, date) and not isinstance(value, datetime):
        value = datetime.combine(value, datetime.min.time())
    if isinstance(value, datetime):
        dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    if isinstance(value, str) and value:
        return value
    return None


class OmniPageInfoPaginator(BasePaginator):
    """Paginator for Omni's shared ``{pageInfo, records}`` list shape (documents, folders,
    schedules): a ``pageSize``/``cursor`` query param pair, with the response's
    ``pageInfo.hasNextPage`` / ``pageInfo.nextCursor`` driving the next page."""

    def __init__(self, page_size: int = DEFAULT_PAGE_SIZE) -> None:
        super().__init__()
        self._page_size = page_size
        self._cursor: Optional[str] = None

    def init_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["pageSize"] = self._page_size
        if self._cursor is not None:
            request.params["cursor"] = self._cursor

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        try:
            page_info = response.json().get("pageInfo") or {}
        except Exception:
            page_info = {}
        next_cursor = page_info.get("nextCursor")
        self._has_next_page = bool(page_info.get("hasNextPage")) and bool(next_cursor)
        self._cursor = next_cursor if self._has_next_page else None

    def update_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["pageSize"] = self._page_size
        if self._cursor is not None:
            request.params["cursor"] = self._cursor

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {"cursor": self._cursor} if self._has_next_page and self._cursor else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        cursor = state.get("cursor")
        if cursor:
            self._cursor = str(cursor)
            self._has_next_page = True


class OmniDocumentsPaginator(OmniPageInfoPaginator):
    """Documents has no server-side ``updatedAt``-since filter, so incremental sync sorts newest
    first (``sortDirection=desc``) and stops paginating once an entire page predates the stored
    watermark — an incremental run only fetches pages of changed/new documents instead of walking
    the whole catalog on every sync. Full syncs (``stop_when_older_than=None``) walk every page."""

    def __init__(self, page_size: int = DEFAULT_PAGE_SIZE, stop_when_older_than: Optional[str] = None) -> None:
        super().__init__(page_size)
        self._stop_when_older_than = stop_when_older_than

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        if self._has_next_page and self._stop_when_older_than is not None and data:
            # `updatedAt` is nullable. A page with no comparable (non-null) values can't be
            # judged against the watermark, so it's skipped rather than risk an early stop that
            # loses not-yet-synced rows.
            updated_ats: list[str] = []
            for row in data:
                if not isinstance(row, dict):
                    continue
                updated_at = row.get("updatedAt")
                if isinstance(updated_at, str) and updated_at:
                    updated_ats.append(updated_at)
            if updated_ats and max(updated_ats) < self._stop_when_older_than:
                self._has_next_page = False


class OmniScimPaginator(BasePaginator):
    """Paginator for the SCIM ``{Resources, itemsPerPage, totalResults, startIndex}`` shape used by
    the Users and UserGroups endpoints. ``startIndex`` is 1-based."""

    def __init__(self, count: int = DEFAULT_PAGE_SIZE) -> None:
        super().__init__()
        self._count = count
        self._start_index = 1

    def init_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["count"] = self._count
        request.params["startIndex"] = self._start_index

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        try:
            body = response.json()
        except Exception:
            body = {}
        items_per_page = body.get("itemsPerPage") or 0
        total_results = body.get("totalResults")
        if not items_per_page:
            self._has_next_page = False
            return
        self._start_index += items_per_page
        self._has_next_page = total_results is None or self._start_index <= total_results

    def update_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["count"] = self._count
        request.params["startIndex"] = self._start_index

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {"start_index": self._start_index} if self._has_next_page else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        start_index = state.get("start_index")
        if start_index:
            self._start_index = int(start_index)
            self._has_next_page = True


def get_resource(
    name: str,
    should_use_incremental_field: bool,
    stop_when_older_than: Optional[str],
) -> EndpointResource:
    # Declared once so each branch's dict literal is checked against `Endpoint` (a re-annotation
    # per branch trips mypy's no-redef).
    endpoint: Endpoint
    if name == "Documents":
        write_disposition = (
            {"disposition": "merge", "strategy": "upsert"} if should_use_incremental_field else "replace"
        )
        endpoint = {
            "path": "/v1/documents",
            "params": {"sortField": "updatedAt", "sortDirection": "desc"},
            "paginator": OmniDocumentsPaginator(
                stop_when_older_than=stop_when_older_than if should_use_incremental_field else None
            ),
            "data_selector": "records",
        }
        return {
            "name": name,
            "table_name": "documents",
            "write_disposition": write_disposition,
            "endpoint": endpoint,
            "table_format": "delta",
        }

    if name == "Folders":
        endpoint = {
            "path": "/v1/folders",
            "params": {"sortField": "name", "sortDirection": "asc"},
            "paginator": OmniPageInfoPaginator(),
            "data_selector": "records",
        }
        return {
            "name": name,
            "table_name": "folders",
            "write_disposition": "replace",
            "endpoint": endpoint,
            "table_format": "delta",
        }

    if name == "Connections":
        endpoint = {
            "path": "/v1/connections",
            "paginator": SinglePagePaginator(),
            "data_selector": "connections",
        }
        return {
            "name": name,
            "table_name": "connections",
            "write_disposition": "replace",
            "endpoint": endpoint,
            "table_format": "delta",
        }

    if name == "Schedules":
        endpoint = {
            "path": "/v1/schedules",
            "params": {"sortField": "scheduleName", "sortDirection": "asc"},
            "paginator": OmniPageInfoPaginator(),
            "data_selector": "records",
        }
        return {
            "name": name,
            "table_name": "schedules",
            "write_disposition": "replace",
            "endpoint": endpoint,
            "table_format": "delta",
        }

    if name == "Users":
        endpoint = {
            "path": "/scim/v2/users",
            "paginator": OmniScimPaginator(),
            "data_selector": "Resources",
        }
        return {
            "name": name,
            "table_name": "users",
            "write_disposition": "replace",
            "endpoint": endpoint,
            "table_format": "delta",
        }

    if name == "UserGroups":
        endpoint = {
            "path": "/scim/v2/groups",
            "paginator": OmniScimPaginator(),
            "data_selector": "Resources",
        }
        return {
            "name": name,
            "table_name": "user_groups",
            "write_disposition": "replace",
            "endpoint": endpoint,
            "table_format": "delta",
        }

    raise ValueError(f"Unknown Omni endpoint: {name}")


def validate_credentials(
    host: str, api_key: str, team_id: int, schema_name: Optional[str] = None
) -> tuple[bool, str | None]:
    """Confirm the credentials are genuine with a cheap ``/v1/whoami`` probe.

    The host is customer-controlled, so we block internal/private addresses (SSRF, cloud only)
    and refuse to follow redirects.
    """
    try:
        base_api_url = _base_api_url(host)
    except Exception:
        return False, "Invalid Omni instance URL"

    hostname = _hostname(host)
    if not hostname or not re.match(r"^[A-Za-z0-9.\-]+$", hostname):
        return False, "Invalid Omni instance URL"

    host_ok, host_err = _is_host_safe(hostname, team_id)
    if not host_ok:
        return False, host_err or HOST_NOT_ALLOWED_ERROR

    is_ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,), allow_redirects=False),
        f"{base_api_url}/v1/whoami",
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        allow_redirects=False,
    )

    if is_ok:
        return True, None
    if status == 401:
        return False, "Invalid Omni API key"
    if status == 403:
        # Valid credentials, missing permission for this probe — let source creation through.
        if schema_name is None:
            return True, None
        return False, "Your Omni API key does not have access to this data"
    if status is None:
        return False, "Could not reach your Omni instance. Check the Instance URL and try again."
    return (
        False,
        f"Omni returned an unexpected response (HTTP {status}). Check that the Instance URL points to your Omni instance.",
    )


def get_key_scope(host: str, api_key: str) -> Optional[str]:
    """Return the caller's API key scope (``"organization"`` or ``"user"``) via ``/v1/whoami``, or
    ``None`` if it can't be determined (used to warn that SCIM endpoints need an Organization key,
    since Personal Access Tokens are documented as unsupported for them)."""
    try:
        base_api_url = _base_api_url(host)
        response = make_tracked_session(redact_values=(api_key,), allow_redirects=False).get(
            f"{base_api_url}/v1/whoami",
            headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
            timeout=10,
            allow_redirects=False,
        )
        if response.status_code != 200:
            return None
        key_scope = response.json().get("keyScope")
        return key_scope if isinstance(key_scope, str) else None
    except Exception:
        return None


def get_endpoint_permissions(host: str, api_key: str, endpoints: list[str]) -> dict[str, str | None]:
    result: dict[str, str | None] = dict.fromkeys(endpoints)
    scim_requested = [name for name in endpoints if name in SCIM_ENDPOINTS]
    if not scim_requested:
        return result

    key_scope = get_key_scope(host, api_key)
    if key_scope == "user":
        reason = "Requires an Organization API key — Personal Access Tokens can't access SCIM user/group endpoints."
        for name in scim_requested:
            result[name] = reason
    return result


def omni_source(
    host: str,
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[OmniResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    # Re-validate the host at sync time, not just at credential-save time: the stored hostname
    # could have been DNS-rebound to a private/internal address since it was validated, so a
    # scheduled import must re-check before sending the bearer-authenticated request (SSRF).
    hostname = _hostname(host)
    host_ok, host_err = _is_host_safe(hostname, team_id)
    if not host_ok:
        raise ValueError(host_err or HOST_NOT_ALLOWED_ERROR)

    stop_when_older_than = _format_watermark(db_incremental_field_last_value) if should_use_incremental_field else None
    resource_config = get_resource(endpoint, should_use_incremental_field, stop_when_older_than)

    config: RESTAPIConfig = {
        "client": {
            "base_url": _base_api_url(host),
            "auth": {"type": "bearer", "token": api_key},
            "headers": {"Accept": "application/json"},
            # SSRF defense in depth: pin every request to the validated host and never follow a
            # 3xx, so a redirect can't bounce the bearer token to a private/metadata address.
            "allowed_hosts": [hostname],
            "allow_redirects": False,
        },
        "resources": [resource_config],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            if resume_config.cursor:
                initial_paginator_state = {"cursor": resume_config.cursor}
            elif resume_config.start_index:
                initial_paginator_state = {"start_index": resume_config.start_index}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Only Documents/Folders/Schedules/Users/UserGroups paginate; Connections uses
        # SinglePagePaginator and never reports a resume state, so this is a no-op for it.
        if not state:
            return
        cursor = state.get("cursor")
        start_index = state.get("start_index")
        if cursor:
            resumable_source_manager.save_state(OmniResumeConfig(cursor=str(cursor)))
        elif start_index:
            resumable_source_manager.save_state(OmniResumeConfig(start_index=int(start_index)))

    resource = rest_api_resource(
        config,
        team_id,
        job_id,
        # Incremental filtering is applied via the custom paginator's `stop_when_older_than`
        # above, not the framework's declarative `incremental` param — no endpoint here declares
        # one, so the framework has nothing to inject this into.
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    partition_key = PARTITION_KEYS.get(endpoint)

    return SourceResponse(
        name=resource.name,
        items=lambda: resource,
        primary_keys=PRIMARY_KEYS[endpoint],
        sort_mode="desc" if endpoint == "Documents" else "asc",
        partition_mode="datetime" if partition_key else None,
        partition_format="week" if partition_key else None,
        partition_keys=[partition_key] if partition_key else None,
    )
