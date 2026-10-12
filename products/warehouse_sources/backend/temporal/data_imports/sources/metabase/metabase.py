import re
import dataclasses
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from typing import Any, Optional
from urllib.parse import urlparse

import requests
import structlog
from structlog.types import FilteringBoundLogger

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import _is_host_safe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.metabase.settings import (
    METABASE_ENDPOINTS,
    MetabaseEndpointConfig,
)

REQUEST_TIMEOUT_SECONDS = 60

# Metabase deletes query_execution rows older than `audit-max-retention-days` (720 by default), so a
# full refresh walks back this many months before the current one.
QUERY_EXECUTION_LOOKBACK_MONTHS = 24

HOST_NOT_ALLOWED_ERROR = "Metabase host is not allowed"

# Returned when the Instance URL responds with a 3xx. We refuse to follow redirects (an off-host
# 3xx is an SSRF vector), so a redirecting URL can never be probed. The raw HOST_NOT_ALLOWED_ERROR
# told the user nothing they could act on; this points them at the canonical instance URL.
REDIRECT_NOT_FOLLOWED_ERROR = (
    "Your Metabase instance redirected the connection, which PostHog doesn't follow. "
    "Enter the direct https:// URL of your Metabase instance, then reconnect."
)

# Stable substring matched by MetabaseSource.get_non_retryable_errors when the session endpoint
# returns a 2xx that isn't JSON (the Instance URL isn't a Metabase API).
SESSION_RESPONSE_NOT_JSON_ERROR = "Metabase session response was not valid JSON"

# Stable substring matched by MetabaseSource.get_non_retryable_errors when the query log endpoint is
# missing (open-source edition) or not licensed.
QUERY_LOGS_UNAVAILABLE_ERROR = "Metabase query execution logs are unavailable"

API_KEY_AUTH = "api_key"
SESSION_AUTH = "session"

# Loopback hosts where plaintext HTTP carries no network-exposure risk (local dev / self-hosted on the
# same box). Every other host is forced to HTTPS so credentials never traverse a network in cleartext.
LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


class MetabaseRetryableError(Exception):
    pass


class MetabaseHostNotAllowedError(Exception):
    pass


class MetabaseQueryLogsUnavailableError(Exception):
    pass


class MetabaseAuthError(Exception):
    """Raised when credentials are rejected (bad API key, or username/password that won't mint a
    session). Deterministic — retrying never fixes it — so it surfaces via get_non_retryable_errors."""

    pass


@dataclasses.dataclass(frozen=True)
class MetabaseResumeConfig:
    # The next yyyy-mm window of the query log walk.
    next_month: str


@frozen
class MetabaseAuth:
    # "api_key" sends a static X-API-Key header; "session" mints a short-lived token via
    # POST /api/session and sends it as X-Metabase-Session (for instances older than v0.47).
    method: str
    api_key: Optional[str] = dataclasses.field(default=None, repr=False)
    username: Optional[str] = None
    password: Optional[str] = dataclasses.field(default=None, repr=False)


def normalize_host(host: str) -> str:
    """Turn whatever the user typed into a bare instance base URL (scheme + host, no path).

    Accepts ``https://company.metabaseapp.com``, ``company.metabaseapp.com``,
    ``https://company.metabaseapp.com/api`` and returns ``https://company.metabaseapp.com``.
    Defaults to https when no scheme is given, and forces a plaintext ``http://`` host to
    ``https://`` so credentials are never sent over the network in cleartext — except for
    loopback hosts (local dev / self-hosted on the same box), which are left untouched.
    """
    host = host.strip()
    if not re.match(r"^https?://", host, flags=re.IGNORECASE):
        host = f"https://{host}"
    parsed = urlparse(host)
    scheme = parsed.scheme.lower()
    if scheme == "http" and (parsed.hostname or "").lower() not in LOOPBACK_HOSTS:
        scheme = "https"
    # Keep only scheme + host:port — urlparse drops any trailing path/slashes (e.g. "/api").
    return f"{scheme}://{parsed.netloc}"


def _hostname(host: str) -> str:
    return (urlparse(normalize_host(host)).hostname or "").lower()


def _redact_values_for_data_requests(auth: MetabaseAuth, headers: dict[str, str]) -> tuple[str, ...]:
    """Credential strings to value-mask in any captured data-request sample, on top of the
    name-based header/body scrubbers. Covers the static secret (API key, or username/password)
    plus the minted session token from ``headers`` — value-based defense-in-depth in case a
    credential ever echoes into a response body."""
    values: list[str] = []
    if auth.method == API_KEY_AUTH:
        if auth.api_key:
            values.append(auth.api_key)
    else:
        values.extend(v for v in (auth.username, auth.password) if v)
    token = headers.get("X-Metabase-Session")
    if token:
        values.append(token)
    return tuple(values)


def _resolve_auth_headers(base_url: str, auth: MetabaseAuth, logger: FilteringBoundLogger) -> dict[str, str]:
    """Build the auth header for every subsequent request.

    API-key auth is a static header. Session auth exchanges username/password for a token via
    POST /api/session and sends it as X-Metabase-Session. The token is minted per sync; Metabase
    session tokens expire (~14 days) so we never persist them.
    """
    if auth.method == API_KEY_AUTH:
        if not auth.api_key:
            raise MetabaseAuthError("Missing Metabase API key")
        return {"x-api-key": auth.api_key, "Accept": "application/json"}

    if not auth.username or not auth.password:
        raise MetabaseAuthError("Missing Metabase username or password")

    # Mint on a capture-disabled session: the request body carries the password and the response
    # body carries the freshly minted token under the generic key "id", neither of which the
    # name-based body scrubbers recognise. Excluding this one exchange from sample capture keeps
    # both out of any captured sample; every later request sends the token via the
    # X-Metabase-Session header, which is on the capture denylist.
    session = make_tracked_session(allow_redirects=False, capture=False)
    try:
        response = session.post(
            f"{base_url}/api/session",
            json={"username": auth.username, "password": auth.password},
            timeout=REQUEST_TIMEOUT_SECONDS,
            allow_redirects=False,
        )
    except requests.exceptions.RequestException as e:
        raise MetabaseRetryableError(f"Metabase session request failed: {e}") from e

    if response.status_code in (400, 401, 403):
        raise MetabaseAuthError("Invalid Metabase username or password")
    if response.status_code == 429 or response.status_code >= 500:
        raise MetabaseRetryableError(f"Metabase session error (retryable): status={response.status_code}")
    if not response.ok:
        # Unexpected non-auth status (e.g. 404 wrong path, 422). Surface as a typed retryable error
        # rather than letting raise_for_status() leak an HTTPError past callers' except clauses.
        logger.error(f"Metabase session error: status={response.status_code}, body={response.text}")
        raise MetabaseRetryableError(f"Metabase session error (retryable): status={response.status_code}")

    try:
        token = response.json().get("id")
    except requests.exceptions.JSONDecodeError as e:
        # A 2xx with a non-JSON body means the Instance URL isn't Metabase's session API (e.g. an
        # SSO/login page or a proxy). Deterministic, so surface it as a non-retryable auth error.
        # Keep the stable substring first so both the non-retryable classifier and validate_credentials
        # (which returns this message straight to the user) carry the guidance.
        raise MetabaseAuthError(
            f"{SESSION_RESPONSE_NOT_JSON_ERROR}. Check that the Instance URL points to your Metabase instance."
        ) from e
    if not token:
        raise MetabaseAuthError("Metabase session response did not contain a token")
    return {"X-Metabase-Session": token, "Accept": "application/json"}


def _connection_error_message(error: Exception) -> str:
    """Translate a low-level requests connection failure into a short, actionable message.

    requests surfaces these as host-revealing blobs (e.g. "HTTPSConnectionPool(host='<ip>',
    port=3000): ... SSLError(... WRONG_VERSION_NUMBER ...)"). Returning that verbatim leaks the
    customer's host/IP and tells them nothing they can act on.
    """
    # Match on the exception type first: substring checks against str(error) alone would misfire on
    # a hostname that happens to contain "ssl"/"timeout" (e.g. https://sslserver.com).
    text = str(error).lower()
    if isinstance(error, requests.exceptions.SSLError):
        if "wrong_version_number" in text:
            return (
                "Couldn't establish a secure (HTTPS) connection to your Metabase instance. "
                "PostHog connects over HTTPS, so the instance must be served over HTTPS. Check the Instance URL."
            )
        return (
            "Couldn't establish a secure (TLS) connection to your Metabase instance. "
            "Check that the Instance URL is correct and its TLS certificate is valid."
        )
    if isinstance(error, requests.exceptions.Timeout):
        return (
            "Connecting to your Metabase instance timed out. "
            "Check that the Instance URL is correct and reachable from the public internet."
        )
    if isinstance(error, requests.exceptions.ConnectionError) and (
        "name or service not known" in text or "nodename nor servname" in text or "failed to resolve" in text
    ):
        return (
            "Couldn't resolve the Metabase host. "
            "Check that the Instance URL is spelled correctly and reachable from the public internet."
        )
    return (
        "Couldn't connect to your Metabase instance. "
        "Check that the Instance URL is correct and reachable from the public internet."
    )


def validate_credentials(
    host: str, auth: MetabaseAuth, team_id: Optional[int] = None, schema_name: Optional[str] = None
) -> tuple[bool, str | None]:
    """Confirm the credentials are genuine with a cheap ``/api/user/current`` probe.

    ``schema_name`` is unused here (every endpoint shares one instance-wide auth), but kept for the
    base-class signature. The host is customer-controlled, so we block internal/private addresses
    (SSRF, cloud only) and refuse to follow redirects.
    """
    try:
        base_url = normalize_host(host)
    except Exception:
        return False, "Invalid Metabase host"

    hostname = _hostname(host)
    if not hostname or not re.match(r"^[A-Za-z0-9.\-]+$", hostname):
        return False, "Invalid Metabase host"

    if team_id is not None:
        host_ok, host_err = _is_host_safe(hostname, team_id)
        if not host_ok:
            return False, host_err or HOST_NOT_ALLOWED_ERROR

    try:
        headers = _resolve_auth_headers(base_url, auth, structlog.get_logger())
    except (MetabaseAuthError, MetabaseRetryableError) as e:
        return False, str(e)

    session = make_tracked_session(redact_values=_redact_values_for_data_requests(auth, headers))
    try:
        response = session.get(f"{base_url}/api/user/current", headers=headers, timeout=10, allow_redirects=False)
    except requests.exceptions.RequestException as e:
        return False, _connection_error_message(e)

    if response.is_redirect or response.is_permanent_redirect:
        return False, REDIRECT_NOT_FOLLOWED_ERROR
    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return False, "Invalid Metabase credentials"
    if response.status_code == 403:
        # Valid credentials, missing permission for this probe — let source creation through.
        if schema_name is None:
            return True, None
        return False, "Metabase credentials lack the required permissions"

    # Any other status: the host responded but not in a way we recognise — often it isn't a
    # Metabase instance at all (e.g. a proxy or hosting-provider error page). Surface the status
    # only; never echo the raw response body, which can carry arbitrary upstream content.
    return (
        False,
        f"Metabase returned an unexpected response (HTTP {response.status_code}). "
        "Check that the Instance URL points to your Metabase instance.",
    )


def _parse_timestamp(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
    else:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def query_execution_months(now: datetime, last_value: Any) -> list[str]:
    """The yyyy-mm windows to fetch, oldest first, ending with the month of ``now``.

    Metabase buckets rows by month in its application database's timezone, so an incremental run
    starts one month before the watermark's UTC month to cover rows across that boundary.
    """
    watermark = _parse_timestamp(last_value)
    if watermark is None:
        year, month = _shift_month(now.year, now.month, -QUERY_EXECUTION_LOOKBACK_MONTHS)
    else:
        year, month = _shift_month(watermark.year, watermark.month, -1)

    months: list[str] = []
    while (year, month) <= (now.year, now.month):
        months.append(f"{year:04d}-{month:02d}")
        year, month = _shift_month(year, month, 1)
    return months


def _started_at_sort_key(row: dict[str, Any]) -> datetime:
    return _parse_timestamp(row.get("started_at")) or datetime.min.replace(tzinfo=UTC)


def _list_pages(
    client_config: ClientConfig, config: MetabaseEndpointConfig, path: str, team_id: int, job_id: str
) -> Iterable[Any]:
    endpoint_config: Endpoint = {"path": path, "params": dict(config.params)}
    if config.data_selector:
        endpoint_config["data_selector"] = config.data_selector

    rest_config: RESTAPIConfig = {
        "client": client_config,
        "resource_defaults": {},
        "resources": [{"name": config.name, "endpoint": endpoint_config}],
    }
    return rest_api_resource(rest_config, team_id, job_id, None)


def _get_query_execution_rows(
    client_config: ClientConfig,
    config: MetabaseEndpointConfig,
    team_id: int,
    job_id: str,
    db_incremental_field_last_value: Any,
    resumable_source_manager: ResumableSourceManager[MetabaseResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    watermark = _parse_timestamp(db_incremental_field_last_value)
    months = query_execution_months(datetime.now(UTC), db_incremental_field_last_value)
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.next_month in months:
        months = months[months.index(resume.next_month) :]

    for index, month in enumerate(months):
        path = config.path.replace("{month}", month)
        try:
            rows = [row for page in _list_pages(client_config, config, path, team_id, job_id) for row in page]
        except requests.exceptions.HTTPError as e:
            # The route only exists on Pro/Enterprise builds, and an unlicensed instance refuses it.
            if e.response is not None and e.response.status_code in (402, 404):
                raise MetabaseQueryLogsUnavailableError(QUERY_LOGS_UNAVAILABLE_ERROR) from e
            raise

        if watermark is not None:
            rows = [row for row in rows if _started_at_sort_key(row) >= watermark]
        # Metabase returns each month newest first; ascending order keeps the incremental watermark
        # monotonic across months.
        rows.sort(key=_started_at_sort_key)
        if index + 1 < len(months):
            resumable_source_manager.save_state(MetabaseResumeConfig(next_month=months[index + 1]))
        if rows:
            yield rows
        else:
            resumable_source_manager.safe_point()


def _flatten_grouped_rows(pages: Iterable[Any]) -> Iterator[list[dict[str, Any]]]:
    for page in pages:
        rows = [row for group in page for rows_for_key in group.values() for row in rows_for_key]
        if rows:
            yield rows


def get_rows(
    host: str,
    auth: MetabaseAuth,
    endpoint: str,
    logger: FilteringBoundLogger,
    team_id: int,
    resumable_source_manager: ResumableSourceManager[MetabaseResumeConfig],
    job_id: str = "",
    db_incremental_field_last_value: Any = None,
) -> Iterator[Any]:
    config = METABASE_ENDPOINTS[endpoint]
    base_url = normalize_host(host)

    # Re-check at run time (not just source-create) in case the host was edited or now resolves to
    # an internal address (SSRF / DNS rebinding). Only enforced on cloud.
    host_ok, host_err = _is_host_safe(_hostname(host), team_id)
    if not host_ok:
        raise MetabaseHostNotAllowedError(host_err or HOST_NOT_ALLOWED_ERROR)

    # Resolve auth once (session auth mints a short-lived token here via one POST /api/session).
    # The secret rides in a header via the framework auth config so it's scrubbed from any raised
    # error; the tracked session's value redaction covers it (and the creds/token) in logs/samples.
    headers = _resolve_auth_headers(base_url, auth, logger)
    if "x-api-key" in headers:
        auth_header_name, secret = "x-api-key", headers["x-api-key"]
    else:
        auth_header_name, secret = "X-Metabase-Session", headers["X-Metabase-Session"]

    session = make_tracked_session(redact_values=_redact_values_for_data_requests(auth, headers))

    client_config: ClientConfig = {
        "base_url": base_url,
        "headers": {"Accept": "application/json"},
        "auth": {"type": "api_key", "name": auth_header_name, "api_key": secret, "location": "header"},
        # Metabase list endpoints are unpaginated — one request returns the whole collection.
        "paginator": SinglePagePaginator(),
        # A pre-built tracked session carries the value redaction; disabling redirects rejects a
        # customer-controlled host that 3xx-es toward an internal address (SSRF).
        "session": session,
        "allow_redirects": False,
    }

    if config.fanout is not None:
        parent = METABASE_ENDPOINTS[config.fanout.parent_name]
        yield from build_dependent_resource(
            endpoint_configs=METABASE_ENDPOINTS,
            child_endpoint=endpoint,
            fanout=config.fanout,
            client_config=client_config,
            path_format_values={},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=None,
            parent_endpoint_extra={"data_selector": parent.data_selector} if parent.data_selector else None,
            page_size_param=None,
        )
    elif config.month_windowed:
        yield from _get_query_execution_rows(
            client_config, config, team_id, job_id, db_incremental_field_last_value, resumable_source_manager
        )
    elif config.grouped_by_key:
        yield from _flatten_grouped_rows(_list_pages(client_config, config, config.path, team_id, job_id))
    else:
        yield from _list_pages(client_config, config, config.path, team_id, job_id)


def metabase_source(
    host: str,
    auth: MetabaseAuth,
    endpoint: str,
    logger: FilteringBoundLogger,
    team_id: int,
    resumable_source_manager: ResumableSourceManager[MetabaseResumeConfig],
    job_id: str = "",
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> SourceResponse:
    config: MetabaseEndpointConfig = METABASE_ENDPOINTS[endpoint]
    last_value = db_incremental_field_last_value if should_use_incremental_field else None

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            host=host,
            auth=auth,
            endpoint=endpoint,
            logger=logger,
            team_id=team_id,
            resumable_source_manager=resumable_source_manager,
            job_id=job_id,
            db_incremental_field_last_value=last_value,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
