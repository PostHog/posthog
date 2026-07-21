"""Plunk transport layer.

Plunk (useplunk.com) is an open-source email platform offered both as a hosted SaaS
(``https://next-api.useplunk.com``) and self-hosted (a customer-supplied host), so the API base URL
must be configurable. Auth is a project-scoped secret API key (``sk_*``) sent as a Bearer token; the
public ``pk_*`` key is only valid for client-side event tracking and is rejected by every list
endpoint.

Contacts are cursor-paginated (``limit``/``cursor``; the response's ``cursor`` field is omitted on
the last page). Campaigns and templates are page-number paginated (``page``/``pageSize`` with a
``totalPages`` count in the body). Segments come back as one bare JSON array.

Every stream is full-refresh: no list endpoint accepts a server-side updated-since/created-after
filter (verified against the Plunk API source), even though rows carry ``createdAt``/``updatedAt``.
"""

import re
import dataclasses
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
    BasePaginator,
    JSONResponseCursorPaginator,
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import Endpoint
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.plunk.settings import (
    PLUNK_ENDPOINTS,
    PlunkEndpointConfig,
)

DEFAULT_BASE_URL = "https://next-api.useplunk.com"

HOST_NOT_ALLOWED_ERROR = "Plunk API URL is not allowed"
HTTP_NOT_ALLOWED_ERROR = "Plunk API URL must use HTTPS"
PUBLIC_KEY_ERROR = "This is a public API key (pk_*). Use your project's secret API key (sk_*) instead."


class PlunkHostNotAllowedError(Exception):
    pass


@dataclasses.dataclass
class PlunkResumeConfig:
    # Exactly one of these is set, matching the endpoint's pagination style. Persisted after each
    # page is yielded, so a crash before the write re-yields the last page (merge dedupes on `id`).
    cursor: str = ""
    page: int = 0


def normalize_base_url(base_url: Optional[str]) -> str:
    """Turn whatever the user typed into a ``<scheme>://<host>`` base URL.

    Blank → the hosted Plunk SaaS. Accepts bare hosts (``plunk.example.com``) and full URLs with or
    without a scheme.
    """
    raw = (base_url or "").strip()
    if not raw:
        raw = DEFAULT_BASE_URL
    if not re.match(r"^https?://", raw, flags=re.IGNORECASE):
        raw = f"https://{raw}"
    return raw.rstrip("/")


def _host_of(base_url: str) -> str:
    # `urlparse` treats a backslash (and its `%5c` encoding) as userinfo, so
    # `https://127.0.0.1\@example.com` parses as host `example.com` while requests/urllib3 (per the
    # WHATWG URL rules) treat `\` as a path separator and connect to `127.0.0.1`. Normalize to `/`
    # first so the host we validate is the host the request actually reaches (SSRF bypass guard).
    normalized = base_url.replace("\\", "/").replace("%5c", "/").replace("%5C", "/")
    return (urlparse(normalized).hostname or "").lower()


def _is_https(base_url: str) -> bool:
    # The secret key rides in the Authorization header, so refuse plaintext HTTP to keep an on-path
    # attacker from capturing it.
    return urlparse(base_url).scheme == "https"


def _paginator_for(config: PlunkEndpointConfig) -> BasePaginator:
    if config.pagination == "cursor":
        # The response's `cursor` field is omitted (or null) once `hasMore` is false, which is
        # exactly the terminator this paginator keys off.
        return JSONResponseCursorPaginator(cursor_path="cursor", cursor_param="cursor")
    if config.pagination == "page":
        return PageNumberPaginator(base_page=1, page=1, page_param="page", total_path="totalPages")
    return SinglePagePaginator()


def _error_message(response: requests.Response) -> str | None:
    # Plunk error bodies look like {"success": false, "error": {"code", "message", ...}}.
    try:
        error = (response.json() or {}).get("error") or {}
        return error.get("message")
    except Exception:
        return None


def validate_credentials(
    base_url: Optional[str], api_key: str, schema_name: Optional[str] = None, team_id: Optional[int] = None
) -> tuple[bool, str | None]:
    """Probe the cheapest list endpoint to confirm the secret key is genuine.

    Plunk keys are project-scoped with no per-resource scopes, so one probe covers every endpoint;
    a 403 (project disabled, unverified email) blocks syncing regardless of schema and fails
    source-create with the API's own message.
    """
    if api_key.startswith("pk_"):
        return False, PUBLIC_KEY_ERROR

    resolved_base_url = normalize_base_url(base_url)
    host = _host_of(resolved_base_url)

    if not host:
        return False, "Invalid Plunk API URL"

    # The host is fully customer-controlled for self-hosted deployments, so block hosts that resolve
    # to private/internal addresses (SSRF). Only enforced on cloud — see _is_host_safe.
    if team_id is not None:
        host_ok, host_err = _is_host_safe(host, team_id)
        if not host_ok:
            return False, host_err or HOST_NOT_ALLOWED_ERROR

    # Refuse plaintext HTTP before the key-bearing request goes out, so a self-hosted URL can't
    # expose the secret key on the network.
    if not _is_https(resolved_base_url):
        return False, HTTP_NOT_ALLOWED_ERROR

    url = f"{resolved_base_url}/contacts?{urlencode({'limit': 1})}"
    try:
        # `redact_values` masks the key from captured HTTP samples. Don't follow redirects: the
        # validated host could 3xx to an internal address, defeating the host check above (SSRF).
        session = make_tracked_session(redact_values=(api_key,))
        response = session.get(
            url,
            headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
            timeout=10,
            allow_redirects=False,
        )
    except requests.exceptions.RequestException as e:
        return False, str(e)

    if response.is_redirect or response.is_permanent_redirect:
        return False, HOST_NOT_ALLOWED_ERROR

    if response.status_code == 200:
        return True, None

    if response.status_code == 401:
        return False, "Invalid Plunk secret API key. Copy the sk_* key from your Plunk project settings."

    return False, _error_message(response) or f"Plunk returned an unexpected status ({response.status_code})"


def plunk_source(
    base_url: Optional[str],
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[PlunkResumeConfig],
) -> SourceResponse:
    config = PLUNK_ENDPOINTS[endpoint]
    resolved_base_url = normalize_base_url(base_url)
    host = _host_of(resolved_base_url)

    # Seed the paginator from any saved resume state; map back into the persisted dataclass on save.
    initial_paginator_state: Optional[dict[str, Any]] = None
    if config.pagination != "single" and resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            if config.pagination == "cursor" and resume.cursor:
                initial_paginator_state = {"cursor": resume.cursor}
            elif config.pagination == "page" and resume.page:
                initial_paginator_state = {"page": resume.page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; the hook fires AFTER a page is yielded so a crash
        # re-yields the last page (merge dedupes on the primary key) rather than skipping it.
        if not state:
            return
        if state.get("cursor"):
            resumable_source_manager.save_state(PlunkResumeConfig(cursor=str(state["cursor"])))
        elif state.get("page") is not None:
            resumable_source_manager.save_state(PlunkResumeConfig(page=int(state["page"])))

    endpoint_config: Endpoint = {
        "path": config.path,
        "params": dict(config.params),
        "paginator": _paginator_for(config),
    }
    if config.pagination != "single":
        # Paginated responses wrap rows under `data`; the segments endpoint returns a bare array,
        # which the framework ingests as-is when no selector is set.
        endpoint_config["data_selector"] = "data"

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": resolved_base_url,
            "headers": {"Accept": "application/json"},
            "auth": {"type": "bearer", "token": api_key},
            # Don't follow redirects: an attacker-controlled host could 3xx to an internal address,
            # bypassing the host validation done before the request (SSRF).
            "allow_redirects": False,
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": endpoint_config,
            }
        ],
    }

    def items() -> Any:
        # Re-check at run time (not just at source-create) in case the URL was edited or now
        # resolves to an internal address (SSRF / DNS rebinding). Only enforced on cloud. Refuse
        # plaintext HTTP before the key is used. Both raise before any request leaves the process.
        host_ok, host_err = _is_host_safe(host, team_id)
        if not host_ok:
            raise PlunkHostNotAllowedError(host_err or HOST_NOT_ALLOWED_ERROR)
        if not _is_https(resolved_base_url):
            raise PlunkHostNotAllowedError(HTTP_NOT_ALLOWED_ERROR)

        yield from rest_api_resource(
            rest_config,
            team_id,
            job_id,
            None,  # every Plunk endpoint is full refresh — no incremental watermark
            resume_hook=save_checkpoint if config.pagination != "single" else None,
            initial_paginator_state=initial_paginator_state,
        )

    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=[config.primary_key],
        partition_count=1 if config.partition_key else None,
        partition_size=1 if config.partition_key else None,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode=config.sort_mode,
    )
