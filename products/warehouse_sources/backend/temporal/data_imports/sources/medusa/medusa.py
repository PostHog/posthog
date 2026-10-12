import threading
from typing import Any, Optional
from urllib.parse import urlparse

import requests
from requests import PreparedRequest, Response
from requests.auth import HTTPBasicAuth

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.datetime_utils import parse_datetime_value
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_adapter
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http.transport import _NoRedirectSession
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    OffsetPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    Endpoint,
    EndpointResource,
    IncrementalConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.medusa.settings import (
    CONNECT_TIMEOUT_SECONDS,
    MAX_RESPONSE_BYTES,
    MAX_ROWS_PER_SYNC,
    MEDUSA_ENDPOINTS,
    PAGE_SIZE,
    PARTITION_KEY,
    PRIMARY_KEYS,
    READ_DEADLINE_SECONDS,
    READ_TIMEOUT_SECONDS,
    REQUEST_TIMEOUT_SECONDS,
    RESPONSE_READ_CHUNK_BYTES,
    MedusaEndpointConfig,
)

HTTPS_REQUIRED_ERROR = "Medusa server URL must use HTTPS"
INVALID_URL_ERROR = "Invalid Medusa server URL"
PAGINATION_LIMIT_ERROR = "Medusa pagination did not terminate"


@frozen
class MedusaResumeConfig:
    # Opaque framework checkpoint: the offset paginator's next position. Round-tripped into
    # `initial_paginator_state` on resume.
    paginator_state: dict[str, Any]


def normalize_base_url(base_url: Optional[str]) -> str:
    """Normalize the server URL and reject anything that isn't HTTPS.

    The secret API key travels in an Authorization header to a user-supplied host, so
    plaintext http:// is rejected to keep it off the wire in the clear. Bare hosts default
    to https. A subpath is kept because Medusa is sometimes served behind a reverse proxy
    under a path prefix.
    """
    host = (base_url or "").strip()
    if not host:
        raise ValueError(f"{INVALID_URL_ERROR}: enter your server's URL, e.g. https://store.example.com")
    if host.lower().startswith("http://"):
        raise ValueError(HTTPS_REQUIRED_ERROR)
    if "://" not in host:
        host = f"https://{host}"
    host = host.rstrip("/")
    # Reject characters that make urlparse (which the SSRF host check trusts) and the HTTP
    # client disagree on the target host; a backslash or an encoded authority delimiter is
    # the wedge, so refuse them outright.
    lowered = host.lower()
    if "\\" in host or "%5c" in lowered or "%40" in lowered:
        raise ValueError(f"{INVALID_URL_ERROR}: {host}")
    try:
        parsed = urlparse(host)
        port = parsed.port
    except ValueError:
        raise ValueError(f"{INVALID_URL_ERROR}: {host}")
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError(f"{INVALID_URL_ERROR} (must be https): {host}")
    # Credentials in the authority (user:pass@host) would ship the API key to `host` while
    # the safety check could be aimed elsewhere; require the authority to be exactly
    # host[:port].
    host_part = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
    expected_netloc = host_part + (f":{port}" if port else "")
    if parsed.netloc.lower() != expected_netloc.lower():
        raise ValueError(f"{INVALID_URL_ERROR}: {host}")
    return host


def hostname_of(base_url: Optional[str]) -> str:
    return urlparse(normalize_base_url(base_url)).hostname or ""


class _BoundedSession(_NoRedirectSession):
    """No-redirect session that also bounds each request on time and response size.

    The base URL is user-supplied, so a hostile host could accept the connection and then
    stall the response or return an arbitrarily large / highly compressed body (``requests``
    buffers and decodes it eagerly before returning) to exhaust a worker. Pin a connect/read
    timeout when the caller supplies none, and stream the body under a hard per-response
    byte cap.
    """

    def send(self, request: PreparedRequest, **kwargs: Any) -> Response:
        # `requests.Session.request` and `RESTClient` both pass an explicit `timeout` kwarg
        # (None when the caller set none), so a plain setdefault would never fire.
        if kwargs.get("timeout") is None:
            kwargs["timeout"] = (CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS)
        kwargs["stream"] = True
        response = super().send(request, **kwargs)
        try:
            body = _read_capped(response)
        finally:
            response.close()
        response._content = body
        response._content_consumed = True  # type: ignore[attr-defined]
        return response


def _read_capped(response: Response) -> bytes:
    """Buffer the body under both a size cap and a hard wall-clock deadline.

    READ_TIMEOUT_SECONDS is only a socket-inactivity timeout, so a host that drips a byte
    before each idle window keeps the read blocked indefinitely while staying under the byte
    cap. Read on a daemon thread and abandon it past READ_DEADLINE_SECONDS, closing the
    response to unblock the socket, so a slow-drip host can't monopolize a worker.
    """
    result: dict[str, Any] = {}

    def drain() -> None:
        try:
            result["body"] = _stream_under_cap(response)
        except BaseException as exc:  # noqa: BLE001 — surfaced to the caller after the join below
            result["error"] = exc

    thread = threading.Thread(target=drain, daemon=True)
    thread.start()
    thread.join(READ_DEADLINE_SECONDS)
    if thread.is_alive():
        # Closing the response unblocks the raw read so the abandoned daemon thread can exit.
        response.close()
        raise ValueError(f"Medusa response body was not fully delivered within {READ_DEADLINE_SECONDS}s")
    if "error" in result:
        raise result["error"]
    return result.get("body", b"")


def _stream_under_cap(response: Response) -> bytes:
    # Stream *decoded* chunks and abort the instant the running total crosses the cap. A
    # single read(decode_content=True) would inflate the whole compressed body at once, so a
    # bomb is bounded only by decoding incrementally and stopping early.
    chunks: list[bytes] = []
    decoded = 0
    for chunk in response.raw.stream(RESPONSE_READ_CHUNK_BYTES, decode_content=True):
        decoded += len(chunk)
        if decoded > MAX_RESPONSE_BYTES:
            raise ValueError(f"Medusa response body exceeded the {MAX_RESPONSE_BYTES}-byte limit")
        chunks.append(chunk)
    return b"".join(chunks)


def _bounded_session(api_key: str) -> requests.Session:
    """A tracked, no-redirect, time- and size-bounded session for Medusa's user-supplied host.

    No-redirect is an SSRF boundary: a user-supplied base URL must not be able to bounce API
    calls (and the Authorization header) to another host via a 3xx. The bounds keep a hostile
    host from stalling a request or returning an unbounded body. The key is registered for
    value-based log redaction.
    """
    session = _BoundedSession()
    adapter = make_tracked_adapter(redact_values=(api_key,))
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({"Accept": "application/json"})
    return session


def validate_credentials(base_url: Optional[str], api_key: str) -> tuple[bool, int | None]:
    """Confirm the secret API key is genuine with one cheap list call.

    Medusa v2 authenticates secret API keys with HTTP Basic: the key is the username, the
    password is empty (the `api_token` security scheme in the Admin API spec).
    """
    base = normalize_base_url(base_url)
    return validate_via_probe(
        lambda: _bounded_session(api_key),
        f"{base}/admin/regions?limit=1",
        auth=HTTPBasicAuth(api_key, ""),
        timeout=REQUEST_TIMEOUT_SECONDS,
        allow_redirects=False,
    )


def _to_iso8601(value: Any) -> Optional[str]:
    """Medusa's timestamp filters compare against timestamptz columns; send a UTC instant."""
    moment = parse_datetime_value(value)
    if moment is None:
        return None
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


class MedusaPaginator(OffsetPaginator):
    """Offset paginator that stops on a short or empty page, with a hard row budget.

    `total_path` stays None: the short-page rule already terminates, and reading `count`
    would re-parse every page body just to stop one request earlier. The host is
    user-supplied, so a server that keeps returning full pages forever must not be able to
    keep a resumable import issuing requests until its activity timeout; past the budget the
    sync fails loudly instead of completing on a sliver. The budget rides `offset`, which is
    part of the framework's persisted resume state.
    """

    def __init__(self) -> None:
        super().__init__(limit=PAGE_SIZE, total_path=None)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        if self._has_next_page and self.offset >= MAX_ROWS_PER_SYNC:
            raise ValueError(f"{PAGINATION_LIMIT_ERROR}: exceeded {MAX_ROWS_PER_SYNC} rows in one sync")


def get_resource(
    config: MedusaEndpointConfig,
    should_use_incremental_field: bool,
    incremental_field_name: Optional[str] = None,
) -> EndpointResource:
    cursor_field: str = "created_at"
    if should_use_incremental_field:
        if config.incremental_field_name is None:
            raise ValueError(f"Medusa endpoint '{config.name}' does not support incremental sync")
        if incremental_field_name is not None and incremental_field_name != config.incremental_field_name:
            raise ValueError(f"Medusa endpoint '{config.name}' has no incremental field '{incremental_field_name}'")
        cursor_field = config.incremental_field_name

    endpoint: Endpoint = {
        "path": f"/admin{config.path}",
        "params": {
            # Explicit ascending sort: it keeps offset page boundaries stable while rows are
            # inserted mid-sync, and on incremental runs it matches sort_mode="asc" so the
            # watermark checkpoints correctly. `created_at` is immutable, so a full refresh
            # sorts on it; incremental runs sort on the cursor field itself.
            "order": cursor_field,
        },
        "paginator": MedusaPaginator(),
        "data_selector": config.data_selector,
    }

    if should_use_incremental_field:
        # Medusa parses nested query operators with `qs`, which accepts the percent-encoded
        # brackets `requests` produces for a literal `updated_at[$gte]=...` param. `$gte` is
        # inclusive, so the boundary row is re-read on each run; the merge dedupes it on `id`.
        incremental: IncrementalConfig = {
            "start_param": f"{cursor_field}[$gte]",
            "cursor_path": cursor_field,
            "convert": _to_iso8601,
        }
        endpoint["incremental"] = incremental

    return {
        "name": config.name,
        "table_name": config.name.lower(),
        "write_disposition": {"disposition": "merge", "strategy": "upsert"}
        if should_use_incremental_field
        else "replace",
        "endpoint": endpoint,
        "table_format": "delta",
    }


def medusa_source(
    base_url: str,
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[MedusaResumeConfig],
    should_use_incremental_field: bool = False,
    incremental_field_name: Optional[str] = None,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    base = normalize_base_url(base_url)
    config = MEDUSA_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": base,
            # The framework auth builds the Basic header and redacts the key from logs and
            # raised errors.
            "auth": {"type": "http_basic", "username": api_key, "password": ""},
            # The key rides in the Authorization header to a user-supplied host: pin every
            # request to that host, reject redirects off it, and bound each response in time
            # and size via the session.
            "session": _bounded_session(api_key),
            "allowed_hosts": [],
            "allow_redirects": False,
            "request_timeout": (CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS),
        },
        "resources": [get_resource(config, should_use_incremental_field, incremental_field_name)],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = resume_config.paginator_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Only persist when there's a next page to resume to; the Redis TTL handles cleanup
        # on completion. Saved after a page is yielded, so a crash re-fetches from the next
        # position and never skips a page (a re-fetched page is deduped by the merge).
        if state:
            resumable_source_manager.save_state(MedusaResumeConfig(paginator_state=dict(state)))

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
        primary_keys=list(PRIMARY_KEYS),
        column_hints=resource.column_hints,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="month",
        partition_keys=[PARTITION_KEY],
        sort_mode="asc",
    )
