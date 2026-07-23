import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional, cast
from urllib.parse import urlparse

import requests

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import _is_host_safe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    OffsetPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import AuthConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.servicenow.settings import SERVICENOW_ENDPOINTS

# ServiceNow's Table API defaults to a generous page size; we keep it modest so each
# heartbeat-bounded batch stays small and resumable. Offset pagination is simple and
# universally supported. Keyset pagination (ORDERBY sys_created_on with a moving
# floor) performs better on very large tables, but offset keeps resume state trivial
# and is adequate for the table sizes this source targets.
DEFAULT_PAGE_SIZE = 1000

SERVICENOW_API_VERSION_V1 = "v1"
SERVICENOW_API_VERSION_V2 = "v2"

# ServiceNow's Table API is reachable both versionless (`/api/now/table`) and pinned
# (`/api/now/v2/table`). `v1` keeps the versionless path it has always used so existing
# syncs stay byte-for-byte unchanged; `v2` targets the explicit v2 endpoint. With
# `sysparm_display_value=false` and `sysparm_exclude_reference_link=true` the row shapes
# are identical across versions, so only the URL segment differs.
_TABLE_API_PATHS = {
    SERVICENOW_API_VERSION_V1: "api/now/table",
    SERVICENOW_API_VERSION_V2: "api/now/v2/table",
}


def _table_api_path(table: str, api_version: str) -> str:
    # An unrecognized pin falls back to the versionless path — the most conservative choice.
    path = _TABLE_API_PATHS.get(api_version, _TABLE_API_PATHS[SERVICENOW_API_VERSION_V1])
    return f"{path}/{table}"


def _table_api_url(base_url: str, table: str, api_version: str) -> str:
    return f"{base_url}/{_table_api_path(table, api_version)}"


@dataclasses.dataclass
class ServiceNowResumeConfig:
    # Row offset of the next unfetched page — ServiceNow's Table API paginates with
    # sysparm_offset/sysparm_limit.
    offset: int = 0


@dataclasses.dataclass
class ServiceNowAuth:
    """Resolved credentials for a single sync. Exactly one auth style is populated."""

    api_key: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None

    def headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["x-sn-apikey"] = self.api_key
        return headers

    def basic_auth(self) -> Optional[tuple[str, str]]:
        if self.username and self.password:
            return (self.username, self.password)
        return None

    def to_auth_config(self) -> AuthConfig:
        """Framework auth config so the secret is redacted from logs and error messages."""
        if self.api_key:
            return {"type": "api_key", "api_key": self.api_key, "name": "x-sn-apikey", "location": "header"}
        return cast(
            AuthConfig,
            {"type": "http_basic", "username": self.username, "password": self.password},
        )

    def secret_values(self) -> tuple[str, ...]:
        return tuple(v for v in (self.api_key, self.password) if v)


def normalize_instance_url(instance: str) -> str:
    """Accept a bare subdomain, host, or full URL and return `https://<host>[:port]`.

    Forces HTTPS and strips any path, query, fragment, or userinfo so only the
    host (and optional port) survive. This keeps the value safe to feed into the
    SSRF host check and to build Table API paths against.

    Examples: ``dev12345`` -> ``https://dev12345.service-now.com``;
    ``https://acme.service-now.com/foo?x=1`` -> ``https://acme.service-now.com``.
    """
    value = (instance or "").strip().rstrip("/")
    if not value:
        raise ValueError("ServiceNow instance URL is required")

    # Bare subdomain (no scheme, no dot) expands to the standard ServiceNow domain.
    if "://" not in value and "." not in value:
        return f"https://{value}.service-now.com"

    if "://" not in value:
        value = f"https://{value}"

    parsed = urlparse(value)
    host = parsed.hostname
    if not host:
        raise ValueError("Invalid ServiceNow instance URL")

    netloc = f"{host}:{parsed.port}" if parsed.port else host
    return f"https://{netloc}"


def _resolve_base_url(instance_url: str, team_id: int) -> str:
    """Normalize the instance URL and reject internal/private hosts (SSRF guard).

    ``_is_host_safe`` is a no-op outside of PostHog Cloud, so self-hosted
    instances can still reach any host.
    """
    base_url = normalize_instance_url(instance_url)
    hostname = urlparse(base_url).hostname or ""
    is_safe, error = _is_host_safe(hostname, team_id)
    if not is_safe:
        raise ValueError(error or "ServiceNow instance host is not allowed.")
    return base_url


def _format_datetime(value: Any) -> Optional[str]:
    """Format an incremental cursor value as ServiceNow's `YYYY-MM-DD HH:MM:SS` (UTC).

    With ``sysparm_display_value=false`` ServiceNow returns and filters audit
    timestamps in UTC, so we coerce everything to UTC before formatting.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d 00:00:00")
    return str(value)


def build_sysparm_query(cursor_field: Optional[str], last_value: Optional[str], sort_field: str) -> str:
    """Build a ServiceNow encoded query.

    Filters server-side on ``<cursor_field>>=<last_value>`` when incremental, and
    always pins an explicit ascending order on ``sort_field`` so pagination is stable
    and the pipeline's cursor watermark advances correctly.
    """
    clauses: list[str] = []
    if cursor_field and last_value:
        clauses.append(f"{cursor_field}>={last_value}")
    clauses.append(f"ORDERBY{sort_field}")
    return "^".join(clauses)


def validate_credentials(
    instance_url: str,
    auth: ServiceNowAuth,
    team_id: int,
    table: Optional[str] = None,
    *,
    api_version: str,
) -> tuple[bool, str | None]:
    try:
        base_url = _resolve_base_url(instance_url, team_id)
    except ValueError as exc:
        return False, str(exc)

    # Probe a cheap single-row read. At source-create (no specific table) we probe
    # `sys_user`; otherwise probe the requested table to confirm scope for it.
    # The probe hits the same versioned Table API path the sync uses, so a v1-pinned
    # source validates against the path it actually reads from.
    probe_table = table or "sys_user"
    url = _table_api_url(base_url, probe_table, api_version)
    params: dict[str, Any] = {"sysparm_limit": 1, "sysparm_fields": "sys_id"}

    try:
        # `instance_url` is user-supplied; don't follow redirects so a safe-looking
        # host can't bounce us to an internal one (SSRF guard).
        response = make_tracked_session(redact_values=auth.secret_values()).get(
            url,
            params=params,
            headers=auth.headers(),
            auth=auth.basic_auth(),
            timeout=10,
            allow_redirects=False,
        )
    except requests.RequestException as exc:
        return False, str(exc)

    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return False, "Invalid ServiceNow credentials. Please check your instance URL and credentials."
    if response.status_code == 403:
        # Valid credentials, but no read access to this table. Accept at source-create
        # (the user may only intend to sync the tables they have access to) and only
        # surface the error when validating a specific table.
        if table is None:
            return True, None
        return False, f"Your ServiceNow account does not have read access to the '{table}' table."
    if response.status_code == 404:
        return False, f"ServiceNow table '{probe_table}' was not found on this instance."

    return False, f"ServiceNow returned an unexpected status ({response.status_code})."


def servicenow_source(
    instance_url: str,
    auth: ServiceNowAuth,
    endpoint: str,
    resumable_source_manager: ResumableSourceManager[ServiceNowResumeConfig],
    team_id: int,
    job_id: str,
    api_version: str = SERVICENOW_API_VERSION_V1,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    endpoint_config = SERVICENOW_ENDPOINTS[endpoint]
    base_url = _resolve_base_url(instance_url, team_id)

    if should_use_incremental_field:
        cursor_field = incremental_field or "sys_updated_on"
        last_value = _format_datetime(db_incremental_field_last_value)
        sort_field = cursor_field
    else:
        cursor_field = None
        last_value = None
        # Partition by creation time, so a full refresh is ordered by the same stable field.
        sort_field = "sys_created_on"

    query = build_sysparm_query(cursor_field, last_value, sort_field)

    params: dict[str, Any] = {
        "sysparm_query": query,
        "sysparm_display_value": "false",
        "sysparm_exclude_reference_link": "true",
    }

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": base_url,
            "headers": {"Accept": "application/json"},
            "auth": auth.to_auth_config(),
            # ServiceNow has no top-level total; termination is short/empty page (OffsetPaginator default).
            "paginator": OffsetPaginator(
                limit=DEFAULT_PAGE_SIZE,
                offset_param="sysparm_offset",
                limit_param="sysparm_limit",
                total_path=None,
            ),
            # `base_url` is user-supplied; refuse redirects so a safe-looking host can't bounce us to
            # an internal one (SSRF guard). A 3xx raises a non-retryable ValueError before the request
            # (and its Authorization header) leaves the process.
            "allow_redirects": False,
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": _table_api_path(endpoint_config.table, api_version),
                    "params": params,
                    # A 200 without `result` (e.g. an empty body) reads as an empty page and stops,
                    # matching the previous `.get("result", [])` behavior.
                    "data_selector": "result",
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"offset": resume.offset}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes on the primary key) rather than skipping it.
        if state and state.get("offset") is not None:
            resumable_source_manager.save_state(ServiceNowResumeConfig(offset=int(state["offset"])))

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
        primary_keys=[endpoint_config.primary_key],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="week",
        partition_keys=[endpoint_config.partition_key],
        sort_mode="asc",
    )
