"""Read-only client for Resend's API, used by the provider import. See https://resend.com/docs/api-reference.

The customer owns the key, so per /routing-outbound-api-calls this honors `retry-after` here rather than going
through `posthog/egress/`. Resend shares one rate limit across all of a team's keys, so the import stays well under
it to leave room for the customer's live sending.
"""

import time
from collections.abc import Iterator
from typing import Any

from django.conf import settings

import requests

from posthog.dataclasses import frozen

PAGE_SIZE = 100
# Resend's default limit is 10 requests a second per team, shared with the customer's live sends.
REQUESTS_PER_SECOND = 2
MAX_RATE_LIMIT_WAITS = 5
MAX_RETRY_AFTER_SECONDS = 60
DEFAULT_TIMEOUT_SECONDS = 30
USER_AGENT = "posthog-messaging-import/1.0"


class ResendAPIError(Exception):
    def __init__(self, message: str, status_code: int | None = None, name: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.name = name


class ResendKeyRejected(ResendAPIError):
    """The key is wrong, deleted or suspended."""


class ResendKeyCannotRead(ResendKeyRejected):
    """The key is a sending-only key. Reading needs a full access key."""


class ResendRateLimited(ResendAPIError):
    """Resend kept answering 429 after the client waited as long as it told it to."""


@frozen
class ResendPage:
    data: list[dict[str, Any]]
    # The cursor of the next page, or None on the last page.
    next_after: str | None


class ResendClient:
    def __init__(
        self,
        api_key: str,
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
        max_rate_limit_waits: int = MAX_RATE_LIMIT_WAITS,
    ):
        self._api_key = api_key
        self._timeout = timeout
        self._max_rate_limit_waits = max_rate_limit_waits
        self._next_request_at = 0.0

    def __repr__(self) -> str:
        return "ResendClient()"

    def check_access(self) -> None:
        """Raises ResendKeyRejected or ResendKeyCannotRead when the key can't read the account."""
        self._get("/domains", {"limit": 1})

    def pages(self, path: str, after: str | None = None) -> Iterator[ResendPage]:
        cursor = after
        while True:
            params: dict[str, Any] = {"limit": PAGE_SIZE}
            if cursor:
                params["after"] = cursor
            body = self._get(path, params)
            data = body.get("data")
            if not isinstance(data, list):
                raise ResendAPIError(f"Resend sent an unexpected response for {path}.")
            has_more = bool(body.get("has_more"))
            if has_more and not data:
                raise ResendAPIError(f"Resend sent an empty page for {path} and said there were more.")
            next_after = str(data[-1]["id"]) if has_more else None
            if next_after is not None and next_after == cursor:
                raise ResendAPIError(f"Resend sent the same page twice for {path}.")
            yield ResendPage(data=data, next_after=next_after)
            if next_after is None:
                return
            cursor = next_after

    def get(self, path: str) -> dict[str, Any]:
        return self._get(path, None)

    def _get(self, path: str, params: dict[str, Any] | None) -> dict[str, Any]:
        waits = 0
        while True:
            self._pace()
            try:
                response = requests.get(
                    f"{settings.MESSAGING_RESEND_API_URL}{path}",
                    params=params,
                    headers={"Authorization": f"Bearer {self._api_key}", "User-Agent": USER_AGENT},
                    timeout=self._timeout,
                    allow_redirects=False,
                )
            except requests.RequestException as e:
                # The exception text can hold the request's details, so only its type leaves this function.
                raise ResendAPIError(f"Couldn't reach Resend ({type(e).__name__}).") from None
            if response.status_code == 429:
                if waits >= self._max_rate_limit_waits:
                    raise ResendRateLimited("Resend asked PostHog to slow down.", status_code=429)
                waits += 1
                time.sleep(_retry_after_seconds(response))
                continue
            return _parse(response)

    def _pace(self) -> None:
        now = time.monotonic()
        if now < self._next_request_at:
            time.sleep(self._next_request_at - now)
        self._next_request_at = max(now, self._next_request_at) + 1 / REQUESTS_PER_SECOND


def _retry_after_seconds(response: requests.Response) -> float:
    try:
        seconds = float(response.headers.get("retry-after", "1"))
    except ValueError:
        seconds = 1.0
    return min(max(seconds, 0.0), MAX_RETRY_AFTER_SECONDS)


def _parse(response: requests.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        body = {}
    if response.ok:
        return body
    name = str(body.get("name") or "")
    message = str(body.get("message") or "")
    status = response.status_code
    if name == "restricted_api_key" and status == 401:
        raise ResendKeyCannotRead("Sending-only key.", status_code=status, name=name)
    # Resend answers an invalid key on a read endpoint with a 400 validation_error.
    if status in (401, 403) or (status == 400 and "api key" in message.lower()):
        raise ResendKeyRejected("Resend rejected the key.", status_code=status, name=name)
    raise ResendAPIError(f"Resend returned HTTP {status}.", status_code=status, name=name)
