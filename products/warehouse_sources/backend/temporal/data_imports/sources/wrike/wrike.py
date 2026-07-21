import dataclasses
from typing import Any, Optional
from urllib.parse import urlencode, urlsplit

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.wrike.settings import WRIKE_ENDPOINTS

# Wrike serves each account from a region-specific host (www.wrike.com, app-us2.wrike.com,
# app-eu.wrike.com, ...). The user supplies their host; we only ever send the token to a
# *.wrike.com host to avoid being retargeted at an attacker-controlled or internal address.
WRIKE_HOST_SUFFIX = "wrike.com"
API_PATH = "/api/v4"
# Wrike caps paginated list pages at 1000 items.
PAGE_SIZE = 1000
# Paginated endpoints carry a `nextPageToken` in the body; the same token is sent back as a query param.
NEXT_PAGE_TOKEN = "nextPageToken"


@dataclasses.dataclass
class WrikeResumeConfig:
    next_page_token: str


def _normalize_host(host: str) -> str:
    """Extract the bare hostname the credential would actually be sent to.

    The user-supplied value is parsed as a URL and reduced to its hostname, so a value
    carrying a path, query, port, or credentials (e.g. `evil.com?.wrike.com` or
    `internal.service/x.wrike.com`) can't smuggle a non-Wrike netloc past `is_host_valid`'s
    suffix check — `requests` would otherwise connect to `evil.com`/`internal.service`.
    Both validation and URL construction go through this, so the validated host and the
    connection target are always the same value."""
    candidate = host.strip().lower()
    if "://" not in candidate:
        candidate = f"//{candidate}"
    return urlsplit(candidate).hostname or ""


def is_host_valid(host: str) -> bool:
    """Only allow Wrike-owned hosts as the credential target (anti-SSRF)."""
    if not host:
        return False
    hostname = _normalize_host(host)
    return hostname == WRIKE_HOST_SUFFIX or hostname.endswith(f".{WRIKE_HOST_SUFFIX}")


def _base_url(host: str) -> str:
    return f"https://{_normalize_host(host)}{API_PATH}"


def _build_url(host: str, path: str, params: dict[str, Any]) -> str:
    clean_params = {key: value for key, value in params.items() if value is not None}
    base = f"{_base_url(host)}{path}"
    if not clean_params:
        return base
    return f"{base}?{urlencode(clean_params)}"


def validate_credentials(access_token: str, host: str) -> tuple[bool, str | None]:
    """Confirm the access token is genuine. `/contacts?me=true` is a cheap authenticated probe
    that returns the current user."""
    if not is_host_valid(host):
        return False, "Host must be a Wrike domain (e.g. www.wrike.com or app-us2.wrike.com)"

    url = _build_url(host, "/contacts", {"me": "true"})
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(access_token,)),
        url,
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
    )
    if ok:
        return True, None
    if status == 401:
        return False, "Invalid Wrike access token"
    if status == 403:
        return False, "Wrike access token is missing the required permissions"

    return False, f"Wrike API error: status={status}"


def wrike_source(
    access_token: str,
    host: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[WrikeResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = WRIKE_ENDPOINTS[endpoint]

    if not is_host_valid(host):
        raise ValueError(f"Refusing to send Wrike credentials to non-Wrike host: {host}")

    params: dict[str, Any] = {"pageSize": PAGE_SIZE} if config.paginated else {}
    paginator = (
        JSONResponseCursorPaginator(cursor_path=NEXT_PAGE_TOKEN, cursor_param=NEXT_PAGE_TOKEN)
        if config.paginated
        else SinglePagePaginator()
    )

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": _base_url(host),
            "headers": {"Accept": "application/json"},
            "auth": {"type": "bearer", "token": access_token},
            # Pin every request (base and paginated) to the validated Wrike host so a tampered
            # response can't retarget the credential off-host.
            "allowed_hosts": [],
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    "data_selector": "data",
                    "paginator": paginator,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if config.paginated and resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"cursor": resume.next_page_token}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Save AFTER a page is yielded, only while a next-page token remains, so a crash re-yields
        # the last page (merge dedupes) rather than skipping it.
        if state and state.get("cursor"):
            resumable_source_manager.save_state(WrikeResumeConfig(next_page_token=str(state["cursor"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=[config.primary_key],
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )
