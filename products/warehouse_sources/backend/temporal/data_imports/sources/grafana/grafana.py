import re
import json
import time
import base64
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
from products.warehouse_sources.backend.temporal.data_imports.sources.grafana.settings import (
    ANNOTATIONS_LIMIT,
    DEFAULT_PAGE_SIZE,
    GRAFANA_ENDPOINTS,
    GrafanaEndpointConfig,
)

REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 5

# Every Grafana list endpoint here is paginated (DEFAULT_PAGE_SIZE / ANNOTATIONS_LIMIT rows), so a
# well-behaved response body is small. This ceiling exists only to stop a malicious or misconfigured
# host from exhausting an import worker's memory with an unbounded (or Content-Length-less, chunked)
# body — requests buffers the whole body otherwise.
MAX_RESPONSE_BYTES = 64 * 1024 * 1024

# Total wall-clock budget for downloading one response body. The socket timeout only caps inactivity
# between chunks, so a host that trickles bytes just under that timeout could occupy a worker
# indefinitely; this bounds the whole read regardless of how the bytes are paced.
MAX_RESPONSE_READ_SECONDS = 120

HOST_NOT_ALLOWED_ERROR = "Grafana host is not allowed"

TOKEN_AUTH = "token"
BASIC_AUTH = "basic"

# Below this window width, stop bisecting a saturated annotations window and accept truncation:
# more than ANNOTATIONS_LIMIT annotations inside one minute can't be separated by the from/to
# filter's millisecond granularity in a bounded number of requests.
MIN_ANNOTATION_WINDOW_MS = 60 * 1000

# Loopback hosts where plaintext HTTP carries no network-exposure risk (local dev / self-hosted on
# the same box). Every other host is forced to HTTPS so credentials never traverse a network in
# cleartext.
LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


class GrafanaRetryableError(Exception):
    pass


class GrafanaHostNotAllowedError(Exception):
    pass


class GrafanaAuthError(Exception):
    """Raised when credentials are missing or malformed. Deterministic — retrying never fixes
    it — so it surfaces via get_non_retryable_errors."""

    pass


class GrafanaResponseTooLargeError(Exception):
    """A response body exceeded the size or time budget for a single request. Deterministic for a
    given host config — not retried — so it fails the request fast instead of buffering forever."""

    pass


@dataclasses.dataclass
class GrafanaAuth:
    # "token" sends a service account token as an Authorization: Bearer header (works on both
    # Grafana Cloud and self-hosted); "basic" sends HTTP Basic credentials (self-hosted OSS only —
    # Grafana Cloud rejects basic auth on the HTTP API).
    method: str
    token: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None


@dataclasses.dataclass
class GrafanaResumeConfig:
    # Next page to fetch for page-number endpoints. None for the other pagination styles.
    next_page: int | None = None
    # Lower bound (epoch ms) of the next annotations window to fetch. Windows are processed in
    # ascending order, so everything before this boundary has already been yielded.
    annotations_from_ms: int | None = None


def _with_default_scheme(host: str) -> str:
    host = host.strip()
    if not re.match(r"^https?://", host, flags=re.IGNORECASE):
        host = f"https://{host}"
    return host


def has_embedded_credentials(host: str) -> bool:
    """Whether the URL carries userinfo (``https://user:pass@host``).

    The host field is stored as non-secret config, so credentials embedded in it would be
    visible to anyone who can view the source configuration — reject them at validation.
    """
    try:
        parsed = urlparse(_with_default_scheme(host))
        return bool(parsed.username or parsed.password)
    except ValueError:
        return False


def normalize_host(host: str) -> str:
    """Turn whatever the user typed into a bare instance base URL (scheme + host, no path).

    Accepts ``https://yourstack.grafana.net``, ``yourstack.grafana.net``,
    ``https://yourstack.grafana.net/api`` and returns ``https://yourstack.grafana.net``.
    Defaults to https when no scheme is given, and forces a plaintext ``http://`` host to
    ``https://`` so credentials are never sent over the network in cleartext — except for
    loopback hosts (local dev / self-hosted on the same box), which are left untouched.
    """
    parsed = urlparse(_with_default_scheme(host))
    scheme = parsed.scheme.lower()
    hostname = (parsed.hostname or "").lower()
    if scheme == "http" and hostname not in LOOPBACK_HOSTS:
        scheme = "https"
    # Rebuild netloc from hostname + port only: drops any trailing path (e.g. "/api") and any
    # userinfo — URL-embedded credentials must never be persisted or sent (see
    # has_embedded_credentials, which rejects them at validation as well).
    if ":" in hostname:  # a bare IPv6 address needs its brackets back
        hostname = f"[{hostname}]"
    netloc = f"{hostname}:{parsed.port}" if parsed.port else hostname
    return f"{scheme}://{netloc}"


def _hostname(host: str) -> str:
    return (urlparse(normalize_host(host)).hostname or "").lower()


def _resolve_auth_headers(auth: GrafanaAuth, org_id: Optional[str] = None) -> dict[str, str]:
    headers: dict[str, str] = {"Accept": "application/json"}

    if auth.method == TOKEN_AUTH:
        if not auth.token:
            raise GrafanaAuthError("Missing Grafana service account token")
        headers["Authorization"] = f"Bearer {auth.token}"
    else:
        if not auth.username or not auth.password:
            raise GrafanaAuthError("Missing Grafana username or password")
        encoded = base64.b64encode(f"{auth.username}:{auth.password}".encode()).decode()
        headers["Authorization"] = f"Basic {encoded}"

    if org_id and str(org_id).strip():
        headers["X-Grafana-Org-Id"] = str(org_id).strip()

    return headers


def _redact_values(auth: GrafanaAuth) -> tuple[str, ...]:
    """Credential strings to value-mask in any captured data-request sample, on top of the
    name-based header/body scrubbers — defense-in-depth in case a credential ever echoes into
    a response body."""
    if auth.method == TOKEN_AUTH:
        return (auth.token,) if auth.token else ()
    return tuple(v for v in (auth.username, auth.password) if v)


def _connection_error_message(error: Exception) -> str:
    """Translate a low-level requests connection failure into a short, actionable message.

    requests surfaces these as host-revealing blobs; returning that verbatim leaks the
    customer's host/IP and tells them nothing they can act on.
    """
    text = str(error).lower()
    if isinstance(error, requests.exceptions.SSLError):
        return (
            "Couldn't establish a secure (TLS) connection to your Grafana instance. "
            "Check that the instance URL is correct and its TLS certificate is valid."
        )
    if isinstance(error, requests.exceptions.Timeout):
        return (
            "Connecting to your Grafana instance timed out. "
            "Check that the instance URL is correct and reachable from the public internet."
        )
    if isinstance(error, requests.exceptions.ConnectionError) and (
        "name or service not known" in text or "nodename nor servname" in text or "failed to resolve" in text
    ):
        return (
            "Couldn't resolve the Grafana host. "
            "Check that the instance URL is spelled correctly and reachable from the public internet."
        )
    return (
        "Couldn't connect to your Grafana instance. "
        "Check that the instance URL is correct and reachable from the public internet."
    )


def _read_body_bounded(response: requests.Response) -> bytes:
    """Download a streamed response body under a hard size and time budget.

    Must be called on a response fetched with ``stream=True`` so nothing is buffered before these
    caps apply. Rejects an oversized declared ``Content-Length`` up front, then reads chunk by
    chunk, aborting if the running total exceeds MAX_RESPONSE_BYTES or the read outlasts
    MAX_RESPONSE_READ_SECONDS. A customer-controlled host can otherwise return an arbitrarily large
    body or trickle one forever, exhausting or indefinitely occupying an import worker.
    """
    declared = response.headers.get("Content-Length")
    if declared is not None:
        try:
            if int(declared) > MAX_RESPONSE_BYTES:
                raise GrafanaResponseTooLargeError(
                    f"Grafana response Content-Length {declared} exceeds the {MAX_RESPONSE_BYTES}-byte limit"
                )
        except ValueError:
            pass  # unparseable header — fall through to the streamed cap below

    deadline = time.monotonic() + MAX_RESPONSE_READ_SECONDS
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_content(chunk_size=64 * 1024):
        total += len(chunk)
        if total > MAX_RESPONSE_BYTES:
            raise GrafanaResponseTooLargeError(f"Grafana response exceeded the {MAX_RESPONSE_BYTES}-byte limit")
        if time.monotonic() > deadline:
            raise GrafanaResponseTooLargeError(
                f"Reading the Grafana response exceeded the {MAX_RESPONSE_READ_SECONDS}s limit"
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _read_json_bounded(response: requests.Response) -> Any:
    """Read a streamed response body under the size/time budget, then parse it as JSON."""
    body = _read_body_bounded(response)
    if not body:
        return None
    return json.loads(body)


def _extract_items(data: Any, data_key: str | None) -> list[dict[str, Any]]:
    """Normalize Grafana's two list shapes into a flat list of records.

    Most list endpoints return a bare JSON array; the search-style endpoints
    (``/api/teams/search``, ``/api/serviceaccounts/search``) wrap it, e.g.
    ``{"teams": [...], "totalCount": N}``.
    """
    if data_key is not None:
        if isinstance(data, dict) and isinstance(data.get(data_key), list):
            return [item for item in data[data_key] if isinstance(item, dict)]
        return []
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def _permission_error_from_response(response: requests.Response) -> str:
    """Build a short scope message from a Grafana 403 body.

    Grafana names the missing scope, e.g. ``{"message": "You'll need additional permissions to
    perform this action. Permissions needed: teams:read"}`` — surface that instead of the raw body.
    """
    try:
        data = _read_json_bounded(response)
        message = data.get("message", "") if isinstance(data, dict) else ""
    except Exception:
        message = ""
    match = re.search(r"Permissions needed:\s*([\w:.*-]+)", message)
    if match:
        return f"Your Grafana credentials are missing the `{match.group(1)}` permission."
    return "Your Grafana credentials lack the permissions needed to access this data."


def _to_epoch_ms(value: Any) -> int:
    """Coerce an incremental cursor value into epoch milliseconds."""
    if isinstance(value, bool):
        return 0
    if isinstance(value, int | float):
        return int(value)
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return int(aware.timestamp() * 1000)
    if isinstance(value, date):
        return int(datetime.combine(value, datetime.min.time(), tzinfo=UTC).timestamp() * 1000)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


def _check_host(host: str, team_id: int) -> None:
    # Re-check at run time (not just source-create) in case the host was edited or now resolves to
    # an internal address (SSRF / DNS rebinding). Only enforced on cloud.
    host_ok, host_err = _is_host_safe(_hostname(host), team_id)
    if not host_ok:
        raise GrafanaHostNotAllowedError(host_err or HOST_NOT_ALLOWED_ERROR)


def _make_fetch(session: requests.Session, headers: dict[str, str], logger: FilteringBoundLogger):
    @retry(
        retry=retry_if_exception_type((GrafanaRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential_jitter(initial=1, max=30),
        reraise=True,
    )
    def fetch(url: str) -> Any:
        # Don't follow redirects: a customer-controlled host could 3xx to an internal address,
        # bypassing the host check (SSRF). stream=True keeps the body off the wire until the bounded
        # readers apply the size/time budget; the `with` releases the connection on every path.
        with session.get(
            url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS, allow_redirects=False, stream=True
        ) as response:
            if response.status_code == 429 or response.status_code >= 500:
                raise GrafanaRetryableError(f"Grafana API error (retryable): status={response.status_code}, url={url}")
            if response.is_redirect or response.is_permanent_redirect:
                raise GrafanaHostNotAllowedError(
                    f"Grafana API returned an unexpected redirect (status={response.status_code}); refusing to follow it"
                )
            if not response.ok:
                body = _read_body_bounded(response).decode("utf-8", "replace")
                logger.error(f"Grafana API error: status={response.status_code}, body={body}, url={url}")
                response.raise_for_status()

            return _read_json_bounded(response)

    return fetch


def validate_credentials(
    host: str,
    auth: GrafanaAuth,
    org_id: Optional[str] = None,
    team_id: Optional[int] = None,
    schema_name: Optional[str] = None,
) -> tuple[bool, str | None]:
    """Confirm the credentials are genuine with a cheap ``/api/org`` probe.

    The host is customer-controlled, so we block internal/private addresses (SSRF, cloud only)
    and refuse to follow redirects. A 403 means the token is genuine but under-scoped for the
    probe — let source creation through (per-endpoint scope is reported separately via
    ``get_endpoint_permissions``) and only fail when a specific ``schema_name`` is being checked.
    """
    if has_embedded_credentials(host):
        return False, (
            "Remove the username and password from the instance URL. Use the authentication method fields instead."
        )

    try:
        base_url = normalize_host(host)
    except Exception:
        return False, "Invalid Grafana host"

    hostname = _hostname(host)
    if not hostname or not re.match(r"^[A-Za-z0-9.\-]+$", hostname):
        return False, "Invalid Grafana host"

    if team_id is not None:
        host_ok, host_err = _is_host_safe(hostname, team_id)
        if not host_ok:
            return False, host_err or HOST_NOT_ALLOWED_ERROR

    try:
        headers = _resolve_auth_headers(auth, org_id)
    except GrafanaAuthError as e:
        return False, str(e)

    session = make_tracked_session(redact_values=_redact_values(auth))
    # stream=True so a hostile host can't buffer an unbounded probe body into the worker; the body
    # is only read (bounded) when a 403 needs its scope message.
    try:
        with session.get(
            f"{base_url}/api/org", headers=headers, timeout=10, allow_redirects=False, stream=True
        ) as response:
            if response.is_redirect or response.is_permanent_redirect:
                return False, HOST_NOT_ALLOWED_ERROR
            if response.status_code == 200:
                return True, None
            if response.status_code == 401:
                return False, "Invalid Grafana credentials"
            if response.status_code == 403:
                if schema_name is None:
                    return True, None
                return False, _permission_error_from_response(response)

            # The host responded but not in a way we recognise — often it isn't a Grafana instance
            # at all (e.g. a proxy or hosting-provider error page). Surface the status only; never
            # echo the raw response body, which can carry arbitrary upstream content.
            return (
                False,
                f"Grafana returned an unexpected response (HTTP {response.status_code}). "
                "Check that the instance URL points to your Grafana instance.",
            )
    except requests.exceptions.RequestException as e:
        return False, _connection_error_message(e)


def _probe_params(config: GrafanaEndpointConfig) -> dict[str, Any]:
    params: dict[str, Any] = {**config.params}
    if config.pagination == "page":
        params[config.page_size_param] = 1
        params["page"] = 1
    elif config.pagination == "time_window":
        params.update({"from": 0, "to": 1, "limit": 1})
    return params


def get_endpoint_permissions(
    host: str,
    auth: GrafanaAuth,
    org_id: Optional[str],
    team_id: int,
    endpoints: list[str],
) -> dict[str, str | None]:
    """Probe each endpoint with a minimal request; ``None`` when reachable, a short reason when
    the credentials lack its scope. Only a definitive denial (401/403) counts as unreachable —
    throttles, 5xx, and network blips must not mark a table as needing extra scopes."""
    base_url = normalize_host(host)
    headers = _resolve_auth_headers(auth, org_id)
    session = make_tracked_session(redact_values=_redact_values(auth))

    results: dict[str, str | None] = {}
    for endpoint in endpoints:
        config = GRAFANA_ENDPOINTS.get(endpoint)
        if config is None:
            results[endpoint] = None
            continue
        url = f"{base_url}{config.path}?{urlencode(_probe_params(config))}"
        try:
            # stream=True so a hostile host can't buffer an unbounded probe body; only a 403's scope
            # message is read (bounded) below.
            with session.get(url, headers=headers, timeout=10, allow_redirects=False, stream=True) as response:
                if response.status_code == 401:
                    results[endpoint] = "Your Grafana credentials are invalid or expired."
                elif response.status_code == 403:
                    results[endpoint] = _permission_error_from_response(response)
                else:
                    results[endpoint] = None
        except requests.exceptions.RequestException:
            results[endpoint] = None
            continue
    return results


def _get_paged_rows(
    fetch: Any,
    base_url: str,
    config: GrafanaEndpointConfig,
    resumable_source_manager: ResumableSourceManager[GrafanaResumeConfig],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page = resume.next_page if resume is not None and resume.next_page is not None else 1
    if page > 1:
        logger.debug(f"Grafana: resuming {config.name} from page {page}")

    while True:
        params = {**config.params, config.page_size_param: DEFAULT_PAGE_SIZE, "page": page}
        data = fetch(f"{base_url}{config.path}?{urlencode(params)}")
        items = _extract_items(data, config.data_key)

        if items:
            yield items

        if len(items) < DEFAULT_PAGE_SIZE:
            break

        page += 1
        # Save AFTER yielding so a crash re-yields the last page (merge dedupes on the primary
        # key) rather than skipping it.
        resumable_source_manager.save_state(GrafanaResumeConfig(next_page=page))


def _get_annotation_rows(
    fetch: Any,
    base_url: str,
    config: GrafanaEndpointConfig,
    resumable_source_manager: ResumableSourceManager[GrafanaResumeConfig],
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    """Walk ``/api/annotations`` in ascending epoch-ms windows, bisecting adaptively.

    The endpoint only exposes ``from``/``to``/``limit`` — no cursor — and on Grafana Cloud the
    ``limit`` semantics across its composite annotation store are unreliable, so a window is only
    trusted when it returns fewer rows than the limit; a saturated window is split in half until
    it fits (or bottoms out at MIN_ANNOTATION_WINDOW_MS, where truncation is logged). Starting
    from one [start, now] window means a sparse history costs a handful of requests while dense
    bursts get subdivided as needed.
    """
    now_ms = int(datetime.now(UTC).timestamp() * 1000)

    start_ms = 0
    if should_use_incremental_field and db_incremental_field_last_value is not None:
        # Inclusive lower bound: rows at exactly the watermark are re-fetched and deduped on merge.
        start_ms = max(0, _to_epoch_ms(db_incremental_field_last_value))

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.annotations_from_ms is not None:
        start_ms = max(start_ms, resume.annotations_from_ms)
        logger.debug(f"Grafana: resuming annotations from {start_ms}")

    if start_ms >= now_ms:
        return

    # LIFO stack of [from, to] windows with the oldest on top, so rows stream oldest-window-first
    # and the resume boundary only ever moves forward.
    windows: list[tuple[int, int]] = [(start_ms, now_ms)]
    while windows:
        window_from, window_to = windows.pop()
        params = {**config.params, "from": window_from, "to": window_to, "limit": ANNOTATIONS_LIMIT}
        items = _extract_items(fetch(f"{base_url}{config.path}?{urlencode(params)}"), config.data_key)

        if len(items) >= ANNOTATIONS_LIMIT:
            if window_to - window_from > MIN_ANNOTATION_WINDOW_MS:
                mid = (window_from + window_to) // 2
                # Halves share the `mid` boundary because from/to inclusivity isn't documented;
                # a row at exactly `mid` is fetched twice and deduped on merge rather than skipped.
                windows.append((mid, window_to))
                windows.append((window_from, mid))
                continue
            logger.warning(
                f"Grafana: annotations window [{window_from}, {window_to}] returned {len(items)} rows at the "
                f"response limit and can't be split further; some annotations in this window may be missing"
            )

        if items:
            yield items

        # Save AFTER yielding so a crash re-yields this window (merge dedupes on the primary key)
        # rather than skipping it. The stack is ascending, so everything before window_to is done.
        if windows:
            resumable_source_manager.save_state(GrafanaResumeConfig(annotations_from_ms=window_to))


def get_rows(
    host: str,
    auth: GrafanaAuth,
    org_id: Optional[str],
    endpoint: str,
    logger: FilteringBoundLogger,
    team_id: int,
    resumable_source_manager: ResumableSourceManager[GrafanaResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = GRAFANA_ENDPOINTS[endpoint]
    base_url = normalize_host(host)

    _check_host(host, team_id)

    headers = _resolve_auth_headers(auth, org_id)
    # One session reused across every page so urllib3 keeps the connection alive instead of
    # re-handshaking per request.
    session = make_tracked_session(redact_values=_redact_values(auth))
    fetch = _make_fetch(session, headers, logger)

    if config.pagination == "page":
        yield from _get_paged_rows(fetch, base_url, config, resumable_source_manager, logger)
    elif config.pagination == "time_window":
        yield from _get_annotation_rows(
            fetch,
            base_url,
            config,
            resumable_source_manager,
            logger,
            should_use_incremental_field,
            db_incremental_field_last_value,
        )
    else:
        url = f"{base_url}{config.path}"
        if config.params:
            url = f"{url}?{urlencode(config.params)}"
        items = _extract_items(fetch(url), config.data_key)
        if items:
            yield items


def grafana_source(
    host: str,
    auth: GrafanaAuth,
    org_id: Optional[str],
    endpoint: str,
    logger: FilteringBoundLogger,
    team_id: int,
    resumable_source_manager: ResumableSourceManager[GrafanaResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = GRAFANA_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            host=host,
            auth=auth,
            org_id=org_id,
            endpoint=endpoint,
            logger=logger,
            team_id=team_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        # Annotations stream oldest-window-first but rows inside each window arrive newest-first,
        # so the stream isn't globally ascending; "desc" defers the incremental watermark commit
        # to successful job end instead of corrupting it with per-batch checkpoints.
        sort_mode="desc" if config.pagination == "time_window" else "asc",
        partition_count=1,
        partition_size=1,
    )
