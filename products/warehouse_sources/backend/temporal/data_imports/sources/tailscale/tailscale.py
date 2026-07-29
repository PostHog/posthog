import re
import time
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import quote

import requests
from structlog.types import FilteringBoundLogger
from tenacity import RetryCallState, retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.tailscale.settings import (
    AUDIT_LOG_RETENTION_DAYS,
    AUDIT_LOG_WINDOW_DAYS,
    AUDIT_LOGS_ENDPOINT,
    TAILSCALE_ENDPOINTS,
    TailscaleEndpointConfig,
)

BASE_URL = "https://api.tailscale.com/api/v2"

REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 5
MAX_RETRY_AFTER_SECONDS = 60
# Refresh OAuth access tokens (1h lifetime) with headroom so a token can't expire mid-request.
OAUTH_TOKEN_REFRESH_MARGIN_SECONDS = 300

OAUTH_CREDENTIALS_ERROR = "Invalid Tailscale OAuth client credentials"


class TailscaleRetryableError(Exception):
    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class TailscaleAuthError(Exception):
    pass


@dataclasses.dataclass
class TailscaleResumeConfig:
    # Start of the next unfetched audit-log window (RFC 3339). Only the audit log
    # endpoint checkpoints — the other endpoints are single unpaginated requests.
    window_start: str


def normalize_tailnet(tailnet: str | None) -> str:
    """Return the tailnet path segment, defaulting to ``-`` (the credential's own tailnet)."""
    normalized = (tailnet or "").strip()
    return normalized if normalized else "-"


def _endpoint_url(config: TailscaleEndpointConfig, tailnet: str | None) -> str:
    # The tailnet is user input placed in the URL path (often a domain like `example.com`),
    # so quote it to keep it a single path segment.
    return f"{BASE_URL}{config.path.format(tailnet=quote(normalize_tailnet(tailnet), safe=''))}"


class TailscaleAuth:
    """Produces the ``Authorization`` header for either auth method.

    API access tokens are sent directly as a Bearer token. OAuth clients exchange their
    client credentials for a short-lived access token, cached until close to expiry.
    """

    def __init__(
        self,
        api_key: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
    ) -> None:
        self._api_key = (api_key or "").strip()
        self._client_id = (client_id or "").strip()
        self._client_secret = (client_secret or "").strip()
        self._access_token: str | None = None
        self._token_expires_at: float = 0.0

    def get_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._get_token()}", "Accept": "application/json"}

    def _get_token(self) -> str:
        if self._api_key:
            return self._api_key

        if not self._client_id or not self._client_secret:
            raise TailscaleAuthError(
                "Missing Tailscale credentials. Provide an API access token or an OAuth client ID and secret."
            )

        if self._access_token and time.monotonic() < self._token_expires_at - OAUTH_TOKEN_REFRESH_MARGIN_SECONDS:
            return self._access_token

        response = make_tracked_session().post(
            f"{BASE_URL}/oauth/token",
            data={"client_id": self._client_id, "client_secret": self._client_secret},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        if response.status_code != 200:
            raise TailscaleAuthError(f"{OAUTH_CREDENTIALS_ERROR} (status={response.status_code})")

        payload = response.json()
        token = payload.get("access_token")
        if not token:
            raise TailscaleAuthError(f"{OAUTH_CREDENTIALS_ERROR} (no access token in response)")

        self._access_token = str(token)
        self._token_expires_at = time.monotonic() + float(payload.get("expires_in") or 3600)
        return self._access_token


def _format_rfc3339(dt: datetime) -> str:
    utc_dt = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    return utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    if not isinstance(value, str) or not value:
        return None
    # Tailscale timestamps carry nanosecond precision; trim to microseconds so
    # `fromisoformat` accepts them.
    trimmed = re.sub(r"\.(\d{6})\d+", r".\1", value.strip())
    try:
        parsed = datetime.fromisoformat(trimmed.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _parse_retry_after(response: requests.Response) -> float | None:
    raw = response.headers.get("Retry-After")
    if raw and raw.strip().isdigit():
        return min(float(raw.strip()), MAX_RETRY_AFTER_SECONDS)
    return None


def _retry_wait(retry_state: RetryCallState) -> float:
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    if isinstance(exc, TailscaleRetryableError) and exc.retry_after is not None:
        return exc.retry_after
    return wait_exponential_jitter(initial=1, max=30)(retry_state)


@retry(
    retry=retry_if_exception_type((TailscaleRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(MAX_RETRIES),
    wait=_retry_wait,
    reraise=True,
)
def _fetch(auth: TailscaleAuth, url: str, params: dict[str, Any] | None = None) -> requests.Response:
    response = make_tracked_session().get(
        url, headers=auth.get_headers(), params=params or None, timeout=REQUEST_TIMEOUT_SECONDS
    )

    if response.status_code == 429 or response.status_code >= 500:
        retry_after = _parse_retry_after(response) if response.status_code == 429 else None
        raise TailscaleRetryableError(
            f"Tailscale API error (retryable): status={response.status_code}, url={url}",
            retry_after=retry_after,
        )

    return response


def _extract_rows(payload: Any, data_key: str) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        rows = payload.get(data_key)
        return rows if isinstance(rows, list) else []
    # Defensive: undocumented bare-list responses.
    return payload if isinstance(payload, list) else []


def _list_rows(
    auth: TailscaleAuth, config: TailscaleEndpointConfig, tailnet: str | None, logger: FilteringBoundLogger
) -> Iterator[list[dict[str, Any]]]:
    url = _endpoint_url(config, tailnet)
    response = _fetch(auth, url, dict(config.params))
    response.raise_for_status()

    rows = _extract_rows(response.json(), config.data_key)
    logger.debug(f"Tailscale: fetched {len(rows)} rows from {config.name}")
    if rows:
        yield rows


def _key_rows(
    auth: TailscaleAuth, config: TailscaleEndpointConfig, tailnet: str | None, logger: FilteringBoundLogger
) -> Iterator[list[dict[str, Any]]]:
    """The keys list endpoint only returns id + description, so fetch each key's detail
    (created, expires, revoked, capabilities) individually. Tailnets hold few keys."""
    url = _endpoint_url(config, tailnet)
    response = _fetch(auth, url, dict(config.params))
    response.raise_for_status()

    listed = _extract_rows(response.json(), config.data_key)
    rows: list[dict[str, Any]] = []
    for key in listed:
        key_id = key.get("id") if isinstance(key, dict) else None
        if not key_id:
            continue
        detail_response = _fetch(auth, f"{url}/{quote(str(key_id), safe='')}")
        if detail_response.status_code == 404:
            # The key was deleted between the list and detail calls.
            logger.debug(f"Tailscale: key {key_id} disappeared mid-sync, skipping")
            continue
        detail_response.raise_for_status()
        detail = detail_response.json()
        rows.append(detail if isinstance(detail, dict) else key)

    logger.debug(f"Tailscale: fetched {len(rows)} rows from {config.name}")
    if rows:
        yield rows


def _audit_log_rows(
    auth: TailscaleAuth,
    config: TailscaleEndpointConfig,
    tailnet: str | None,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[TailscaleResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    """Walk the configuration audit log in ascending time windows.

    The endpoint requires inclusive `start`/`end` params and returns everything in the
    window (no pagination), so each window is one request, yielded as one batch, then
    checkpointed. Because `start` is inclusive, each incremental run (and each window
    boundary) would re-fetch the records at the boundary timestamp — a client-side
    cursor drops those already-seen rows.
    """
    url = _endpoint_url(config, tailnet)
    now = datetime.now(UTC)
    retention_floor = now - timedelta(days=AUDIT_LOG_RETENTION_DAYS)

    cursor: datetime | None = None
    start = retention_floor
    if should_use_incremental_field:
        watermark = _parse_datetime(db_incremental_field_last_value)
        if watermark is not None:
            cursor = watermark
            # A watermark older than the retention window would request a range Tailscale
            # no longer holds; clamp rather than risk a 4xx for out-of-retention starts.
            start = max(watermark, retention_floor)

    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        resume_start = _parse_datetime(resume_config.window_start) if resume_config else None
        if resume_start is not None and resume_start > start:
            start = resume_start
            logger.debug(f"Tailscale: resuming audit log sync from {_format_rfc3339(resume_start)}")

    while start < now:
        window_end = min(start + timedelta(days=AUDIT_LOG_WINDOW_DAYS), now)
        response = _fetch(auth, url, {"start": _format_rfc3339(start), "end": _format_rfc3339(window_end)})
        response.raise_for_status()

        rows = _extract_rows(response.json(), config.data_key)
        fresh: list[tuple[datetime | None, dict[str, Any]]] = []
        for row in rows:
            event_time = _parse_datetime(row.get("eventTime"))
            # Rows with an unparsable eventTime are kept — dropping audit records is
            # worse than a rare duplicate.
            if cursor is not None and event_time is not None and event_time <= cursor:
                continue
            fresh.append((event_time, row))

        # sort_mode="asc" lets the pipeline checkpoint the watermark per batch, so rows
        # must be yielded in ascending eventTime order.
        fresh.sort(key=lambda item: item[0] or datetime.min.replace(tzinfo=UTC))

        if fresh:
            yield [row for _, row in fresh]
            parsed_times = [event_time for event_time, _ in fresh if event_time is not None]
            if parsed_times:
                cursor = max(parsed_times)

        # Checkpoint AFTER yielding so a crash re-fetches (and dedupes) the last window
        # instead of skipping it.
        resumable_source_manager.save_state(TailscaleResumeConfig(window_start=_format_rfc3339(window_end)))
        start = window_end


def get_rows(
    api_key: str | None,
    client_id: str | None,
    client_secret: str | None,
    tailnet: str | None,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[TailscaleResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = TAILSCALE_ENDPOINTS[endpoint]
    auth = TailscaleAuth(api_key=api_key, client_id=client_id, client_secret=client_secret)

    if endpoint == AUDIT_LOGS_ENDPOINT:
        yield from _audit_log_rows(
            auth,
            config,
            tailnet,
            logger,
            resumable_source_manager,
            should_use_incremental_field,
            db_incremental_field_last_value,
        )
    elif endpoint == "keys":
        yield from _key_rows(auth, config, tailnet, logger)
    else:
        yield from _list_rows(auth, config, tailnet, logger)


def tailscale_source(
    api_key: str | None,
    client_id: str | None,
    client_secret: str | None,
    tailnet: str | None,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[TailscaleResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    endpoint_config = TAILSCALE_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            client_id=client_id,
            client_secret=client_secret,
            tailnet=tailnet,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=[endpoint_config.primary_key] if endpoint_config.primary_key else None,
        # Audit log windows advance forward in time and each window is sorted ascending;
        # the other endpoints are single full-refresh responses where order is irrelevant.
        sort_mode="asc",
        partition_count=1 if endpoint_config.partition_key else None,
        partition_size=1 if endpoint_config.partition_key else None,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )


def _probe_url_and_params(schema_name: str | None, tailnet: str | None) -> tuple[str, dict[str, Any]]:
    """A cheap request proving the credential can reach `schema_name` (or the tailnet at all).

    The keys list is the default probe: it is small on every tailnet (devices can be
    huge and the API has no `limit` param). The audit log probe uses a 1-hour window
    to satisfy the required start/end params without pulling real volume.
    """
    config = TAILSCALE_ENDPOINTS.get(schema_name or "") or TAILSCALE_ENDPOINTS["keys"]
    url = _endpoint_url(config, tailnet)
    if config.name == AUDIT_LOGS_ENDPOINT:
        now = datetime.now(UTC)
        return url, {"start": _format_rfc3339(now - timedelta(hours=1)), "end": _format_rfc3339(now)}
    if config.name == "devices":
        # Probe with the lighter default field set.
        return url, {}
    return url, dict(config.params)


def validate_credentials(
    api_key: str | None,
    client_id: str | None,
    client_secret: str | None,
    tailnet: str | None,
    schema_name: str | None = None,
) -> tuple[bool, str | None]:
    auth = TailscaleAuth(api_key=api_key, client_id=client_id, client_secret=client_secret)
    url, params = _probe_url_and_params(schema_name, tailnet)

    try:
        response = make_tracked_session().get(url, headers=auth.get_headers(), params=params or None, timeout=10)
    except TailscaleAuthError as e:
        return False, str(e)
    except requests.exceptions.RequestException as e:
        return False, str(e)

    if response.status_code == 200:
        return True, None

    if response.status_code == 401:
        return False, "Invalid Tailscale credentials. API access tokens expire after at most 90 days."

    if response.status_code == 403:
        if schema_name is None:
            # Valid credential without the probe's scope (OAuth clients are scoped per
            # resource) — let source creation through; per-endpoint access is checked later.
            return True, None
        return False, f"Your Tailscale credentials lack the scope required to read '{schema_name}'."

    if response.status_code == 404:
        return False, "Tailnet not found. Check the tailnet name, or leave it blank to use the default tailnet."

    try:
        body = response.json()
        return False, str(body.get("message", response.text))
    except Exception:
        return False, response.text
