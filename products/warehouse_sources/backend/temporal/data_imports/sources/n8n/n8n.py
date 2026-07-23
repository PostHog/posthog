import dataclasses
from typing import Any, Optional
from urllib.parse import urlencode, urlparse

from posthog.cloud_utils import is_cloud

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.n8n.settings import (
    N8N_API_PATH,
    N8N_ENDPOINTS,
    PAGE_SIZE,
)


@dataclasses.dataclass
class N8nResumeConfig:
    # The `nextCursor` token to fetch the next page. None means "start from the
    # first page" — used both on a fresh sync and when the bookmark predates any page.
    next_cursor: Optional[str] = None


def normalize_host(host: str) -> str:
    """Normalize the instance URL and reject anything that isn't plain http(s).

    Accepts either a bare host (`myinstance.app.n8n.cloud`) or a full URL, with or
    without the `/api/v1` suffix, and returns the instance origin (no trailing slash).
    """
    host = host.strip()
    if not host:
        raise ValueError("n8n host is required")
    if "://" not in host:
        host = f"https://{host}"
    host = host.rstrip("/")
    # Tolerate a pasted API base URL by trimming a trailing /api/v1.
    if host.endswith(N8N_API_PATH):
        host = host[: -len(N8N_API_PATH)]
    parsed = urlparse(host)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError(f"Invalid n8n host: {host}")
    # The API key rides in the X-N8N-API-KEY header on every request, so plaintext http
    # would leak it to any network observer. On PostHog Cloud the request egresses over the
    # public internet, so require https. Self-hosted operators control their own network path
    # (e.g. an internal n8n reachable only over http), so http stays allowed there — mirroring
    # how host IP safety is only enforced on cloud.
    if parsed.scheme == "http" and is_cloud():
        raise ValueError("n8n instance URL must use https")
    # SSRF guard: urlparse treats a backslash as userinfo and an "@" as a userinfo
    # separator, but urllib3/requests treat the backslash as an authority separator, so
    # `http://127.0.0.1\@example.com` validates as example.com yet connects to 127.0.0.1.
    # A legitimate instance URL has no userinfo, so reject either construct outright.
    if "\\" in host or "%5c" in host.lower() or "@" in parsed.netloc:
        raise ValueError(f"Invalid n8n host: {host}")
    return host


def hostname_of(host: str) -> str:
    return urlparse(normalize_host(host)).hostname or ""


def _base_url(host: str) -> str:
    return f"{normalize_host(host)}{N8N_API_PATH}"


def _get_headers(api_key: str) -> dict[str, str]:
    return {"X-N8N-API-KEY": api_key, "Accept": "application/json"}


def _build_url(base_url: str, params: dict[str, Any]) -> str:
    if not params:
        return base_url
    return f"{base_url}?{urlencode(params)}"


def n8n_source(
    host: str,
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[N8nResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = N8N_ENDPOINTS[endpoint]

    params: dict[str, Any] = {"limit": PAGE_SIZE, **config.extra_params}

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": _base_url(host),
            # Auth (the X-N8N-API-KEY header) is supplied via the framework auth config so its
            # value is redacted from logs and raised errors; only the non-secret Accept header here.
            "headers": {"Accept": "application/json"},
            "auth": {"type": "api_key", "api_key": api_key, "name": "X-N8N-API-KEY", "location": "header"},
            # n8n cursor pagination: `nextCursor` in the body, echoed back as the `cursor` query
            # param. A null/absent nextCursor terminates.
            "paginator": JSONResponseCursorPaginator(cursor_path="nextCursor", cursor_param="cursor"),
            # `host` is user-supplied, so pin redirects off so validation and the outbound request
            # stay on the same target (SSRF defense-in-depth).
            "allow_redirects": False,
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    "data_selector": "data",
                    # `data` is the required envelope field; a 200 body without it means the
                    # response shape changed — fail loud instead of silently syncing 0 rows.
                    "data_selector_required": True,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.next_cursor is not None:
            initial_paginator_state = {"cursor": resume.next_cursor}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes) rather than skipping it.
        if state and state.get("cursor") is not None:
            resumable_source_manager.save_state(N8nResumeConfig(next_cursor=state["cursor"]))

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
        primary_keys=list(config.primary_keys),
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )


def validate_credentials(host: str, api_key: str) -> bool:
    """Confirm the instance is reachable and the key is accepted.

    Probes /workflows with limit=1 — the most broadly-available scope on an API key.
    """
    try:
        url = _build_url(f"{_base_url(host)}/workflows", {"limit": 1})
    except ValueError:
        return False
    ok, _status = validate_via_probe(
        # `host` is user-supplied, so pin redirects off (SSRF defense-in-depth) and redact the key.
        lambda: make_tracked_session(redact_values=(api_key,), allow_redirects=False),
        url,
        headers=_get_headers(api_key),
        timeout=15,
    )
    return ok
