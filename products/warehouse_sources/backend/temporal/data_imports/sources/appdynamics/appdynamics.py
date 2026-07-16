import json
import time
import dataclasses
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlparse

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter
from urllib3.util.retry import Retry

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.appdynamics.settings import (
    APPDYNAMICS_ENDPOINTS,
    APPLICATIONS_PATH,
    AppdynamicsEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import _is_host_safe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

REQUEST_TIMEOUT = 60
MAX_RETRY_ATTEMPTS = 5
# The controller host is user-supplied, so a hostile or misbehaving controller could stream
# an unbounded or slowly-trickled body. `requests`' read timeout only limits idle gaps between
# reads, not total size or duration, so cap both: no single response may buffer more than this
# many bytes or take longer than the wall-clock budget to download.
MAX_RESPONSE_BYTES = 256 * 1024 * 1024
MAX_DOWNLOAD_SECONDS = 120
RESPONSE_CHUNK_SIZE = 1024 * 1024
# Controller OAuth tokens default to a ~5 minute TTL (configurable per controller);
# refresh well before expiry so a request never rides a token that dies mid-flight.
TOKEN_REFRESH_MARGIN_SECONDS = 60
MILLIS_PER_DAY = 24 * 60 * 60 * 1000

OAUTH_FAILED_MESSAGE = (
    "AppDynamics OAuth token request failed. Check your API client name, client secret, and account name."
)


class AppdynamicsRetryableError(Exception):
    pass


class AppdynamicsError(Exception):
    """Non-retryable AppDynamics transport error (bad credentials, unexpected redirect)."""


@dataclasses.dataclass
class AppdynamicsResumeConfig:
    # Fan-out bookmark: the application currently being processed. A stable application-ID
    # bookmark (not a positional index) so applications added/removed between a crash and
    # the retry can't resume us into the wrong application. None for `applications` itself.
    application_id: int | None = None
    # For time-windowed endpoints: epoch-ms start of the next unprocessed window within
    # the bookmarked application.
    window_start: int | None = None


@dataclasses.dataclass
class AppdynamicsAuth:
    """Resolved credentials for a single sync. Exactly one auth style is populated."""

    account_name: str
    api_client_name: Optional[str] = None
    api_client_secret: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None

    @property
    def uses_oauth(self) -> bool:
        return bool(self.api_client_name)


def normalize_host(host: str) -> str:
    """Accept a bare account name, host, or full URL and return `https://<host>[:port]`.

    Forces HTTPS and strips any path, query, fragment, or userinfo so only the host (and
    optional port) survive. This keeps the value safe to feed into the SSRF host check and
    to build Controller API paths against.

    Examples: ``mycompany`` -> ``https://mycompany.saas.appdynamics.com``;
    ``https://acme.saas.appdynamics.com/controller`` -> ``https://acme.saas.appdynamics.com``.
    """
    value = (host or "").strip().rstrip("/")
    if not value:
        raise ValueError("AppDynamics controller URL is required")

    # A bare account name (no scheme, no dot) expands to the standard SaaS controller domain.
    if "://" not in value and "." not in value:
        return f"https://{value}.saas.appdynamics.com"

    if "://" not in value:
        value = f"https://{value}"

    parsed = urlparse(value)
    hostname = parsed.hostname
    if not hostname:
        raise ValueError("Invalid AppDynamics controller URL")

    netloc = f"{hostname}:{parsed.port}" if parsed.port else hostname
    return f"https://{netloc}"


def _resolve_base_url(host: str, team_id: int) -> str:
    """Normalize the controller URL and reject internal/private hosts (SSRF guard).

    ``_is_host_safe`` is a no-op outside of PostHog Cloud, so self-hosted instances can
    still reach any host (e.g. an on-premises controller).
    """
    base_url = normalize_host(host)
    hostname = urlparse(base_url).hostname or ""
    is_safe, error = _is_host_safe(hostname, team_id)
    if not is_safe:
        raise ValueError(error or "AppDynamics controller host is not allowed.")
    return base_url


def _fetch_oauth_token(session: requests.Session, base_url: str, auth: AppdynamicsAuth) -> tuple[str, int]:
    """Exchange the API client credentials for a short-lived bearer token.

    Returns ``(access_token, expires_in_seconds)``.
    """
    response = session.post(
        f"{base_url}/controller/api/oauth/access_token",
        data={
            "grant_type": "client_credentials",
            "client_id": f"{auth.api_client_name}@{auth.account_name}",
            "client_secret": auth.api_client_secret,
        },
        timeout=REQUEST_TIMEOUT,
        allow_redirects=False,
        stream=True,
    )

    if response.status_code == 429 or response.status_code >= 500:
        response.close()
        raise AppdynamicsRetryableError(
            f"AppDynamics OAuth token request failed (retryable): status={response.status_code}"
        )
    if not response.ok:
        response.close()
        raise AppdynamicsError(OAUTH_FAILED_MESSAGE)

    payload = _read_json_within_limits(response)
    token = payload.get("access_token")
    if not token:
        raise AppdynamicsError(OAUTH_FAILED_MESSAGE)
    # The default token TTL is 5 minutes; fall back to that when the response omits it.
    return token, int(payload.get("expires_in") or 300)


def _read_json_within_limits(response: requests.Response) -> Any:
    """Stream a response body under fixed byte and wall-clock caps, then parse it as JSON.

    Reading in chunks means an oversized or trickled body is rejected before it can exhaust
    memory or hold an import worker open indefinitely, rather than being buffered whole by
    `requests`. Exceeding a limit is non-retryable — a host that behaves this way won't stop
    on a retry.
    """
    deadline = time.monotonic() + MAX_DOWNLOAD_SECONDS
    chunks: list[bytes] = []
    total = 0
    try:
        for chunk in response.iter_content(chunk_size=RESPONSE_CHUNK_SIZE):
            if not chunk:
                continue
            total += len(chunk)
            if total > MAX_RESPONSE_BYTES:
                raise AppdynamicsError(
                    f"AppDynamics response exceeded the {MAX_RESPONSE_BYTES // (1024 * 1024)} MiB size limit"
                )
            if time.monotonic() > deadline:
                raise AppdynamicsError(f"AppDynamics response exceeded the {MAX_DOWNLOAD_SECONDS}s download time limit")
            chunks.append(chunk)
    finally:
        response.close()
    return json.loads(b"".join(chunks))


def _read_capped_text(response: requests.Response, limit: int = 64 * 1024) -> str:
    """Read at most `limit` bytes of a streamed body for error logging, then close it."""
    data = bytearray()
    try:
        for chunk in response.iter_content(chunk_size=8192):
            data.extend(chunk)
            if len(data) >= limit:
                break
    finally:
        response.close()
    return bytes(data[:limit]).decode("utf-8", errors="replace")


class AppdynamicsClient:
    """Thin Controller REST client handling auth (OAuth token refresh or basic) and retries."""

    def __init__(self, base_url: str, auth: AppdynamicsAuth, logger: FilteringBoundLogger):
        self._base_url = base_url
        self._auth = auth
        self._logger = logger
        # One session for the whole sync so the TCP/TLS connection is reused. Disable
        # urllib3-level retries — `tenacity` below is the single retry mechanism.
        self._session = make_tracked_session(retry=Retry(total=0))
        self._token: str | None = None
        self._token_expires_at: datetime | None = None

    def _get_token(self) -> str:
        now = datetime.now(UTC)
        if self._token and self._token_expires_at and now < self._token_expires_at:
            return self._token

        token, expires_in = _fetch_oauth_token(self._session, self._base_url, self._auth)
        self._token = token
        self._token_expires_at = now + timedelta(seconds=max(expires_in - TOKEN_REFRESH_MARGIN_SECONDS, 30))
        return token

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self._auth.uses_oauth:
            headers["Authorization"] = f"Bearer {self._get_token()}"
        return headers

    def _basic_auth(self) -> Optional[tuple[str, str]]:
        if self._auth.uses_oauth:
            return None
        return (f"{self._auth.username}@{self._auth.account_name}", self._auth.password or "")

    @retry(
        retry=retry_if_exception_type(
            (
                AppdynamicsRetryableError,
                requests.ReadTimeout,
                requests.ConnectionError,
                requests.exceptions.ChunkedEncodingError,
            )
        ),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=1, max=30),
        reraise=True,
    )
    def get_json(self, path: str, params: dict[str, Any]) -> Any:
        # `output=JSON` is required on Controller REST endpoints — the default is XML.
        # The base URL is user-supplied; refuse redirects so a safe-looking host can't
        # bounce us to an internal one (SSRF guard).
        # `stream=True` keeps the body off the wire until we read it in bounded chunks below,
        # so a hostile controller can't make `requests` buffer an arbitrarily large response.
        response = self._session.get(
            f"{self._base_url}{path}",
            params={**params, "output": "JSON"},
            headers=self._headers(),
            auth=self._basic_auth(),
            timeout=REQUEST_TIMEOUT,
            allow_redirects=False,
            stream=True,
        )

        if response.status_code == 429 or response.status_code >= 500:
            response.close()
            raise AppdynamicsRetryableError(
                f"AppDynamics API error (retryable): status={response.status_code}, path={path}"
            )

        if 300 <= response.status_code < 400:
            response.close()
            raise AppdynamicsError(
                f"AppDynamics returned an unexpected redirect (status={response.status_code}, path={path}); refusing to follow"
            )

        if not response.ok:
            self._logger.error(
                f"AppDynamics API error: status={response.status_code}, body={_read_capped_text(response)}, path={path}"
            )
            response.raise_for_status()

        return _read_json_within_limits(response)


def validate_credentials(
    host: str,
    auth: AppdynamicsAuth,
    team_id: int,
    schema_name: Optional[str] = None,
) -> tuple[bool, str | None]:
    try:
        base_url = _resolve_base_url(host, team_id)
    except ValueError as exc:
        return False, str(exc)

    session = make_tracked_session()
    headers = {"Accept": "application/json"}
    basic_auth: Optional[tuple[str, str]] = None

    if auth.uses_oauth:
        # The token exchange itself proves the API client credentials are genuine.
        try:
            token, _ = _fetch_oauth_token(session, base_url, auth)
        except (AppdynamicsError, AppdynamicsRetryableError) as exc:
            return False, str(exc)
        except requests.RequestException as exc:
            return False, str(exc)
        headers["Authorization"] = f"Bearer {token}"
    else:
        basic_auth = (f"{auth.username}@{auth.account_name}", auth.password or "")

    try:
        # Cheap probe; every Controller stream shares the same account-level read roles,
        # so one probe covers all endpoints. Refuse redirects (SSRF guard). Only the status
        # code matters, so stream and close without downloading a body a hostile host could
        # bloat.
        response = session.get(
            f"{base_url}{APPLICATIONS_PATH}",
            params={"output": "JSON"},
            headers=headers,
            auth=basic_auth,
            timeout=10,
            allow_redirects=False,
            stream=True,
        )
        response.close()
    except requests.RequestException as exc:
        return False, str(exc)

    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return (
            False,
            "Invalid AppDynamics credentials. Please check your controller URL, account name, and credentials.",
        )
    if response.status_code == 403:
        # Valid identity, missing read role. Accept at source-create (the user may grant
        # roles afterwards) and only surface the error when validating a specific schema.
        if schema_name is None:
            return True, None
        return False, "Your AppDynamics user or API client is missing read access to application data."

    return False, f"AppDynamics returned an unexpected status ({response.status_code})."


def _watermark_to_epoch_ms(value: Any) -> int:
    """Coerce the persisted incremental watermark to epoch milliseconds."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=UTC)
        return int(dt.timestamp() * 1000)
    return int(value)


def _iter_windows(start_ms: int, end_ms: int, chunk_days: int) -> Iterator[tuple[int, int]]:
    """Yield `[start, end)` epoch-ms chunks so each request stays bounded and resumable."""
    chunk_ms = chunk_days * MILLIS_PER_DAY
    window_start = start_ms
    while window_start < end_ms:
        yield window_start, min(window_start + chunk_ms, end_ms)
        window_start += chunk_ms


def _metric_rows(application_id: int, metric: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten a metric-data entry's nested `metricValues` into one row per interval."""
    return [
        {
            "application_id": application_id,
            "metricId": metric.get("metricId"),
            "metricName": metric.get("metricName"),
            "metricPath": metric.get("metricPath"),
            "frequency": metric.get("frequency"),
            **value,
        }
        for value in metric.get("metricValues") or []
    ]


def _window_start_ms(
    config: AppdynamicsEndpointConfig,
    end_ms: int,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> int:
    if should_use_incremental_field and db_incremental_field_last_value is not None:
        # BETWEEN_TIMES bounds are inclusive and these endpoints don't paginate, so every
        # row at the watermark timestamp was already captured by the previous run — +1ms
        # skips nothing and avoids re-fetching the boundary rows.
        return _watermark_to_epoch_ms(db_incremental_field_last_value) + 1
    return end_ms - config.default_lookback_days * MILLIS_PER_DAY


def _get_windowed_application_rows(
    client: AppdynamicsClient,
    config: AppdynamicsEndpointConfig,
    application_id: int,
    start_ms: int,
    end_ms: int,
    metric_paths: list[str],
    resumable_source_manager: ResumableSourceManager[AppdynamicsResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    path = config.path.format(application_id=application_id)

    for window_start, window_end in _iter_windows(start_ms, end_ms, config.window_chunk_days):
        window_params = {
            "time-range-type": "BETWEEN_TIMES",
            "start-time": window_start,
            "end-time": window_end,
        }
        if config.is_metric_data:
            for metric_path in metric_paths:
                metrics = client.get_json(path, {**window_params, "metric-path": metric_path, "rollup": "false"})
                for metric in metrics or []:
                    rows = _metric_rows(application_id, metric)
                    if rows:
                        yield rows
        else:
            rows = client.get_json(path, window_params)
            if rows:
                yield [{**row, "application_id": application_id} for row in rows]

        # Save AFTER yielding the window so a crash re-yields it (merge dedupes on the
        # primary key) rather than skipping it.
        resumable_source_manager.save_state(
            AppdynamicsResumeConfig(application_id=application_id, window_start=window_end)
        )


def get_rows(
    base_url: str,
    endpoint: str,
    auth: AppdynamicsAuth,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[AppdynamicsResumeConfig],
    metric_paths: list[str],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = APPDYNAMICS_ENDPOINTS[endpoint]
    client = AppdynamicsClient(base_url, auth, logger)

    if not config.fan_out_over_applications:
        rows = client.get_json(config.path, {})
        if rows:
            yield rows
        return

    applications = client.get_json(APPLICATIONS_PATH, {}) or []
    application_ids = [application["id"] for application in applications]

    # Resolve the saved application-ID bookmark to the slice of applications still to
    # process. If the bookmarked application no longer exists (deleted between runs),
    # start over from the first one — merge dedupes re-pulled rows on the primary key.
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    remaining = application_ids
    resume_window_start: int | None = None
    if resume is not None and resume.application_id is not None and resume.application_id in application_ids:
        remaining = application_ids[application_ids.index(resume.application_id) :]
        resume_window_start = resume.window_start
        logger.debug(
            f"AppDynamics: resuming '{endpoint}' from application_id={resume.application_id}, "
            f"window_start={resume_window_start}"
        )

    end_ms = int(datetime.now(UTC).timestamp() * 1000)
    start_ms = _window_start_ms(config, end_ms, should_use_incremental_field, db_incremental_field_last_value)

    for index, application_id in enumerate(remaining):
        if config.time_windowed:
            # Only the resumed-into application uses the saved window; the rest start fresh.
            application_start = resume_window_start if resume_window_start is not None else start_ms
            resume_window_start = None
            yield from _get_windowed_application_rows(
                client,
                config,
                application_id,
                application_start,
                end_ms,
                metric_paths,
                resumable_source_manager,
            )
        else:
            rows = client.get_json(config.path.format(application_id=application_id), {})
            if rows:
                yield [{**row, "application_id": application_id} for row in rows]

        # Advance the bookmark to the next application so a crash between applications
        # resumes correctly.
        if index + 1 < len(remaining):
            resumable_source_manager.save_state(
                AppdynamicsResumeConfig(application_id=remaining[index + 1], window_start=None)
            )


def appdynamics_source(
    host: str,
    auth: AppdynamicsAuth,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[AppdynamicsResumeConfig],
    team_id: int,
    metric_paths: list[str],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    endpoint_config = APPDYNAMICS_ENDPOINTS[endpoint]
    base_url = _resolve_base_url(host, team_id)

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            base_url=base_url,
            endpoint=endpoint,
            auth=auth,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            metric_paths=metric_paths,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=endpoint_config.primary_keys,
        # Time-windowed streams fan out over applications, so rows are not globally ordered
        # by the cursor field; desc mode persists the incremental watermark only at
        # successful job end instead of checkpointing a misleading per-batch max.
        sort_mode="desc" if endpoint_config.time_windowed else "asc",
    )
