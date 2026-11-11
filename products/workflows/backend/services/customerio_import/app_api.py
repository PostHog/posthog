"""Reads automation message content from Customer.io's App API with the team's own App API key.

The key belongs to the customer's Customer.io account and no other PostHog process shares it, so the client paces
itself under Customer.io's documented limit of 10 requests per second and honors 429 with Retry-After itself.
"""

import time
from typing import Any

import requests
import structlog

logger = structlog.get_logger(__name__)

_BASE_URLS = {"us": "https://api.customer.io/v1", "eu": "https://api-eu.customer.io/v1"}
_MIN_INTERVAL_SECONDS = 0.125
_MAX_RETRY_AFTER_SECONDS = 10.0
_MAX_ATTEMPTS = 3
_MAX_PAGES = 100
_TIMEOUT_SECONDS = 20


class CustomerioApiError(Exception):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class CustomerioAppApi:
    def __init__(self, api_key: str, deadline: float) -> None:
        self._api_key = api_key
        self._deadline = deadline
        self._base_url: str | None = None
        self._last_request_at = 0.0
        self._session = requests.Session()

    def campaign_actions(self, campaign_id: str) -> list[dict[str, Any]]:
        """Every message, webhook and attribute update tile of an automation, one object per language variant."""
        return self._paged(f"/campaigns/{campaign_id}/actions", "actions")

    def sender_identities(self) -> list[dict[str, Any]]:
        return self._paged("/sender_identities", "sender_identities")

    def segments(self) -> list[dict[str, Any]]:
        return list(self._get("/segments").get("segments") or [])

    def snippets(self) -> list[dict[str, Any]]:
        return list(self._get("/snippets").get("snippets") or [])

    def _paged(self, path: str, key: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        start: str | None = None
        for _ in range(_MAX_PAGES):
            page = self._get(path, {"start": start} if start else None)
            items.extend(item for item in page.get(key) or [] if isinstance(item, dict))
            start = page.get("next") or None
            if not start:
                break
        return items

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if self._base_url is None:
            self._base_url = self._detect_region()
        return self._request(self._base_url, path, params)

    def _detect_region(self) -> str:
        # The key does not say which region its account lives in, so the first region that accepts it wins.
        for region in ("us", "eu"):
            try:
                self._request(_BASE_URLS[region], "/subscription_topics", None)
            except CustomerioApiError as error:
                if error.status in (401, 403):
                    continue
                raise
            return _BASE_URLS[region]
        raise CustomerioApiError("Customer.io rejected the stored App API key in both regions.", status=401)

    def _request(self, base_url: str, path: str, params: dict[str, Any] | None) -> dict[str, Any]:
        for attempt in range(_MAX_ATTEMPTS):
            wait = self._last_request_at + _MIN_INTERVAL_SECONDS - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            remaining = self._deadline - time.monotonic()
            if remaining <= 1:
                raise CustomerioApiError("Reading from Customer.io took too long.")
            self._last_request_at = time.monotonic()
            try:
                response = self._session.get(
                    f"{base_url}{path}",
                    params=params,
                    headers={"Authorization": f"Bearer {self._api_key}", "Accept": "application/json"},
                    timeout=min(_TIMEOUT_SECONDS, remaining),
                )
            except requests.RequestException as error:
                raise CustomerioApiError(f"Customer.io could not be reached: {type(error).__name__}") from error
            if response.status_code == 429 and attempt < _MAX_ATTEMPTS - 1:
                time.sleep(_retry_after(response))
                continue
            if response.status_code >= 400:
                # The body can echo request details, so only the status is logged.
                logger.info("workflows.import.customerio_api_error", path=path, status=response.status_code)
                raise CustomerioApiError(
                    f"Customer.io answered {response.status_code} for {path}.", status=response.status_code
                )
            try:
                body = response.json()
            except ValueError as error:
                raise CustomerioApiError(f"Customer.io returned a response that is not JSON for {path}.") from error
            return body if isinstance(body, dict) else {}
        raise CustomerioApiError(f"Customer.io kept rate limiting {path}.", status=429)


def _retry_after(response: requests.Response) -> float:
    try:
        seconds = float(response.headers.get("Retry-After", "1"))
    except ValueError:
        seconds = 1.0
    return min(max(seconds, 0.5), _MAX_RETRY_AFTER_SECONDS)
