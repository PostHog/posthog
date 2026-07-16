import re
import time
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import quote, urlencode, urlparse

import requests
import structlog
from structlog.types import FilteringBoundLogger
from tenacity import RetryCallState, retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import _is_host_safe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.infisical.settings import (
    INFISICAL_ENDPOINTS,
    InfisicalEndpointConfig,
)

DEFAULT_BASE_URL = "https://app.infisical.com"
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 5
MAX_RETRY_AFTER_SECONDS = 60
# Re-login this many seconds before the access token's advertised expiry, so a token can't
# lapse between the check and the request during a long sync.
TOKEN_EXPIRY_MARGIN_SECONDS = 60
# base_url points at a customer-controlled host, so cap what a single response may buffer into
# memory and how many pages a paginating loop may fetch — a hostile or misbehaving server can
# otherwise stream an unbounded (chunked) body or hand back full pages forever and exhaust the
# import worker. Both bounds are far above any legitimate Infisical response.
MAX_RESPONSE_BYTES = 128 * 1024 * 1024
RESPONSE_CHUNK_BYTES = 1024 * 1024
MAX_PAGES = 100_000
# Cap how much of an error response body reaches the logs — the host is untrusted.
ERROR_BODY_LOG_LIMIT = 500

HOST_NOT_ALLOWED_ERROR = "Infisical host is not allowed"
INVALID_CREDENTIALS_ERROR = "Invalid Infisical machine identity credentials"

module_logger = structlog.get_logger(__name__)


class InfisicalRetryableError(Exception):
    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class InfisicalHostNotAllowedError(Exception):
    pass


class InfisicalResponseTooLargeError(Exception):
    pass


class InfisicalAuthError(Exception):
    pass


@dataclasses.dataclass
class InfisicalResumeConfig:
    # Offset of the next unfetched page within the (window_start, window_end) query.
    offset: int = 0
    # Audit-log time window pinned at sync start. Pinning end_date keeps offset pagination
    # stable while new logs keep arriving at the top of the (newest-first) result set.
    window_start: str | None = None
    window_end: str | None = None


def normalize_base_url(base_url: str) -> str:
    """Turn whatever the user typed into ``https://<host>[:port]``.

    Accepts values like ``app.infisical.com``, ``https://eu.infisical.com/``, or a
    self-hosted URL with a stray path. Always https — machine identity secrets must
    never travel in plaintext.
    """
    value = base_url.strip()
    if not re.match(r"^https?://", value, flags=re.IGNORECASE):
        value = f"https://{value}"
    parsed = urlparse(value)
    host = (parsed.hostname or "").strip().lower()
    if not host or not re.match(r"^[a-z0-9.\-]+$", host):
        raise ValueError("Invalid Infisical base URL")
    port = f":{parsed.port}" if parsed.port else ""
    return f"https://{host}{port}"


def _format_datetime_z(dt: datetime) -> str:
    utc_dt = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    return utc_dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _format_incremental_value(value: Any) -> str:
    if isinstance(value, datetime):
        return _format_datetime_z(value)
    if isinstance(value, date):
        return _format_datetime_z(datetime.combine(value, datetime.min.time(), tzinfo=UTC))
    return str(value)


def _format_path(path: str, organization_id: str) -> str:
    # quote() with safe="" also encodes slashes, so a malformed org ID can't traverse the path.
    return path.replace("{organization_id}", quote(organization_id, safe=""))


def _parse_retry_after(response: requests.Response) -> float | None:
    """Infisical sends ``Retry-After`` in whole seconds on 429. Ignore HTTP-date forms."""
    raw = response.headers.get("Retry-After")
    if raw and raw.strip().isdigit():
        return min(float(raw.strip()), MAX_RETRY_AFTER_SECONDS)
    return None


def _retry_wait(retry_state: RetryCallState) -> float:
    """Honor a server-provided Retry-After when present, else exponential backoff."""
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    if isinstance(exc, InfisicalRetryableError) and exc.retry_after is not None:
        return exc.retry_after
    return wait_exponential_jitter(initial=1, max=30)(retry_state)


@retry(
    retry=retry_if_exception_type(
        (
            InfisicalRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(MAX_RETRIES),
    wait=_retry_wait,
    reraise=True,
)
def _read_capped_body(response: requests.Response) -> None:
    """Buffer a streamed response body into memory under ``MAX_RESPONSE_BYTES``.

    Aborts (closing the connection) once the cap is crossed rather than letting a hostile or
    misbehaving host stream an unbounded chunked body and exhaust the worker. Pins the bytes
    onto the response so downstream ``.json()`` / ``.text`` keep working.
    """
    total = 0
    chunks: list[bytes] = []
    for chunk in response.iter_content(chunk_size=RESPONSE_CHUNK_BYTES):
        if not chunk:
            continue
        total += len(chunk)
        if total > MAX_RESPONSE_BYTES:
            response.close()
            raise InfisicalResponseTooLargeError(
                f"Infisical response exceeded {MAX_RESPONSE_BYTES} bytes; refusing to buffer it"
            )
        chunks.append(chunk)
    # Setting _content to real bytes short-circuits Response.content, so downstream
    # .json()/.text return this buffer instead of re-reading the consumed stream.
    response._content = b"".join(chunks)


def _send(
    session: requests.Session,
    method: str,
    url: str,
    logger: FilteringBoundLogger,
    headers: dict[str, str] | None = None,
    json_body: dict[str, Any] | None = None,
) -> requests.Response:
    # Don't follow redirects: the base URL is customer-controlled, so a 3xx could point at an
    # internal address and defeat the host validation done before the request (SSRF).
    # stream=True keeps the body unread until _read_capped_body enforces the size cap below.
    response = session.request(
        method,
        url,
        headers=headers,
        json=json_body,
        timeout=REQUEST_TIMEOUT_SECONDS,
        allow_redirects=False,
        stream=True,
    )

    if response.status_code == 429 or response.status_code >= 500:
        retry_after = _parse_retry_after(response) if response.status_code == 429 else None
        response.close()
        raise InfisicalRetryableError(
            f"Infisical API error (retryable): status={response.status_code}, url={url}",
            retry_after=retry_after,
        )

    # A 3xx isn't an error status (`response.ok` is True), so reject it explicitly rather than
    # silently parsing the redirect body as data.
    if response.is_redirect or response.is_permanent_redirect:
        response.close()
        raise InfisicalHostNotAllowedError(
            f"Infisical API returned an unexpected redirect (status={response.status_code}); refusing to follow it"
        )

    _read_capped_body(response)

    if not response.ok:
        logger.error(
            f"Infisical API error: status={response.status_code}, body={response.text[:ERROR_BODY_LOG_LIMIT]}, url={url}"
        )
        response.raise_for_status()

    return response


class InfisicalClient:
    """Minimal Universal Auth client: exchanges the machine identity's client ID/secret for a
    short-lived bearer token and re-logins when the token nears expiry (or is rejected)."""

    def __init__(self, base_url: str, client_id: str, client_secret: str, logger: FilteringBoundLogger) -> None:
        self._base_url = normalize_base_url(base_url)
        self._client_id = client_id
        self._client_secret = client_secret
        self._logger = logger
        # capture=False on both sessions. HTTP sample capture reads response.text inside the
        # tracked adapter's send() — before _send's _read_capped_body runs — so an armed
        # capture rule would buffer an unbounded body from the customer-controlled host and
        # defeat the size cap. The auth exchange additionally carries the client secret and
        # minted accessToken in camelCase fields the name-based scrubbers don't recognise.
        # One session reused across every request so urllib3 keeps the connection alive.
        self._session = make_tracked_session(redact_values=(client_secret,), capture=False)
        self._auth_session = make_tracked_session(redact_values=(client_secret,), capture=False)
        self._access_token: str | None = None
        self._token_refresh_at: float = 0.0

    @property
    def base_url(self) -> str:
        return self._base_url

    def ensure_token(self) -> str:
        if self._access_token is not None and time.monotonic() < self._token_refresh_at:
            return self._access_token

        try:
            response = _send(
                self._auth_session,
                "post",
                f"{self._base_url}/api/v1/auth/universal-auth/login",
                self._logger,
                headers={"Accept": "application/json"},
                json_body={"clientId": self._client_id, "clientSecret": self._client_secret},
            )
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status in (400, 401, 403):
                raise InfisicalAuthError(INVALID_CREDENTIALS_ERROR) from exc
            raise

        data = response.json()
        self._access_token = data["accessToken"]
        expires_in = float(data.get("expiresIn") or 0)
        # expiresIn <= margin (including a non-expiring token reported as 0) falls back to a
        # periodic hourly re-login, which is always safe.
        refresh_after = expires_in - TOKEN_EXPIRY_MARGIN_SECONDS
        if refresh_after <= 0:
            refresh_after = 3600
        self._token_refresh_at = time.monotonic() + refresh_after
        return self._access_token

    def get(self, path: str, params: dict[str, Any] | None = None) -> requests.Response:
        url = f"{self._base_url}{path}"
        if params:
            url = f"{url}?{urlencode(params)}"

        token = self.ensure_token()
        try:
            return self._get(url, token)
        except requests.HTTPError as exc:
            # A 401 mid-sync usually means the token was revoked/expired server-side earlier
            # than advertised — re-login once before giving up.
            if exc.response is not None and exc.response.status_code == 401:
                self._access_token = None
                return self._get(url, self.ensure_token())
            raise

    def _get(self, url: str, token: str) -> requests.Response:
        return _send(
            self._session,
            "get",
            url,
            self._logger,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )


def validate_credentials(
    base_url: str,
    client_id: str,
    client_secret: str,
    organization_id: str,
    schema_name: Optional[str] = None,
    team_id: Optional[int] = None,
) -> tuple[bool, str | None]:
    """Exchange the machine identity credentials for a token to confirm they are genuine.

    At source-create (``schema_name is None``) a successful login is enough — per-endpoint
    permissions are granted separately in Infisical and users may only scope the identity to
    the tables they want. A scoped probe (``schema_name`` set) also hits that endpoint and
    treats 403 as a hard failure.
    """
    try:
        normalized = normalize_base_url(base_url)
    except ValueError:
        return False, "Invalid Infisical base URL"

    if not re.match(r"^[A-Za-z0-9\-]+$", organization_id.strip()):
        return False, "Invalid Infisical organization ID"

    # The base URL is fully customer-controlled, so block hosts that resolve to private/
    # internal addresses (SSRF). Only enforced on cloud — see _is_host_safe.
    if team_id is not None:
        host_ok, host_err = _is_host_safe(urlparse(normalized).hostname or "", team_id)
        if not host_ok:
            return False, host_err or HOST_NOT_ALLOWED_ERROR

    client = InfisicalClient(normalized, client_id, client_secret, module_logger)
    try:
        client.ensure_token()
    except InfisicalAuthError as exc:
        return False, str(exc)
    except InfisicalHostNotAllowedError:
        return False, HOST_NOT_ALLOWED_ERROR
    except requests.RequestException as exc:
        return False, str(exc)

    if schema_name is None:
        return True, None

    config = INFISICAL_ENDPOINTS.get(schema_name)
    if config is None:
        return False, f"Unknown Infisical table: {schema_name}"

    # The fan-out endpoint's per-project scopes can't be probed cheaply, so probe the
    # project list it iterates instead.
    path = "/api/v1/projects" if config.fan_out_over_projects else _format_path(config.path, organization_id.strip())
    params: dict[str, Any] = {"limit": 1, "offset": 0} if config.paginated else {}
    try:
        client.get(path, params)
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else None
        if status == 401:
            return False, INVALID_CREDENTIALS_ERROR
        if status == 403:
            return False, f"Your Infisical machine identity lacks permission to read {schema_name}"
        return False, str(exc)
    except InfisicalHostNotAllowedError:
        return False, HOST_NOT_ALLOWED_ERROR
    except requests.RequestException as exc:
        return False, str(exc)

    return True, None


def _get_audit_log_rows(
    client: InfisicalClient,
    config: InfisicalEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[InfisicalResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    """Page through the org audit log newest-first within a pinned time window.

    The endpoint has no sort param and returns rows newest-first, so the window's endDate is
    pinned at sync start: logs arriving mid-sync land before the window and can't shift rows
    across page boundaries. Incremental runs set startDate to the createdAt watermark
    (inclusive — the boundary row is re-pulled and deduped on the primary key).
    """
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.window_end:
        offset = resume.offset
        window_start = resume.window_start
        window_end = resume.window_end
        logger.debug(f"Infisical: resuming audit_logs at offset={offset}, window_end={window_end}")
    else:
        offset = 0
        window_end = _format_datetime_z(datetime.now(UTC))
        window_start = (
            _format_incremental_value(db_incremental_field_last_value)
            if should_use_incremental_field and db_incremental_field_last_value
            else None
        )

    for page in range(MAX_PAGES):
        params: dict[str, Any] = {"limit": config.page_limit, "offset": offset, "endDate": window_end}
        if window_start:
            params["startDate"] = window_start

        rows = client.get(config.path, params).json().get(config.data_key) or []
        if not rows:
            break

        yield rows

        offset += len(rows)
        # Save AFTER yielding so a crash re-yields the last page rather than skipping it —
        # merge dedupes on the primary key.
        resumable_source_manager.save_state(
            InfisicalResumeConfig(offset=offset, window_start=window_start, window_end=window_end)
        )

        if len(rows) < config.page_limit:
            break

        if page == MAX_PAGES - 1:
            logger.warning(f"Infisical: hit MAX_PAGES={MAX_PAGES} for audit_logs, stopping pagination")


def _get_offset_paginated_rows(
    client: InfisicalClient,
    config: InfisicalEndpointConfig,
    organization_id: str,
    resumable_source_manager: ResumableSourceManager[InfisicalResumeConfig],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    path = _format_path(config.path, organization_id)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    offset = resume.offset if resume is not None else 0
    if offset:
        logger.debug(f"Infisical: resuming {config.name} at offset={offset}")

    for page in range(MAX_PAGES):
        params: dict[str, Any] = {"limit": config.page_limit, "offset": offset, **config.extra_params}
        rows = client.get(path, params).json().get(config.data_key) or []
        if not rows:
            break

        yield rows

        offset += len(rows)
        resumable_source_manager.save_state(InfisicalResumeConfig(offset=offset))

        if len(rows) < config.page_limit:
            break

        if page == MAX_PAGES - 1:
            logger.warning(f"Infisical: hit MAX_PAGES={MAX_PAGES} for {config.name}, stopping pagination")


def _get_project_fan_out_rows(
    client: InfisicalClient,
    config: InfisicalEndpointConfig,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    projects = client.get("/api/v1/projects").json().get("projects") or []

    for project in projects:
        project_id = project.get("id")
        if not project_id:
            continue

        path = config.path.replace("{project_id}", quote(str(project_id), safe=""))
        try:
            rows = client.get(path).json().get(config.data_key) or []
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            # The machine identity's project grants are per-project, and a project can be
            # deleted between enumeration and this fetch. Skip rather than failing the sync.
            if status in (403, 404):
                logger.warning(f"Infisical: skipping project {project_id} {config.name} (status={status})")
                continue
            raise

        if rows:
            yield rows


def get_rows(
    base_url: str,
    client_id: str,
    client_secret: str,
    organization_id: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[InfisicalResumeConfig],
    team_id: int,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = INFISICAL_ENDPOINTS[endpoint]
    normalized = normalize_base_url(base_url)

    # Re-check at run time (not just at source-create) in case the base URL was edited or now
    # resolves to an internal address (SSRF / DNS rebinding). Only enforced on cloud.
    host_ok, host_err = _is_host_safe(urlparse(normalized).hostname or "", team_id)
    if not host_ok:
        raise InfisicalHostNotAllowedError(host_err or HOST_NOT_ALLOWED_ERROR)

    client = InfisicalClient(normalized, client_id, client_secret, logger)
    organization_id = organization_id.strip()

    if config.fan_out_over_projects:
        yield from _get_project_fan_out_rows(client, config, logger)
        return

    if endpoint == "audit_logs":
        yield from _get_audit_log_rows(
            client,
            config,
            logger,
            resumable_source_manager,
            should_use_incremental_field,
            db_incremental_field_last_value,
        )
        return

    if config.paginated:
        yield from _get_offset_paginated_rows(client, config, organization_id, resumable_source_manager, logger)
        return

    rows = client.get(_format_path(config.path, organization_id)).json().get(config.data_key) or []
    if rows:
        yield rows


def infisical_source(
    base_url: str,
    client_id: str,
    client_secret: str,
    organization_id: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[InfisicalResumeConfig],
    team_id: int,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    endpoint_config = INFISICAL_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            base_url=base_url,
            client_id=client_id,
            client_secret=client_secret,
            organization_id=organization_id,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            team_id=team_id,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=[endpoint_config.primary_key],
        # The audit log has no sort param and returns newest-first (verified against the
        # open-source server, which orders by createdAt DESC), so desc — the pipeline then
        # persists the incremental watermark only at successful job end. Every incremental
        # run covers the full [watermark, sync-start] window in one job, so no
        # earliest-value backscroll is needed. The other endpoints are full refresh, where
        # ordering doesn't affect correctness.
        sort_mode="desc" if endpoint == "audit_logs" else "asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="week" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )
