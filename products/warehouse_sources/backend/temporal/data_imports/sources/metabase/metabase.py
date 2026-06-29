import re
import dataclasses
from collections.abc import Iterator
from typing import Any, Optional
from urllib.parse import urlencode, urlparse

import requests
import structlog
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import _is_host_safe
from products.warehouse_sources.backend.temporal.data_imports.sources.metabase.settings import (
    METABASE_ENDPOINTS,
    MetabaseEndpointConfig,
)

REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 5

HOST_NOT_ALLOWED_ERROR = "Metabase host is not allowed"

API_KEY_AUTH = "api_key"
SESSION_AUTH = "session"

# Loopback hosts where plaintext HTTP carries no network-exposure risk (local dev / self-hosted on the
# same box). Every other host is forced to HTTPS so credentials never traverse a network in cleartext.
LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


class MetabaseRetryableError(Exception):
    pass


class MetabaseHostNotAllowedError(Exception):
    pass


class MetabaseAuthError(Exception):
    """Raised when credentials are rejected (bad API key, or username/password that won't mint a
    session). Deterministic — retrying never fixes it — so it surfaces via get_non_retryable_errors."""

    pass


@dataclasses.dataclass
class MetabaseAuth:
    # "api_key" sends a static X-API-Key header; "session" mints a short-lived token via
    # POST /api/session and sends it as X-Metabase-Session (for instances older than v0.47).
    method: str
    api_key: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None


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

    token = response.json().get("id")
    if not token:
        raise MetabaseAuthError("Metabase session response did not contain a token")
    return {"X-Metabase-Session": token, "Accept": "application/json"}


def _extract_items(data: Any) -> list[dict[str, Any]]:
    """Normalize Metabase's two list shapes into a flat list of records.

    Some endpoints (``/api/card``, ``/api/dashboard``, ``/api/collection``) return a bare JSON
    array; others (``/api/database``, ``/api/user``) wrap it as ``{"data": [...], "total": N}``.
    """
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict) and isinstance(data.get("data"), list):
        return [item for item in data["data"] if isinstance(item, dict)]
    return []


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
        return False, str(e)

    if response.is_redirect or response.is_permanent_redirect:
        return False, HOST_NOT_ALLOWED_ERROR
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


def get_rows(
    host: str,
    auth: MetabaseAuth,
    endpoint: str,
    logger: FilteringBoundLogger,
    team_id: int,
) -> Iterator[list[dict[str, Any]]]:
    config = METABASE_ENDPOINTS[endpoint]
    base_url = normalize_host(host)

    # Re-check at run time (not just source-create) in case the host was edited or now resolves to
    # an internal address (SSRF / DNS rebinding). Only enforced on cloud.
    host_ok, host_err = _is_host_safe(_hostname(host), team_id)
    if not host_ok:
        raise MetabaseHostNotAllowedError(host_err or HOST_NOT_ALLOWED_ERROR)

    headers = _resolve_auth_headers(base_url, auth, logger)
    session = make_tracked_session(redact_values=_redact_values_for_data_requests(auth, headers))

    url = f"{base_url}{config.path}"
    if config.params:
        url = f"{url}?{urlencode(config.params)}"

    @retry(
        retry=retry_if_exception_type((MetabaseRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential_jitter(initial=1, max=30),
        reraise=True,
    )
    def fetch(page_url: str) -> requests.Response:
        # Don't follow redirects: a customer-controlled host could 3xx to an internal address,
        # bypassing the host check above (SSRF).
        response = session.get(page_url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS, allow_redirects=False)

        if response.status_code == 429 or response.status_code >= 500:
            raise MetabaseRetryableError(
                f"Metabase API error (retryable): status={response.status_code}, url={page_url}"
            )
        if response.is_redirect or response.is_permanent_redirect:
            raise MetabaseHostNotAllowedError(
                f"Metabase API returned an unexpected redirect (status={response.status_code}); refusing to follow it"
            )
        if not response.ok:
            logger.error(f"Metabase API error: status={response.status_code}, body={response.text}, url={page_url}")
            response.raise_for_status()

        return response

    # Metabase list endpoints are unpaginated — one request returns the whole collection.
    response = fetch(url)
    items = _extract_items(response.json())
    if items:
        yield items


def metabase_source(
    host: str,
    auth: MetabaseAuth,
    endpoint: str,
    logger: FilteringBoundLogger,
    team_id: int,
) -> SourceResponse:
    config: MetabaseEndpointConfig = METABASE_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(host=host, auth=auth, endpoint=endpoint, logger=logger, team_id=team_id),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
