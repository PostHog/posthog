"""Invoice Ninja transport layer.

Invoice Ninja is an open-source invoicing / billing platform offered both as the hosted SaaS
(``https://invoicing.co``) and self-hosted (a customer-supplied host), so the API base URL must be
configurable. Auth is a single ``X-API-TOKEN`` header; every request must also carry
``X-Requested-With: XMLHttpRequest`` (the API rejects requests without it) and be made over HTTPS.

List endpoints are page-number paginated (``page`` / ``per_page``) and wrap their records under a
top-level ``data`` key alongside a ``meta.pagination`` object that reports ``current_page`` and
``total_pages`` (and a ``links.next`` URL that is null on the last page).

Every stream is full-refresh. Invoice Ninja documents ``created_at`` / ``updated_at`` filters on its
index endpoints, but the timestamps are integer unix seconds and the ordering the API applies under
those filters could not be verified against the live API without a token — an unverified sort order
risks a corrupted incremental watermark on a mid-sync shutdown. Incremental sync can be layered on
per endpoint once its server-side filter and sort behaviour are verified with real credentials.
"""

import re
import dataclasses
from typing import Any, Optional
from urllib.parse import urlencode, urlparse

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
from products.warehouse_sources.backend.temporal.data_imports.sources.invoiceninja.settings import (
    INVOICENINJA_ENDPOINTS,
)

DEFAULT_API_HOST = "https://invoicing.co"
API_VERSION_PATH = "/api/v1"

HOST_NOT_ALLOWED_ERROR = "Invoice Ninja API URL is not allowed"
HTTP_NOT_ALLOWED_ERROR = "Invoice Ninja API URL must use HTTPS"


class InvoiceNinjaHostNotAllowedError(Exception):
    pass


@dataclasses.dataclass
class InvoiceNinjaResumeConfig:
    # The next page to fetch on resume. Persisted after each page is yielded, so a crash before this
    # write leaves the previous value in place and the last page is re-yielded (merge dedupes on `id`).
    next_page: int


class InvoiceNinjaPaginator(BasePaginator):
    """Page-number paginator matching Invoice Ninja's Laravel/Fractal envelope.

    A page has more after it when ``meta.pagination`` reports ``current_page < total_pages`` OR
    carries a non-null ``links.next`` (some deployments expose only one of the two signals). An empty
    ``data`` list, or a response with no pagination block at all, terminates — the latter guards
    against an unbounded loop on a malformed index response.
    """

    def __init__(self, page: int = 1, page_param: str = "page") -> None:
        super().__init__()
        self.page = page
        self.page_param = page_param

    def _set_page(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params[self.page_param] = self.page

    def init_request(self, request: Request) -> None:
        self._set_page(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        if not data:
            self._has_next_page = False
            return

        try:
            body = response.json()
        except Exception:
            body = {}
        pagination = (body.get("meta") or {}).get("pagination") or {}
        current_page = pagination.get("current_page")
        total_pages = pagination.get("total_pages")
        has_next_link = bool((pagination.get("links") or {}).get("next"))
        more_by_count = bool(current_page and total_pages and int(current_page) < int(total_pages))

        if not (more_by_count or has_next_link):
            self._has_next_page = False
            return

        # Prefer the server's reported page number; fall back to incrementing our own when the API
        # exposes only the `links.next` signal without a current-page count.
        self.page = (int(current_page) + 1) if current_page else self.page + 1
        self._has_next_page = True

    def update_request(self, request: Request) -> None:
        self._set_page(request)

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {"page": self.page} if self._has_next_page else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        page = state.get("page")
        if page is not None:
            self.page = int(page)
            self._has_next_page = True


def normalize_base_url(base_url: Optional[str]) -> str:
    """Turn whatever the user typed into a ``<scheme>://<host>/api/v1`` base URL.

    Blank → the hosted Invoice Ninja SaaS. Accepts bare hosts (``invoices.example.com``), full URLs
    with or without a scheme, and values that already include the ``/api/v1`` suffix.
    """
    raw = (base_url or "").strip()
    if not raw:
        raw = DEFAULT_API_HOST
    if not re.match(r"^https?://", raw, flags=re.IGNORECASE):
        raw = f"https://{raw}"
    raw = raw.rstrip("/")
    # Drop a trailing version segment the user may have pasted in, then re-add the version we target.
    raw = re.sub(r"/api/v\d+$", "", raw)
    return f"{raw}{API_VERSION_PATH}"


def _host_of(base_url: str) -> str:
    # `urlparse` treats a backslash (and its `%5c` encoding) as userinfo, so
    # `https://127.0.0.1\@example.com` parses as host `example.com` while requests/urllib3 (per the
    # WHATWG URL rules) treat `\` as a path separator and connect to `127.0.0.1`. Normalize to `/`
    # first so the host we validate is the host the request actually reaches (SSRF bypass guard).
    normalized = base_url.replace("\\", "/").replace("%5c", "/").replace("%5C", "/")
    return (urlparse(normalized).hostname or "").lower()


def _is_https(base_url: str) -> bool:
    # The API token rides in the X-API-TOKEN header, so refuse plaintext HTTP to keep an on-path
    # attacker from capturing it. Invoice Ninja mandates HTTPS anyway (HTTP requests fail).
    return urlparse(base_url).scheme == "https"


def _get_headers(api_token: str) -> dict[str, str]:
    return {
        "X-API-TOKEN": api_token,
        # Invoice Ninja rejects API requests that omit this header.
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json",
    }


def _request_headers() -> dict[str, str]:
    # Auth (the X-API-TOKEN key) is supplied via the framework auth config so its value is redacted
    # from logs and raised errors; only the non-secret required headers are set here.
    return {
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json",
    }


def _is_invalid_token(response: requests.Response) -> bool:
    """A 403 from Invoice Ninja means a bad token — its body reads ``{"message": "Invalid token"}``.

    Enterprise plans can also restrict a token to a subset of entities, which surfaces as a 403 without
    that message; those are treated as a missing permission rather than a bad token.
    """
    try:
        message = (response.json() or {}).get("message", "")
    except Exception:
        message = response.text or ""
    return "invalid token" in message.lower()


def validate_credentials(
    base_url: Optional[str], api_token: str, schema_name: Optional[str] = None, team_id: Optional[int] = None
) -> tuple[bool, str | None]:
    """Probe a cheap list endpoint to confirm the API token is genuine.

    A bad Invoice Ninja token returns 403 ``{"message": "Invalid token"}``, so — unlike sources whose
    403 means "valid token, missing scope" — a 403 carrying that message is always a hard failure. A
    403 *without* it (an entity-restricted enterprise token) is accepted at source-create and only
    rejected for a scoped probe.
    """
    resolved_base_url = normalize_base_url(base_url)
    host = _host_of(resolved_base_url)

    if not host:
        return False, "Invalid Invoice Ninja API URL"

    # The host is fully customer-controlled for self-hosted deployments, so block hosts that resolve to
    # private/internal addresses (SSRF). Only enforced on cloud — see _is_host_safe.
    if team_id is not None:
        host_ok, host_err = _is_host_safe(host, team_id)
        if not host_ok:
            return False, host_err or HOST_NOT_ALLOWED_ERROR

    # Refuse plaintext HTTP before the token-bearing request goes out, so a self-hosted URL can't
    # expose the API token on the network.
    if not _is_https(resolved_base_url):
        return False, HTTP_NOT_ALLOWED_ERROR

    url = f"{resolved_base_url}/clients?{urlencode({'per_page': 1, 'page': 1})}"
    try:
        # `redact_values` masks the token from captured HTTP samples: it rides in the `X-API-TOKEN`
        # header, which the transport's name-based denylist doesn't recognise. Don't follow redirects:
        # the validated host could 3xx to an internal address, defeating the host check above (SSRF).
        session = make_tracked_session(redact_values=(api_token,))
        response = session.get(url, headers=_get_headers(api_token), timeout=10, allow_redirects=False)
    except requests.exceptions.RequestException as e:
        return False, str(e)

    if response.is_redirect or response.is_permanent_redirect:
        return False, HOST_NOT_ALLOWED_ERROR

    if response.status_code == 200:
        return True, None

    if response.status_code == 401:
        return False, "Invalid Invoice Ninja API token"

    if response.status_code == 403:
        if _is_invalid_token(response):
            return False, "Invalid Invoice Ninja API token"
        if schema_name is None:
            # Valid token, restricted to a subset of entities — let source creation through.
            return True, None
        return False, "Your Invoice Ninja API token lacks permission for this endpoint"

    try:
        body = response.json()
        return False, body.get("message", response.text)
    except Exception:
        return False, response.text


def invoiceninja_source(
    base_url: Optional[str],
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[InvoiceNinjaResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = INVOICENINJA_ENDPOINTS[endpoint]
    resolved_base_url = normalize_base_url(base_url)
    host = _host_of(resolved_base_url)

    # Seed the paginator from any saved resume state; map back into the persisted dataclass on save.
    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"page": resume.next_page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields the
        # last page (merge dedupes on the primary key) rather than skipping it.
        if state and state.get("page") is not None:
            resumable_source_manager.save_state(InvoiceNinjaResumeConfig(next_page=int(state["page"])))

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": resolved_base_url,
            "headers": _request_headers(),
            "auth": {"type": "api_key", "api_key": api_token, "name": "X-API-TOKEN", "location": "header"},
            # Don't follow redirects: an attacker-controlled host could 3xx to an internal address,
            # bypassing the host validation done before the request (SSRF).
            "allow_redirects": False,
            "paginator": InvoiceNinjaPaginator(),
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": {"per_page": config.page_size},
                    "data_selector": "data",
                },
            }
        ],
    }

    def items() -> Any:
        # Re-check at run time (not just at source-create) in case the URL was edited or now resolves
        # to an internal address (SSRF / DNS rebinding). Only enforced on cloud. Refuse plaintext HTTP
        # before the token is used, so the token is never sent in the clear. Both raise before any
        # request leaves the process.
        host_ok, host_err = _is_host_safe(host, team_id)
        if not host_ok:
            raise InvoiceNinjaHostNotAllowedError(host_err or HOST_NOT_ALLOWED_ERROR)
        if not _is_https(resolved_base_url):
            raise InvoiceNinjaHostNotAllowedError(HTTP_NOT_ALLOWED_ERROR)

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
        # Full-refresh replace: no incremental cursor is enabled, so there is no watermark to
        # checkpoint. Invoice Ninja returns `created_at` / `updated_at` as integer unix seconds rather
        # than datetimes, so datetime partitioning isn't applied — see the module docstring.
        sort_mode="asc",
    )
