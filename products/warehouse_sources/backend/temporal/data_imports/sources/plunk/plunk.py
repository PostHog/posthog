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
import threading
import dataclasses
from typing import Any, Optional
from urllib.parse import urlencode, urlparse

import requests

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_adapter
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

# The base URL can be a customer-controlled self-hosted host, so the sync path can't trust it to
# behave. `RESTClient` calls `session.send()` without a timeout and buffers the whole body via
# `.json()`, so a host that hangs, trickles bytes, or ships a huge (or gzip-bombed) 200 could pin an
# import worker or exhaust its memory. `_BoundedPlunkSession` pins a connect/read timeout and reads
# every body incrementally under a decoded-byte cap and a wall-clock deadline before handing it back.
DEFAULT_TIMEOUT_SECONDS: tuple[float, float] = (10.0, 60.0)  # (connect, read)
MAX_RESPONSE_BYTES = 256 * 1024 * 1024
_READ_CHUNK_BYTES = 1024 * 1024
# The per-read socket timeout only bounds the gap between bytes, so a host trickling one byte just
# under it could keep a worker busy indefinitely. This absolute wall-clock deadline caps how long a
# single body read may take end to end, even while a read is blocked mid-chunk.
MAX_RESPONSE_SECONDS = 600.0

# The credential probe runs inline in the source-create API request (a Django worker), not a sync
# worker, so it gets much tighter bounds: its only job is to read a status code and a small JSON
# error body, so a controlled host must not be able to hold or fatten the worker even briefly.
VALIDATION_TIMEOUT_SECONDS: tuple[float, float] = (10.0, 10.0)  # (connect, read)
VALIDATION_MAX_RESPONSE_BYTES = 5 * 1024 * 1024
VALIDATION_MAX_RESPONSE_SECONDS = 30.0


class PlunkHostNotAllowedError(Exception):
    pass


class PlunkResponseTooLargeError(Exception):
    pass


class PlunkResponseTimeoutError(Exception):
    pass


def _read_bounded(
    response: requests.Response, max_bytes: int = MAX_RESPONSE_BYTES, max_seconds: float = MAX_RESPONSE_SECONDS
) -> bytes:
    """Read a streamed response body under both a decoded-byte cap and a total-transfer deadline.

    The read runs on a worker thread bounded by ``join(timeout=max_seconds)``, so the deadline is
    enforced as absolute wall-clock time even while a read is blocked: ``iter_content`` fills a whole
    chunk before it yields, so a host that trickles bytes just under the per-read socket timeout
    could otherwise never let an in-loop deadline check run. ``iter_content`` decodes content
    encoding as it streams, so the cap counts decoded bytes and a gzip bomb can't slip past it. On
    timeout we close the response to unblock the pending socket read and let the daemon thread unwind.
    """
    box: dict[str, Any] = {}

    def _reader() -> None:
        try:
            total = 0
            chunks: list[bytes] = []
            for chunk in response.iter_content(chunk_size=_READ_CHUNK_BYTES):
                total += len(chunk)
                if total > max_bytes:
                    box["error"] = PlunkResponseTooLargeError(
                        f"Plunk API response exceeded the size limit ({max_bytes} bytes)"
                    )
                    return
                chunks.append(chunk)
            box["data"] = b"".join(chunks)
        except Exception as exc:  # surfaced on the calling thread below
            box["error"] = exc

    thread = threading.Thread(target=_reader, name="plunk-read-bounded", daemon=True)
    thread.start()
    thread.join(timeout=max_seconds)
    if thread.is_alive():
        # Close the socket so the blocked read raises and the daemon thread can exit.
        response.close()
        raise PlunkResponseTimeoutError(f"Plunk API response exceeded the download time limit ({max_seconds:g}s)")
    if "error" in box:
        raise box["error"]
    return box.get("data", b"")


class _BoundedPlunkSession(requests.Session):
    """Tracked, no-redirect session that streams every response under a size + time bound.

    `RESTClient` invokes `send()` without a timeout and later reads the full body via `.json()`, so
    on its own it offers no defense against a customer-controlled host that hangs or returns an
    unbounded body. This pins a default connect/read timeout, streams the body through
    `_read_bounded` under a decoded-byte cap and a wall-clock deadline, then re-buffers it so the
    rest of the REST client (`.json()`, `.content`) sees an ordinary buffered response. The probe in
    `validate_credentials` reuses it with tighter caps.
    """

    def __init__(self, *, max_bytes: int = MAX_RESPONSE_BYTES, max_seconds: float = MAX_RESPONSE_SECONDS) -> None:
        super().__init__()
        self._max_bytes = max_bytes
        self._max_seconds = max_seconds

    def send(self, request: requests.PreparedRequest, **kwargs: Any) -> requests.Response:
        # Never follow redirects: a validated host could 3xx to an internal address (SSRF). Pin the
        # timeout only when the caller didn't set one, and stream so the body is read incrementally.
        kwargs["allow_redirects"] = False
        kwargs.setdefault("timeout", DEFAULT_TIMEOUT_SECONDS)
        kwargs["stream"] = True
        response = super().send(request, **kwargs)
        if response.is_redirect or response.is_permanent_redirect:
            # The caller rejects the 3xx itself; don't touch the (unconsumed) body.
            return response
        response._content = _read_bounded(response, self._max_bytes, self._max_seconds)
        response._content_consumed = True  # type: ignore[attr-defined]
        return response


def _make_bounded_session(
    api_key: str, *, max_bytes: int = MAX_RESPONSE_BYTES, max_seconds: float = MAX_RESPONSE_SECONDS
) -> requests.Session:
    session = _BoundedPlunkSession(max_bytes=max_bytes, max_seconds=max_seconds)
    adapter = make_tracked_adapter(redact_values=(api_key,))
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


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
    # A real Plunk base URL is just `<scheme>://<host>[:port]`. `urlparse` and requests/urllib3
    # disagree on how to split an authority that carries userinfo, a backslash, or percent-encoding,
    # and the disagreement is an SSRF bypass: for `https://safe.example%5c@127.0.0.1`, `urlparse`
    # reads host `safe.example` (validated) while requests connects to `127.0.0.1` (it keeps
    # `safe.example%5c` as userinfo — it does not decode `%5c`); a raw `\` flips the split the other
    # way. Rather than reconcile two parsers, reject any authority that isn't an unambiguous bare
    # host — none of these forms appear in a legitimate Plunk URL.
    netloc = urlparse(base_url).netloc
    if "@" in netloc or "\\" in netloc or "%" in netloc:
        return ""
    return (urlparse(base_url).hostname or "").lower()


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
        # A bounded session (like the sync path, but with tight validation caps) streams the probe
        # body under a decoded-byte cap and an absolute deadline, so a controlled host can't hold or
        # fatten this inline API worker. `redact_values` masks the key from captured samples; the
        # session refuses redirects so the validated host can't 3xx to an internal address (SSRF).
        session = _make_bounded_session(
            api_key, max_bytes=VALIDATION_MAX_RESPONSE_BYTES, max_seconds=VALIDATION_MAX_RESPONSE_SECONDS
        )
        response = session.get(
            url,
            headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
            timeout=VALIDATION_TIMEOUT_SECONDS,
            allow_redirects=False,
        )
    except (requests.exceptions.RequestException, PlunkResponseTooLargeError, PlunkResponseTimeoutError) as e:
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
            # Bound the customer-controlled host: pin a connect/read timeout and read every body
            # under a decoded-byte cap and wall-clock deadline so it can't hang a worker or OOM it.
            "session": _make_bounded_session(api_key),
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
