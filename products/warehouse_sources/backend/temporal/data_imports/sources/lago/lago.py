"""Lago transport layer.

Lago is an open-source usage-based billing platform offered both as Lago Cloud
(``https://api.getlago.com``) and self-hosted (a customer-supplied host), so the API base URL
must be configurable. Auth is a single Bearer API key. List endpoints are page-number paginated
(``page`` / ``per_page``) and wrap their records under a resource key alongside a ``meta`` object
that carries ``total_pages`` / ``next_page``.

Every stream is full-refresh. Lago's REST API exposes no universal server-side ``created_at`` /
``updated_at`` cursor across resources — only a handful of endpoints offer ad-hoc date filters
(e.g. ``issuing_date_from`` on invoices) that filter on a business date rather than a monotonic
record-creation timestamp, so they are unsafe to treat as an incremental cursor. Incremental sync
can be layered on later for a specific endpoint once its server-side filter is verified against the
live API.

Pagination, retries, auth-header redaction, and the redirect / off-host SSRF guards are provided by
the shared ``rest_source`` framework (page-number paginator, ``allowed_hosts`` host-pinning,
``allow_redirects=False``). The DNS-based internal-IP check for customer-supplied self-hosted hosts
has no framework equivalent, so it stays here as a run-time pre-check.
"""

import re
import dataclasses
from collections.abc import Iterator
from typing import Any, Optional
from urllib.parse import urlencode, urlparse

import requests

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import _is_host_safe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.lago.settings import (
    LAGO_ENDPOINTS,
    LagoEndpointConfig,
)

DEFAULT_API_HOST = "https://api.getlago.com"
API_VERSION_PATH = "/api/v1"

HOST_NOT_ALLOWED_ERROR = "Lago API URL is not allowed"


class LagoHostNotAllowedError(Exception):
    pass


@dataclasses.dataclass
class LagoResumeConfig:
    # The next page to fetch on resume. Persisted after each page is yielded, so a crash before
    # this write leaves the previous value in place and the last page is re-yielded (Lago merges
    # dedupe on `lago_id`).
    next_page: int


def normalize_base_url(api_url: Optional[str]) -> str:
    """Turn whatever the user typed into a ``<scheme>://<host>/api/v1`` base URL.

    Blank → Lago Cloud. Accepts bare hosts (``billing.example.com``), full URLs with or without a
    scheme, and values that already include the ``/api/v1`` suffix.
    """
    raw = (api_url or "").strip()
    if not raw:
        raw = DEFAULT_API_HOST
    if not re.match(r"^https?://", raw, flags=re.IGNORECASE):
        raw = f"https://{raw}"
    raw = raw.rstrip("/")
    # Drop a trailing version segment the user may have pasted in, then re-add the version we target.
    raw = re.sub(r"/api/v\d+$", "", raw)
    return f"{raw}{API_VERSION_PATH}"


def _host_of(base_url: str) -> str:
    return (urlparse(base_url).hostname or "").lower()


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def validate_credentials(
    api_url: Optional[str], api_key: str, schema_name: Optional[str] = None, team_id: Optional[int] = None
) -> tuple[bool, str | None]:
    """Probe a cheap list endpoint to confirm the Bearer token is genuine.

    At source-create (``schema_name is None``) a 403 is accepted: the token is valid but may lack
    permission for this particular probe. A scoped probe (``schema_name`` set) treats 403 as a hard
    failure.

    Kept hand-rolled rather than routed through ``validate_via_probe`` because the probe must run
    with ``allow_redirects=False`` and reject any 3xx — the validated host could 3xx to an internal
    address, defeating the internal-IP check below (SSRF). ``validate_via_probe`` follows redirects.
    """
    base_url = normalize_base_url(api_url)
    host = _host_of(base_url)

    if not host:
        return False, "Invalid Lago API URL"

    # The host is fully customer-controlled for self-hosted deployments, so block hosts that resolve
    # to private/internal addresses (SSRF). Only enforced on cloud — see _is_host_safe.
    if team_id is not None:
        host_ok, host_err = _is_host_safe(host, team_id)
        if not host_ok:
            return False, host_err or HOST_NOT_ALLOWED_ERROR

    url = f"{base_url}/customers?{urlencode({'per_page': 1, 'page': 1})}"
    try:
        # Don't follow redirects: the validated host could 3xx to an internal address, defeating
        # the host check above (SSRF).
        response = make_tracked_session().get(url, headers=_get_headers(api_key), timeout=10, allow_redirects=False)
    except requests.exceptions.RequestException as e:
        return False, str(e)

    if response.is_redirect or response.is_permanent_redirect:
        return False, HOST_NOT_ALLOWED_ERROR

    if response.status_code == 200:
        return True, None

    if response.status_code == 401:
        return False, "Invalid Lago API key"

    if response.status_code == 403:
        if schema_name is None:
            # Valid token, missing permission for this probe — let source creation through.
            return True, None
        return False, "Lago API key lacks the required permissions for this endpoint"

    try:
        body = response.json()
        return False, body.get("error", response.text)
    except Exception:
        return False, response.text


def lago_source(
    api_url: Optional[str],
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[LagoResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config: LagoEndpointConfig = LAGO_ENDPOINTS[endpoint]
    base_url = normalize_base_url(api_url)
    host = _host_of(base_url)

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": base_url,
            # Auth (Bearer) is supplied via the framework auth config so its value is redacted from
            # logs and raised errors; only the non-secret accept/content headers are set here.
            "headers": {"Accept": "application/json", "Content-Type": "application/json"},
            "auth": {"type": "bearer", "token": api_key},
            # Pin every request to the base host and refuse redirects: a self-hosted host is
            # customer-controlled, so a tampered pagination link or a 3xx to an internal address must
            # not carry the Authorization header off-host (SSRF). `allowed_hosts=[]` means
            # "same host as base_url only".
            "allowed_hosts": [],
            "allow_redirects": False,
            # Page-number pagination; `meta.total_pages` stops after the last page so no extra empty
            # page is fetched. `stop_after_empty_page` (default) covers a 0-row / missing-key body.
            "paginator": PageNumberPaginator(base_page=1, total_path="meta.total_pages"),
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": {"per_page": config.page_size},
                    "data_selector": config.data_key,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"page": resume.next_page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes on `lago_id`) rather than skipping it.
        if state and state.get("page") is not None:
            resumable_source_manager.save_state(LagoResumeConfig(next_page=int(state["page"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    def items() -> Iterator[list[dict[str, Any]]]:
        # Re-check at run time (not just at source-create) in case the URL was edited or now resolves
        # to an internal address (SSRF / DNS rebinding). Only enforced on cloud.
        host_ok, host_err = _is_host_safe(host, team_id)
        if not host_ok:
            raise LagoHostNotAllowedError(host_err or HOST_NOT_ALLOWED_ERROR)
        yield from resource

    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=[config.primary_key],
        # Full-refresh replace: Lago exposes no `sort` param and no incremental cursor, so there is
        # no watermark to checkpoint. The default ascending mode is harmless here.
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
