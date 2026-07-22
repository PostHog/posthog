import re
import json
import socket
import threading
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode, urlparse

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import _is_host_safe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.gerrit.settings import (
    CHANGES_BASE_QUERY,
    GERRIT_ENDPOINTS,
    GerritEndpointConfig,
)

REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 5

# Hard ceilings on how much of a response body we'll pull into memory and how long we'll spend
# pulling it. The host is customer-supplied, so a hostile server could otherwise stream an
# unbounded or slow-drip body and OOM / tie up a shared worker — the socket read timeout only
# bounds idle gaps, not total bytes or total wall-clock. A single page of the largest endpoint
# (100 fully-expanded changes) sits comfortably under the byte cap.
MAX_RESPONSE_BYTES = 64 * 1024 * 1024
MAX_DOWNLOAD_SECONDS = 120
DOWNLOAD_CHUNK_BYTES = 64 * 1024

# Anti-XSSI magic prefix Gerrit prepends to every JSON response body.
XSSI_PREFIX = ")]}'"

HOST_NOT_ALLOWED_ERROR = "Gerrit host is not allowed"

# Loopback hosts where plaintext HTTP carries no network-exposure risk (local dev / self-hosted on
# the same box). Every other host is forced to HTTPS so credentials never traverse a network in
# cleartext.
LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


class GerritRetryableError(Exception):
    pass


class GerritHostNotAllowedError(Exception):
    pass


class GerritResponseTooLargeError(Exception):
    pass


@dataclasses.dataclass
class GerritResumeConfig:
    # Number of rows already fetched for the endpoint — Gerrit paginates with an `S` skip offset.
    offset: int = 0


def normalize_host(host: str) -> str:
    """Turn whatever the user typed into a Gerrit base URL (scheme + host + optional context path).

    Unlike most SaaS sources, a self-hosted Gerrit can live under a context path (e.g.
    ``https://example.com/r``), so any path the user supplied is preserved — only trailing slashes
    and a trailing ``/a`` (the authenticated-API prefix we add ourselves) are stripped. Defaults to
    https when no scheme is given, and forces a plaintext ``http://`` host to ``https://`` so
    credentials are never sent over the network in cleartext — except for loopback hosts.
    """
    host = host.strip()
    if not re.match(r"^https?://", host, flags=re.IGNORECASE):
        host = f"https://{host}"
    parsed = urlparse(host)
    scheme = parsed.scheme.lower()
    if scheme == "http" and (parsed.hostname or "").lower() not in LOOPBACK_HOSTS:
        scheme = "https"
    path = parsed.path.rstrip("/")
    if path.endswith("/a"):
        path = path[: -len("/a")]
    return f"{scheme}://{parsed.netloc}{path}"


def _hostname(host: str) -> str:
    return (urlparse(normalize_host(host)).hostname or "").lower()


def parse_gerrit_response(text: str) -> Any:
    """Parse a Gerrit JSON response body, stripping the ``)]}'`` anti-XSSI prefix."""
    stripped = text.lstrip()
    if stripped.startswith(XSSI_PREFIX):
        stripped = stripped[len(XSSI_PREFIX) :]
    return json.loads(stripped)


def _underlying_socket(response: requests.Response) -> Optional[socket.socket]:
    """Best-effort reach for the raw socket behind a streamed response.

    Used only to release a drain thread stuck in a body read once the download deadline fires.
    The attribute chain into urllib3/``http.client`` is private, so this stays defensive and
    returns ``None`` if the layout differs — the caller still returns at the deadline either way.
    """
    for path in (("_fp", "fp", "raw", "_sock"), ("_connection", "sock")):
        obj: Any = getattr(response, "raw", None)
        for attr in path:
            obj = getattr(obj, attr, None)
            if obj is None:
                break
        if isinstance(obj, socket.socket):
            return obj
    return None


def _read_capped_text(response: requests.Response) -> str:
    """Drain a streamed response body under a byte cap and a hard wall-clock deadline, then decode.

    The request is issued with ``stream=True`` so nothing is buffered until this read. Two limits
    protect a shared worker from a hostile customer-supplied host:

    * ``MAX_RESPONSE_BYTES`` caps how much we buffer into memory, checked as chunks arrive.
    * ``MAX_DOWNLOAD_SECONDS`` caps total wall-clock. This is *not* enforceable via the socket read
      timeout alone: that timeout resets on every ``recv``, so a host dripping one byte just under
      it keeps a single ``iter_content`` read (which blocks until a full chunk is read) parked
      indefinitely. Nor can ``Response.close()`` from a timer reliably cancel that parked read. So
      the body is drained on a worker thread and this caller waits on it for at most the deadline;
      once it elapses the caller returns immediately — a sync worker is never held past the
      deadline regardless of platform — and shuts the socket down to release the drain thread
      (``shutdown`` unblocks a parked ``recv`` on POSIX where ``close`` does not).
    """
    result: dict[str, Any] = {}
    done = threading.Event()

    def _drain() -> None:
        try:
            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_content(chunk_size=DOWNLOAD_CHUNK_BYTES):
                if not chunk:
                    continue
                total += len(chunk)
                if total > MAX_RESPONSE_BYTES:
                    raise GerritResponseTooLargeError("Gerrit returned an oversized response body")
                chunks.append(chunk)
            result["text"] = b"".join(chunks).decode(response.encoding or "utf-8", errors="replace")
        except Exception as exc:
            result["error"] = exc
        finally:
            done.set()

    thread = threading.Thread(target=_drain, name="gerrit-body-drain", daemon=True)
    thread.start()

    if not done.wait(MAX_DOWNLOAD_SECONDS):
        drain_socket = _underlying_socket(response)
        if drain_socket is not None:
            try:
                drain_socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        response.close()
        raise GerritResponseTooLargeError("Gerrit response body took too long to download")

    if "error" in result:
        raise result["error"]
    return result["text"]


def _api_base(base_url: str, authenticated: bool) -> str:
    # Authenticated requests go through the `/a/` path prefix; anonymous ones hit the same
    # endpoints without it (public instances allow anonymous reads).
    return f"{base_url}/a" if authenticated else base_url


def format_after_value(value: Any) -> str:
    """Format an incremental cursor for Gerrit's ``after:"YYYY-MM-DD HH:MM:SS"`` query operator.

    Gerrit timestamps are UTC; the stored watermark comes back as a (usually naive, UTC) datetime
    parsed from the change's ``updated`` field.
    """
    if isinstance(value, datetime):
        utc_value = value.astimezone(UTC) if value.tzinfo is not None else value
        return utc_value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d 00:00:00")
    return str(value)


def build_changes_query(db_incremental_field_last_value: Optional[Any]) -> str:
    if db_incremental_field_last_value is None:
        return CHANGES_BASE_QUERY
    return f'({CHANGES_BASE_QUERY}) after:"{format_after_value(db_incremental_field_last_value)}"'


def _rows_from_response(config: GerritEndpointConfig, data: Any) -> tuple[list[dict[str, Any]], bool]:
    """Normalize a page into row dicts and read Gerrit's more-results flag off the last entry."""
    if config.response_kind == "map":
        rows = []
        for key, value in (data or {}).items():
            if not isinstance(value, dict):
                continue
            row = dict(value)
            # Map responses key entries by resource name and may omit it from the entry itself.
            row.setdefault("name", key)
            rows.append(row)
    else:
        rows = [dict(item) for item in (data or []) if isinstance(item, dict)]

    has_more = any(row.pop(config.more_flag, False) for row in rows)
    return rows, has_more


def _connection_error_message(error: Exception) -> str:
    """Translate a low-level requests connection failure into a short, actionable message
    without echoing the raw error, which embeds the customer's host/IP."""
    text = str(error).lower()
    if isinstance(error, requests.exceptions.SSLError):
        return (
            "Couldn't establish a secure (HTTPS) connection to your Gerrit instance. "
            "Check that the instance URL is correct and its TLS certificate is valid."
        )
    if isinstance(error, requests.exceptions.Timeout):
        return (
            "Connecting to your Gerrit instance timed out. "
            "Check that the instance URL is correct and reachable from the public internet."
        )
    if isinstance(error, requests.exceptions.ConnectionError) and (
        "name or service not known" in text or "nodename nor servname" in text or "failed to resolve" in text
    ):
        return (
            "Couldn't resolve the Gerrit host. "
            "Check that the instance URL is spelled correctly and reachable from the public internet."
        )
    return (
        "Couldn't connect to your Gerrit instance. "
        "Check that the instance URL is correct and reachable from the public internet."
    )


def _make_session(username: Optional[str], http_password: Optional[str]) -> requests.Session:
    redact_values = tuple(v for v in (http_password,) if v)
    session = make_tracked_session(allow_redirects=False, redact_values=redact_values)
    if username and http_password:
        session.auth = (username, http_password)
    return session


def validate_credentials(
    host: str,
    username: Optional[str],
    http_password: Optional[str],
    team_id: Optional[int] = None,
    schema_name: Optional[str] = None,
) -> tuple[bool, str | None]:
    """Probe the instance: with credentials, ``/a/accounts/self`` confirms the HTTP password is
    genuine; without, ``/config/server/version`` confirms the instance allows anonymous reads.
    With ``schema_name`` set, probe that endpoint instead — group listing in particular needs an
    authenticated account."""
    try:
        base_url = normalize_host(host)
    except Exception:
        return False, "Invalid Gerrit instance URL"

    hostname = _hostname(host)
    if not hostname or not re.match(r"^[A-Za-z0-9.\-]+$", hostname):
        return False, "Invalid Gerrit instance URL"

    if team_id is not None:
        host_ok, host_err = _is_host_safe(hostname, team_id)
        if not host_ok:
            return False, host_err or HOST_NOT_ALLOWED_ERROR

    authenticated = bool(username and http_password)
    if (username and not http_password) or (http_password and not username):
        return False, "Enter both a username and an HTTP password, or leave both blank for anonymous access"

    session = _make_session(username, http_password)
    api_base = _api_base(base_url, authenticated)

    if schema_name is not None and schema_name in GERRIT_ENDPOINTS:
        config = GERRIT_ENDPOINTS[schema_name]
        params: dict[str, str | list[str]] = {**config.params, "n": "1"}
        if schema_name == "changes":
            params["q"] = CHANGES_BASE_QUERY
        probe_url = f"{api_base}{config.path}?{urlencode(params, doseq=True)}"
    elif authenticated:
        probe_url = f"{api_base}/accounts/self"
    else:
        probe_url = f"{api_base}/config/server/version"

    # stream=True so the body isn't buffered until we drain it under a cap (see _read_capped_text).
    try:
        with session.get(probe_url, timeout=10, allow_redirects=False, stream=True) as response:
            if response.is_redirect or response.is_permanent_redirect:
                return False, HOST_NOT_ALLOWED_ERROR
            if response.status_code == 200:
                try:
                    parse_gerrit_response(_read_capped_text(response))
                except GerritResponseTooLargeError:
                    return False, (
                        "Gerrit returned an unexpectedly large response. "
                        "Check that the instance URL points to your Gerrit instance."
                    )
                except (json.JSONDecodeError, ValueError):
                    return False, (
                        "Gerrit didn't return a valid API response. "
                        "Check that the instance URL points to your Gerrit instance."
                    )
                return True, None
            if response.status_code == 401:
                return False, "Invalid Gerrit username or HTTP password"
            if response.status_code == 403:
                # Valid token but missing permission for this probe — let source creation through;
                # per-schema probes still report it so users can deselect the table.
                if schema_name is None:
                    return True, None
                return False, "Your Gerrit account lacks permission to read this resource"

            return (
                False,
                f"Gerrit returned an unexpected response (HTTP {response.status_code}). "
                "Check that the instance URL points to your Gerrit instance.",
            )
    except requests.exceptions.RequestException as e:
        return False, _connection_error_message(e)


def get_rows(
    host: str,
    username: Optional[str],
    http_password: Optional[str],
    endpoint: str,
    team_id: int,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[GerritResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> Iterator[list[dict[str, Any]]]:
    config = GERRIT_ENDPOINTS[endpoint]
    base_url = normalize_host(host)

    # Re-check at run time (not just source-create) in case the host was edited or now resolves
    # to an internal address (SSRF / DNS rebinding). Only enforced on cloud.
    host_ok, host_err = _is_host_safe(_hostname(host), team_id)
    if not host_ok:
        raise GerritHostNotAllowedError(host_err or HOST_NOT_ALLOWED_ERROR)

    authenticated = bool(username and http_password)
    session = _make_session(username, http_password)
    api_base = _api_base(base_url, authenticated)

    params: dict[str, str | list[str]] = dict(config.params)
    if endpoint == "changes":
        params["q"] = build_changes_query(db_incremental_field_last_value if should_use_incremental_field else None)

    offset = 0
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.offset:
        offset = resume.offset
        logger.debug(f"Gerrit: resuming {endpoint} from offset {offset}")

    @retry(
        retry=retry_if_exception_type((GerritRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential_jitter(initial=1, max=30),
        reraise=True,
    )
    def fetch(page_url: str) -> str:
        # Don't follow redirects: a customer-controlled host could 3xx to an internal address,
        # bypassing the host check above (SSRF). stream=True so the body isn't buffered until we
        # drain it under a cap (see _read_capped_text).
        with session.get(page_url, timeout=REQUEST_TIMEOUT_SECONDS, allow_redirects=False, stream=True) as response:
            # Gerrit rate limits surface as 429 with an instance-configured window; back off and retry.
            if response.status_code == 429 or response.status_code >= 500:
                raise GerritRetryableError(
                    f"Gerrit API error (retryable): status={response.status_code}, url={page_url}"
                )
            if response.is_redirect or response.is_permanent_redirect:
                raise GerritHostNotAllowedError(
                    f"Gerrit API returned an unexpected redirect (status={response.status_code}); refusing to follow it"
                )
            if not response.ok:
                logger.error(
                    f"Gerrit API error: status={response.status_code}, body={_read_capped_text(response)}, url={page_url}"
                )
                response.raise_for_status()

            return _read_capped_text(response)

    while True:
        page_params: dict[str, str | list[str]] = {**params, "n": str(config.page_size)}
        if offset:
            page_params["S"] = str(offset)
        url = f"{api_base}{config.path}?{urlencode(page_params, doseq=True)}"

        rows, has_more = _rows_from_response(config, parse_gerrit_response(fetch(url)))

        if not rows:
            break

        offset += len(rows)
        yield rows

        if not has_more:
            break

        # Save AFTER yielding so a crash re-yields the last page rather than skipping it —
        # merge dedupes on the primary key.
        resumable_source_manager.save_state(GerritResumeConfig(offset=offset))


def gerrit_source(
    host: str,
    username: Optional[str],
    http_password: Optional[str],
    endpoint: str,
    team_id: int,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[GerritResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = GERRIT_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            host=host,
            username=username,
            http_password=http_password,
            endpoint=endpoint,
            team_id=team_id,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        # /changes/ returns newest-first on `updated` with no ascending option, so the pipeline
        # must persist the incremental watermark only at successful job end.
        sort_mode=config.sort_mode,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
