import threading
import dataclasses
from collections import Counter
from typing import Any, Optional
from urllib.parse import urlparse

import requests
from requests import PreparedRequest, Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.baserow.settings import (
    CONNECT_TIMEOUT_SECONDS,
    DEFAULT_BASE_URL,
    MAX_PAGES_PER_SYNC,
    MAX_RESPONSE_BYTES,
    PAGE_SIZE,
    READ_DEADLINE_SECONDS,
    READ_TIMEOUT_SECONDS,
    REQUEST_TIMEOUT_SECONDS,
    RESPONSE_READ_CHUNK_BYTES,
    ROWS_PRIMARY_KEYS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_adapter
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http.transport import _NoRedirectSession
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponsePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe


@dataclasses.dataclass
class BaserowResumeConfig:
    next_url: str


def normalize_base_url(base_url: Optional[str]) -> str:
    """Normalize the instance URL and reject anything that isn't HTTPS.

    The database token travels in a header to a user-supplied host, so plaintext
    http:// is rejected to keep it off the wire in the clear. Bare hosts default
    to https; a blank value means the hosted baserow.io service.
    """
    host = (base_url or "").strip()
    if not host:
        return DEFAULT_BASE_URL
    if "://" not in host:
        host = f"https://{host}"
    host = host.rstrip("/")
    # Reject characters that make urlparse (which the SSRF host check trusts) and the HTTP
    # client disagree on the target host — a backslash or an encoded authority delimiter
    # is the wedge, so refuse them outright.
    lowered = host.lower()
    if "\\" in host or "%5c" in lowered or "%40" in lowered:
        raise ValueError(f"Invalid Baserow instance URL: {host}")
    try:
        parsed = urlparse(host)
        port = parsed.port
    except ValueError:
        raise ValueError(f"Invalid Baserow instance URL: {host}")
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError(f"Invalid Baserow instance URL (must be https): {host}")
    # Credentials in the authority (user:pass@host) would ship the token to `host` while the
    # safety check could be aimed elsewhere; require the authority to be exactly host[:port].
    host_part = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
    expected_netloc = host_part + (f":{port}" if port else "")
    if parsed.netloc.lower() != expected_netloc.lower():
        raise ValueError(f"Invalid Baserow instance URL: {host}")
    return host


def hostname_of(base_url: Optional[str]) -> str:
    return urlparse(normalize_base_url(base_url)).hostname or ""


class _BoundedSession(_NoRedirectSession):
    """No-redirect session that also bounds each request on time and response size.

    The base_url is user-supplied, so a hostile host could accept the connection and
    then stall the response (``RESTClient.send()`` passes no timeout) or return an
    arbitrarily large / highly compressed body (``requests`` buffers and decodes it
    eagerly before returning) to exhaust a worker. Pin a connect/read timeout when the
    caller supplies none, and stream the body under a hard per-response byte cap.
    """

    def send(self, request: PreparedRequest, **kwargs: Any) -> Response:
        kwargs.setdefault("timeout", (CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS))
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
        raise ValueError(f"Baserow response body was not fully delivered within {READ_DEADLINE_SECONDS}s")
    if "error" in result:
        raise result["error"]
    return result.get("body", b"")


def _stream_under_cap(response: Response) -> bytes:
    # Stream *decoded* chunks and abort the instant the running total crosses the cap. A
    # single read(decode_content=True) would inflate the whole compressed body at once — a
    # gzipped page decompresses fully before any size check — so a bomb is bounded only by
    # decoding incrementally and stopping early.
    chunks: list[bytes] = []
    decoded = 0
    for chunk in response.raw.stream(RESPONSE_READ_CHUNK_BYTES, decode_content=True):
        decoded += len(chunk)
        if decoded > MAX_RESPONSE_BYTES:
            raise ValueError(f"Baserow response body exceeded the {MAX_RESPONSE_BYTES}-byte limit")
        chunks.append(chunk)
    return b"".join(chunks)


def _bounded_session(database_token: str, *, extra_headers: Optional[dict[str, str]] = None) -> requests.Session:
    """A tracked, no-redirect, time- and size-bounded session for Baserow's user-supplied host.

    No-redirect is an SSRF boundary: a user-supplied base_url must not be able to bounce API
    calls (and the token header) to an internal host via a 3xx. The bounds keep a hostile host
    from stalling a request or returning an unbounded body. Credentials are registered for
    value-based log redaction.
    """
    session = _BoundedSession()
    adapter = make_tracked_adapter(redact_values=(database_token,))
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    headers = {"Accept": "application/json"}
    if extra_headers:
        headers.update(extra_headers)
    session.headers.update(headers)
    return session


def _get_session(database_token: str) -> requests.Session:
    return _bounded_session(database_token, extra_headers={"Authorization": f"Token {database_token}"})


class BaserowPaginator(JSONResponsePaginator):
    """Follows the `next` URL in Baserow's paginated body, pinned to the configured origin.

    The next URL comes from the response body (and is persisted in resume state), so a
    tampered response must not be able to redirect the token-bearing request to another
    host, port, or a plaintext http:// URL.
    """

    def __init__(self, base_url: str) -> None:
        super().__init__(next_url_path="next")
        self._allowed_netloc = urlparse(normalize_base_url(base_url)).netloc.lower()
        # Cycle guards: a host that keeps returning a `next` link can otherwise keep a
        # resumable import issuing requests until its week-long activity timeout. Track the
        # link we just followed to catch a repeated URL, and count pages as a coarse backstop.
        self._previous_next_url: Optional[str] = None
        self._pages_followed = 0

    def _pin(self, url: str) -> None:
        target = urlparse(url)
        if target.scheme != "https" or target.netloc.lower() != self._allowed_netloc:
            raise ValueError(f"Baserow pagination URL {url!r} is not on the configured instance")

    def _guard_progress(self) -> None:
        if self._next_url is None:
            return
        self._pin(self._next_url)
        if self._next_url == self._previous_next_url:
            raise ValueError(f"Baserow pagination is not advancing (repeated next URL {self._next_url!r})")
        self._pages_followed += 1
        if self._pages_followed > MAX_PAGES_PER_SYNC:
            raise ValueError(f"Baserow sync exceeded the {MAX_PAGES_PER_SYNC}-page limit")
        self._previous_next_url = self._next_url

    def update_state(self, response: requests.Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        if self._has_next_page:
            self._guard_progress()

    def set_resume_state(self, state: dict[str, Any]) -> None:
        super().set_resume_state(state)
        if self._next_url is not None:
            # Seed the repeat guard from the resumed link so a host that immediately echoes it
            # back is caught, and pin it here too (a tampered resume URL must not be followed).
            self._pin(self._next_url)
            self._previous_next_url = self._next_url


def list_tables(base_url: Optional[str], database_token: str) -> list[dict[str, Any]]:
    """List every table the database token can see, across all databases in its workspace."""
    base = normalize_base_url(base_url)
    response = _get_session(database_token).get(
        f"{base}/api/database/tables/all-tables/", timeout=REQUEST_TIMEOUT_SECONDS
    )
    response.raise_for_status()
    tables = response.json()
    if not isinstance(tables, list):
        raise ValueError("Unexpected response from Baserow when listing tables")
    return tables


def build_schema_name_map(tables: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Map schema name -> table. Names stay human-readable; only tables whose name repeats
    across the token's databases get the table id appended, deterministically."""
    name_counts = Counter(str(table["name"]) for table in tables)
    return {
        (str(table["name"]) if name_counts[str(table["name"])] == 1 else f"{table['name']} ({table['id']})"): table
        for table in tables
    }


def resolve_table_id(
    base_url: Optional[str],
    database_token: str,
    schema_name: str,
    schema_metadata: Optional[dict[str, Any]],
) -> int:
    # The table id is stamped into schema_metadata at schema creation, so a later rename of
    # the Baserow table keeps syncing into the same warehouse table. The re-listing below is
    # only a safety net for schemas persisted without metadata.
    if schema_metadata and schema_metadata.get("table_id") is not None:
        return int(schema_metadata["table_id"])

    table = build_schema_name_map(list_tables(base_url, database_token)).get(schema_name)
    if table is None:
        raise ValueError(f"Baserow table for schema {schema_name!r} not found — it may have been renamed or deleted")
    return int(table["id"])


def check_table_read_permission(base_url: Optional[str], database_token: str, table_id: int) -> str | None:
    """Return None when the token can read the table's rows, or a short reason when it can't.

    Database tokens carry per-table CRUD toggles; a token without read on a table gets a 401
    ``ERROR_NO_PERMISSION_TO_TABLE`` from the rows endpoint. Only a real denial is a missing
    permission — a throttle, 5xx, or network blip must not mark the table unreachable.
    """
    base = normalize_base_url(base_url)
    try:
        response = _get_session(database_token).get(
            f"{base}/api/database/rows/table/{table_id}/",
            params={"size": 1},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except Exception:
        return None
    if response.status_code in (401, 403):
        return "The database token does not have read permission for this table. Enable read access for it in Baserow's token settings."
    return None


def validate_credentials(base_url: Optional[str], database_token: str) -> tuple[bool, int | None]:
    base = normalize_base_url(base_url)
    return validate_via_probe(
        lambda: _bounded_session(database_token),
        f"{base}/api/database/tables/all-tables/",
        headers={"Authorization": f"Token {database_token}"},
        timeout=REQUEST_TIMEOUT_SECONDS,
        allow_redirects=False,
    )


def baserow_rows_source(
    base_url: Optional[str],
    database_token: str,
    table_id: int,
    schema_name: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[BaserowResumeConfig],
) -> SourceResponse:
    base = normalize_base_url(base_url)

    config: RESTAPIConfig = {
        "client": {
            "base_url": base,
            "auth": {
                "type": "api_key",
                "name": "Authorization",
                "api_key": f"Token {database_token}",
                "location": "header",
            },
            "paginator": BaserowPaginator(base),
            # RESTClient.send() passes no timeout and buffers the whole body eagerly, so the
            # row-page reads run through the bounded session — otherwise a user-controlled host
            # could stall a request or return an unbounded page and occupy an import worker.
            "session": _bounded_session(database_token),
        },
        "resources": [
            {
                "name": "rows",
                "endpoint": {
                    "path": f"/api/database/rows/table/{table_id}/",
                    "params": {
                        "size": PAGE_SIZE,
                        # Human-readable column names. Safe: Baserow reserves `id` and
                        # `order` as field names, so the row's own keys can't be shadowed.
                        "user_field_names": "true",
                    },
                    "data_selector": "results",
                },
                # Rows expose no server-side updated-since filter, so every sync is a full refresh.
                "write_disposition": "replace",
                "table_format": "delta",
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = {"next_url": resume_config.next_url}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Only persist when there's a next page to resume to; the Redis TTL
        # handles cleanup on completion.
        if state and state.get("next_url"):
            resumable_source_manager.save_state(BaserowResumeConfig(next_url=str(state["next_url"])))

    resource = rest_api_resource(
        config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=schema_name,
        items=lambda: resource,
        primary_keys=list(ROWS_PRIMARY_KEYS),
    )
