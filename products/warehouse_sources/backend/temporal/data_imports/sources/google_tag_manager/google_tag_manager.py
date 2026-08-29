import time
from collections.abc import Iterator
from typing import Any, Optional

from django.conf import settings

import requests
import structlog
from google.auth.transport.requests import AuthorizedSession
from google.oauth2.credentials import Credentials as OAuthCredentials
from urllib3.util.retry import Retry

from products.warehouse_sources.backend.temporal.data_imports.naming_convention import NamingConvention
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_adapter
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.googletagmanager import (
    GoogleTagManagerSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_tag_manager.settings import (
    ENDPOINTS,
    GOOGLE_TAG_MANAGER_PRIMARY_KEYS,
    GoogleTagManagerParentLevel,
)

logger = structlog.get_logger(__name__)

GTM_API_BASE = "https://tagmanager.googleapis.com/tagmanager/v2"
GTM_OAUTH_SCOPES = ["https://www.googleapis.com/auth/tagmanager.readonly"]

# The GTM API budget is tiny and project-wide: 0.25 QPS (a 100-second sliding window of 25
# requests) and 10,000 requests/day, shared by every connection made through our OAuth app
# (https://developers.google.com/tag-platform/tag-manager/api/v2/limits-quotas). Space
# requests out proactively and back off hard when Google reports quota exhaustion.
REQUEST_INTERVAL_SECONDS = 4.5
MAX_TRANSIENT_RETRIES = 5
TRANSIENT_BACKOFF_BASE_SECONDS = 10.0

# Legacy-style Google error reasons that mean "over quota" rather than "no permission".
_QUOTA_ERROR_REASONS = {"quotaExceeded", "rateLimitExceeded", "userRateLimitExceeded", "dailyLimitExceeded"}


class GoogleTagManagerQuotaExceededError(Exception):
    """Raised when the GTM API quota stays exhausted after in-line retries.

    Deliberately NOT matched by `get_non_retryable_errors`, so Temporal retries the sync
    later, once the shared per-project quota has refilled. Tagged `(retryable)` so
    `GoogleTagManagerSource.get_retryable_errors` keeps this self-recovering failure out
    of error tracking.
    """


def google_tag_manager_session(refresh_token: str) -> AuthorizedSession:
    credentials = OAuthCredentials(
        token=None,
        refresh_token=refresh_token,
        client_id=settings.GOOGLE_TAG_MANAGER_APP_CLIENT_ID,
        client_secret=settings.GOOGLE_TAG_MANAGER_APP_CLIENT_SECRET,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=GTM_OAUTH_SCOPES,
    )
    session = AuthorizedSession(credentials)
    # retry=Retry(total=0) opts out of the adapter's built-in 429/5xx retries: `_list_page` is the
    # single retry layer, since it must also treat quota 403s as transient and each compounded
    # retry would spend more of the tiny shared GTM quota.
    adapter = make_tracked_adapter(retry=Retry(total=0))
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


class RequestThrottle:
    """Spaces consecutive requests at least `interval_seconds` apart, to stay under GTM's 0.25 QPS."""

    def __init__(self, interval_seconds: float = REQUEST_INTERVAL_SECONDS) -> None:
        self._interval_seconds = interval_seconds
        self._last_request_at: float | None = None

    def wait(self) -> None:
        if self._last_request_at is not None:
            remaining = self._interval_seconds - (time.monotonic() - self._last_request_at)
            if remaining > 0:
                time.sleep(remaining)
        self._last_request_at = time.monotonic()


def parse_account_ids(raw: Optional[str]) -> set[str] | None:
    """Normalize the optional comma-separated account filter; None means every accessible account."""
    if not raw:
        return None
    ids = {part.strip() for part in raw.split(",")}
    ids.discard("")
    return ids or None


def _is_quota_error(response: requests.Response) -> bool:
    """GTM reports quota exhaustion as 429, or as 403 with a quota/rate-limit reason.

    A permission 403 must NOT be retried, so the 403 body is inspected for Google's quota
    markers (legacy `error.errors[].reason` and the newer `error.status` RESOURCE_EXHAUSTED).
    """
    if response.status_code == 429:
        return True
    if response.status_code != 403:
        return False
    try:
        error = response.json().get("error", {})
    except ValueError:
        return False
    if not isinstance(error, dict):
        return False
    if error.get("status") == "RESOURCE_EXHAUSTED":
        return True
    reasons = {item.get("reason") for item in error.get("errors", []) if isinstance(item, dict)}
    return bool(reasons & _QUOTA_ERROR_REASONS)


def _backoff_seconds(response: requests.Response, attempt: int) -> float:
    """Seconds to wait before retrying a transient error: honor `Retry-After`, else exponential."""
    retry_after = response.headers.get("Retry-After")
    if retry_after is not None:
        try:
            return float(retry_after)
        except ValueError:
            pass
    return TRANSIENT_BACKOFF_BASE_SECONDS * (2**attempt)


def _list_page(
    session: AuthorizedSession, throttle: RequestThrottle, url: str, params: dict[str, str]
) -> dict[str, Any]:
    for attempt in range(MAX_TRANSIENT_RETRIES + 1):
        throttle.wait()
        response = session.get(url, params=params)
        if response.ok:
            return response.json()

        # Surface Google's real reason, since raise_for_status() discards the body where it lives.
        logger.warning(
            "GTM API request failed",
            url=url,
            status_code=response.status_code,
            body=response.text,
        )

        is_quota = _is_quota_error(response)
        is_server_error = 500 <= response.status_code < 600
        if not is_quota and not is_server_error:
            # Permission and bad-request errors are permanent: let the HTTPError bubble up so
            # `get_non_retryable_errors` can match "401 Client Error" / "403 Client Error".
            response.raise_for_status()

        if attempt == MAX_TRANSIENT_RETRIES:
            if is_quota:
                raise GoogleTagManagerQuotaExceededError(
                    f"Google Tag Manager API quota still exhausted after {MAX_TRANSIENT_RETRIES} retries (retryable)"
                )
            # A transient 5xx that never cleared, so surface the HTTPError for a Temporal activity retry.
            response.raise_for_status()

        wait_seconds = _backoff_seconds(response, attempt)
        logger.warning(
            "GTM API request failed, backing off",
            url=url,
            attempt=attempt,
            wait_seconds=wait_seconds,
        )
        time.sleep(wait_seconds)

    # Unreachable: the loop either returns, raises for status, or raises the quota error.
    raise AssertionError("unreachable")


def _iter_pages(
    session: AuthorizedSession,
    throttle: RequestThrottle,
    resource_path: str,
    data_key: str,
    params: dict[str, str] | None = None,
) -> Iterator[list[dict[str, Any]]]:
    url = f"{GTM_API_BASE}/{resource_path}"
    page_token: str | None = None
    while True:
        query = dict(params or {})
        if page_token:
            query["pageToken"] = page_token
        payload = _list_page(session, throttle, url, query)
        rows = payload.get(data_key) or []
        if rows:
            yield rows
        page_token = payload.get("nextPageToken")
        if not page_token:
            return


def _iter_rows(
    session: AuthorizedSession,
    throttle: RequestThrottle,
    resource_path: str,
    data_key: str,
) -> Iterator[dict[str, Any]]:
    for page in _iter_pages(session, throttle, resource_path, data_key):
        yield from page


def _iter_accounts(
    session: AuthorizedSession, throttle: RequestThrottle, account_ids: set[str] | None
) -> Iterator[dict[str, Any]]:
    for account in _iter_rows(session, throttle, "accounts", "account"):
        if account_ids is None or account.get("accountId") in account_ids:
            yield account


def _iter_parent_paths(
    session: AuthorizedSession,
    throttle: RequestThrottle,
    parent_level: GoogleTagManagerParentLevel,
    account_ids: set[str] | None,
) -> Iterator[str]:
    """Depth-first walk down to the endpoint's parent level, yielding parent resource paths.

    Depth-first keeps the first leaf request close to the start of the sync, so rows start
    yielding (and the pipeline starts batching) before the whole account tree has been listed.
    """
    for account in _iter_accounts(session, throttle, account_ids):
        if parent_level == "account":
            yield account["path"]
            continue
        for container in _iter_rows(session, throttle, f"{account['path']}/containers", "container"):
            if parent_level == "container":
                yield container["path"]
                continue
            yield from (
                workspace["path"]
                for workspace in _iter_rows(session, throttle, f"{container['path']}/workspaces", "workspace")
            )


def get_accounts_probe(session: AuthorizedSession) -> dict[str, Any]:
    """First page of accounts.list, the cheapest call that proves the token grants GTM read access."""
    response = session.get(f"{GTM_API_BASE}/accounts")
    response.raise_for_status()
    return response.json()


def google_tag_manager_source(
    config: GoogleTagManagerSourceConfig, resource_name: str, refresh_token: str
) -> SourceResponse:
    endpoint = ENDPOINTS.get(resource_name)
    if endpoint is None:
        raise ValueError(f"Unknown Google Tag Manager schema: {resource_name}")

    account_ids = parse_account_ids(config.account_ids)

    def get_rows() -> Iterator[list[dict[str, Any]]]:
        session = google_tag_manager_session(refresh_token)
        throttle = RequestThrottle()

        if endpoint.parent_level == "root":
            for page in _iter_pages(session, throttle, endpoint.path_suffix, endpoint.data_key, endpoint.params):
                rows = [row for row in page if account_ids is None or row.get("accountId") in account_ids]
                if rows:
                    yield rows
            return

        for parent_path in _iter_parent_paths(session, throttle, endpoint.parent_level, account_ids):
            yield from _iter_pages(
                session, throttle, f"{parent_path}/{endpoint.path_suffix}", endpoint.data_key, endpoint.params
            )

    return SourceResponse(
        name=NamingConvention.normalize_identifier(resource_name),
        items=get_rows,
        primary_keys=list(GOOGLE_TAG_MANAGER_PRIMARY_KEYS),
    )
