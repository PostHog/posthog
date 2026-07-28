import re
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlencode, urlparse

import requests
from structlog.types import FilteringBoundLogger
from tenacity import RetryCallState, retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.lacework.settings import (
    LACEWORK_ENDPOINTS,
    LaceworkEndpointConfig,
)

REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 5
# The rate limit is 480 requests per rolling hour; a 429's Retry-After can be long, so cap the
# in-process wait and let the (resumable) Temporal activity retry handle anything longer.
MAX_RETRY_AFTER_SECONDS = 60
TOKEN_EXPIRY_SECONDS = 3600
TOKEN_REFRESH_LEEWAY_SECONDS = 300
# Lacework caps one request's result set (across all its pages) at 500k rows.
RESULT_SET_ROW_CAP = 500_000

INVALID_ACCOUNT_ERROR = "Invalid Lacework account name"

_ACCOUNT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.\-]*$")


class LaceworkRetryableError(Exception):
    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


@dataclasses.dataclass
class LaceworkResumeConfig:
    # ISO start of the time window currently being paged. Windows are re-derived from this on
    # resume, so boundaries stay consistent across attempts.
    window_start: str
    # ISO end of that window (pinned so a saved nextPage URL is always paired with the exact
    # window it belongs to).
    window_end: str
    # Next page URL within the window. None means "start the window at its first page".
    next_page_url: str | None = None


def normalize_account(account_name: str) -> str:
    """Turn whatever the user typed into a bare account name.

    Accepts values like ``mycompany``, ``mycompany.lacework.net``, or
    ``https://mycompany.lacework.net/`` and returns ``mycompany``.
    """
    account = account_name.strip()
    account = re.sub(r"^https?://", "", account, flags=re.IGNORECASE)
    account = account.split("/")[0].strip()
    account = re.sub(r"\.lacework\.net$", "", account, flags=re.IGNORECASE)
    return account


def base_url(account_name: str) -> str:
    """Account-specific API base. The validation pins every request to ``*.lacework.net``."""
    account = normalize_account(account_name)
    if not account or not _ACCOUNT_RE.match(account):
        raise ValueError(INVALID_ACCOUNT_ERROR)
    return f"https://{account}.lacework.net/api/v2"


def _is_same_host(url: str, account_name: str) -> bool:
    """Whether a (server-controlled) nextPage URL points back at the configured account host.

    Parse the URL the way requests/urllib3 will before comparing hosts: a backslash (literal or
    percent-encoded) in the authority is a path separator to them, so ``https://evil.example\\@host``
    connects to ``evil.example`` even though ``urlparse`` reports ``host``. Normalize backslashes to
    forward slashes first, then require an ``https`` URL on the default port whose hostname matches
    exactly — otherwise a crafted resume/nextPage URL could exfiltrate the bearer token.
    """
    try:
        normalized = url.replace("\\", "/").replace("%5c", "/").replace("%5C", "/")
        parsed = urlparse(normalized)
        if parsed.scheme.lower() != "https":
            return False
        if parsed.port not in (None, 443):
            return False
        expected = urlparse(base_url(account_name)).hostname or ""
        return (parsed.hostname or "").lower() == expected.lower()
    except Exception:
        return False


def _format_datetime(dt: datetime) -> str:
    """Lacework accepts ``yyyy-MM-ddTHH:mm:ss.SSSZ``; millisecond precision keeps window
    boundaries exact so watermark-derived starts don't truncate backwards."""
    utc_dt = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    return utc_dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    raise ValueError(f"Cannot parse datetime from {value!r}")


def _parse_retry_after(response: requests.Response) -> float | None:
    raw = response.headers.get("Retry-After")
    if raw and raw.strip().isdigit():
        return min(float(raw.strip()), MAX_RETRY_AFTER_SECONDS)
    return None


def _retry_wait(retry_state: RetryCallState) -> float:
    """Honor a server-provided Retry-After when present, else exponential backoff."""
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    if isinstance(exc, LaceworkRetryableError) and exc.retry_after is not None:
        return exc.retry_after
    return wait_exponential_jitter(initial=1, max=30)(retry_state)


class LaceworkClient:
    """Thin client handling the two-step auth (API key -> short-lived bearer token) and requests.

    The bearer token is cached and refreshed with a leeway before its expiry, so long syncs never
    send an expired token.
    """

    def __init__(
        self,
        session: requests.Session,
        account_name: str,
        key_id: str,
        secret_key: str,
        logger: FilteringBoundLogger,
    ) -> None:
        self._session = session
        self._account_name = account_name
        self._base_url = base_url(account_name)
        self._key_id = key_id
        self._secret_key = secret_key
        self._logger = logger
        self._token: str | None = None
        self._token_expires_at: datetime | None = None
        # Token exchanges carry the secret key in the X-LW-UAKS header and return the minted
        # bearer token in a generic `token` field — neither is recognised by the name-based
        # sample scrubbers, so keep auth calls out of HTTP sample capture entirely.
        self._auth_session = make_tracked_session(redact_values=(secret_key,), capture=False)

    @retry(
        retry=retry_if_exception_type((LaceworkRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRIES),
        wait=_retry_wait,
        reraise=True,
    )
    def _request(
        self,
        session: requests.Session,
        method: str,
        url: str,
        headers: dict[str, str],
        json_body: dict[str, Any] | None = None,
    ) -> requests.Response:
        response = session.request(
            method,
            url,
            headers=headers,
            json=json_body,
            timeout=REQUEST_TIMEOUT_SECONDS,
            allow_redirects=False,
        )

        if response.status_code == 429 or response.status_code >= 500:
            retry_after = _parse_retry_after(response) if response.status_code == 429 else None
            raise LaceworkRetryableError(
                f"Lacework API error (retryable): status={response.status_code}, url={url}",
                retry_after=retry_after,
            )

        if not response.ok:
            self._logger.error(f"Lacework API error: status={response.status_code}, body={response.text}, url={url}")
            response.raise_for_status()

        return response

    def _get_token(self) -> str:
        now = datetime.now(UTC)
        if (
            self._token is not None
            and self._token_expires_at is not None
            and now < self._token_expires_at - timedelta(seconds=TOKEN_REFRESH_LEEWAY_SECONDS)
        ):
            return self._token

        response = self._request(
            self._auth_session,
            "POST",
            f"{self._base_url}/access/tokens",
            headers={"X-LW-UAKS": self._secret_key, "Content-Type": "application/json"},
            json_body={"keyId": self._key_id, "expiryTime": TOKEN_EXPIRY_SECONDS},
        )
        data = response.json()
        self._token = str(data["token"])
        try:
            self._token_expires_at = _parse_datetime(data["expiresAt"])
        except Exception:
            self._token_expires_at = now + timedelta(seconds=TOKEN_EXPIRY_SECONDS)
        return self._token

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._get_token()}", "Content-Type": "application/json"}

    def fetch(self, method: str, url: str, json_body: dict[str, Any] | None = None) -> dict[str, Any]:
        """Fetch one page. A 204 (no data) comes back as an empty payload."""
        response = self._request(self._session, method, url, headers=self._auth_headers(), json_body=json_body)
        if response.status_code == 204 or not response.content:
            return {}
        parsed = response.json()
        return parsed if isinstance(parsed, dict) else {"data": parsed}


def validate_credentials(account_name: str, key_id: str, secret_key: str) -> tuple[bool, str | None]:
    """One cheap probe: the token exchange itself confirms the account, key id, and secret."""
    try:
        url = f"{base_url(account_name)}/access/tokens"
    except ValueError:
        return False, INVALID_ACCOUNT_ERROR

    try:
        # capture=False + redact_values: the request's X-LW-UAKS header and the response's
        # generic `token` field would otherwise slip past the name-based sample scrubbers.
        response = make_tracked_session(redact_values=(secret_key,), capture=False).post(
            url,
            headers={"X-LW-UAKS": secret_key, "Content-Type": "application/json"},
            json={"keyId": key_id, "expiryTime": TOKEN_EXPIRY_SECONDS},
            timeout=10,
            allow_redirects=False,
        )
    except requests.exceptions.RequestException as e:
        return False, str(e)

    if response.status_code == 201:
        return True, None

    if response.status_code in (401, 403):
        return False, "Invalid Lacework API key ID or secret key"

    try:
        body = response.json()
        return False, str(body.get("message", response.text))
    except Exception:
        return False, response.text or f"Lacework API returned status {response.status_code}"


def _first_page_request(
    config: LaceworkEndpointConfig, api_base_url: str, window_start: datetime, window_end: datetime
) -> tuple[str, str, dict[str, Any] | None]:
    """Build (method, url, body) for the first page of a time window."""
    start = _format_datetime(window_start)
    end = _format_datetime(window_end)
    if config.method == "GET":
        query = urlencode({"startTime": start, "endTime": end})
        return "GET", f"{api_base_url}{config.path}?{query}", None

    body: dict[str, Any] = {"timeFilter": {"startTime": start, "endTime": end}}
    if config.dataset:
        body["dataset"] = config.dataset
    return "POST", f"{api_base_url}{config.path}", body


def get_rows(
    account_name: str,
    key_id: str,
    secret_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[LaceworkResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = LACEWORK_ENDPOINTS[endpoint]
    # One session reused across every page and window so urllib3 keeps the connection alive.
    session = make_tracked_session()
    client = LaceworkClient(session, account_name, key_id, secret_key, logger)
    api_base_url = base_url(account_name)

    now = datetime.now(UTC)

    start: datetime | None = None
    if should_use_incremental_field and db_incremental_field_last_value is not None:
        try:
            start = _parse_datetime(db_incremental_field_last_value)
        except ValueError:
            logger.warning(
                f"Lacework: could not parse incremental value {db_incremental_field_last_value!r}, "
                f"falling back to the default lookback"
            )
    if start is None:
        start = now - timedelta(days=config.default_lookback_days)
    # A future-dated watermark (bad source data) would build an inverted window; clamp to now.
    start = min(start, now)

    window_start = start
    window_end: datetime | None = None
    next_page_url: str | None = None

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None:
        window_start = _parse_datetime(resume.window_start)
        window_end = _parse_datetime(resume.window_end)
        if resume.next_page_url and not _is_same_host(resume.next_page_url, account_name):
            logger.warning("Lacework: ignoring resume URL whose host does not match the configured account")
        else:
            next_page_url = resume.next_page_url
        logger.debug(f"Lacework: resuming from window_start={resume.window_start}, url={next_page_url}")

    while window_start < now:
        if window_end is None:
            window_end = min(window_start + timedelta(days=config.window_days), now)

        if next_page_url is not None:
            method, url, body = "GET", next_page_url, None
        else:
            method, url, body = _first_page_request(config, api_base_url, window_start, window_end)

        while True:
            data = client.fetch(method, url, body)
            rows = data.get("data") or []
            paging = data.get("paging") or {}
            total_rows = paging.get("totalRows")
            if isinstance(total_rows, int | float) and total_rows >= RESULT_SET_ROW_CAP:
                logger.warning(
                    f"Lacework: result set for {endpoint} window "
                    f"{_format_datetime(window_start)}..{_format_datetime(window_end)} hit the API's "
                    f"{RESULT_SET_ROW_CAP}-row cap; rows beyond the cap are not returned"
                )

            next_page_url = (paging.get("urls") or {}).get("nextPage")
            if next_page_url is not None and not _is_same_host(next_page_url, account_name):
                logger.warning("Lacework: stopping pagination, next URL host does not match the configured account")
                next_page_url = None

            if rows:
                yield rows

            # Save AFTER yielding so a crash re-yields the current page rather than skipping it.
            # When the window is done, checkpoint the NEXT window instead so a resume doesn't
            # re-walk this one.
            if next_page_url is not None:
                resumable_source_manager.save_state(
                    LaceworkResumeConfig(
                        window_start=_format_datetime(window_start),
                        window_end=_format_datetime(window_end),
                        next_page_url=next_page_url,
                    )
                )
                method, url, body = "GET", next_page_url, None
            else:
                break

        window_start = window_end
        window_end = None
        if window_start < now:
            next_window_end = min(window_start + timedelta(days=config.window_days), now)
            resumable_source_manager.save_state(
                LaceworkResumeConfig(
                    window_start=_format_datetime(window_start),
                    window_end=_format_datetime(next_window_end),
                    next_page_url=None,
                )
            )


def lacework_source(
    account_name: str,
    key_id: str,
    secret_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[LaceworkResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    endpoint_config = LACEWORK_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            account_name=account_name,
            key_id=key_id,
            secret_key=secret_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=endpoint_config.primary_keys,
        # Rows within a time window arrive in no documented order, so the incremental watermark
        # must only persist at successful job end ("desc" mode) — a per-batch checkpoint could
        # advance it past unfetched rows of the same window. Mid-job crashes resume via the
        # ResumableSourceManager state instead.
        sort_mode="desc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="week" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )
