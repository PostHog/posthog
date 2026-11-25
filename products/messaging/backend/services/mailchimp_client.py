"""Read-only client for Mailchimp's Marketing API, used by the provider import.
See https://mailchimp.com/developer/marketing/api/.

The customer owns the key, so per /routing-outbound-api-calls this honors rate limits here rather than going through
`posthog/egress/`. Mailchimp allows each account 10 requests in flight at once and answers 429 past that
(https://mailchimp.com/developer/marketing/api-concepts/errors/). The client sends one request at a time, so the
customer's own apps keep the other nine.

The data center comes from the key's suffix, such as `-us21`, and must match a strict pattern, so a crafted key can't
point the request, and the key with it, at another host.
"""

import re
import time
from typing import Any
from urllib.parse import quote

from django.conf import settings

import requests

from posthog.dataclasses import frozen

PAGE_SIZE = 1000
# Mailchimp documents no request rate, only the limit on requests in flight, so this only keeps a long import gentle.
REQUESTS_PER_SECOND = 10
MAX_RATE_LIMIT_WAITS = 6
MAX_TRANSIENT_RETRIES = 3
TRANSIENT_RETRY_BASE_SECONDS = 2
MAX_WAIT_SECONDS = 60
# Mailchimp stops a request after 120 seconds, and a page of 1,000 members can take a while to build.
DEFAULT_TIMEOUT_SECONDS = 120
USER_AGENT = "posthog-messaging-import/1.0"
_DATA_CENTER = re.compile(r"[a-z]{2,4}[0-9]{1,3}")


class MailchimpAPIError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class MailchimpKeyRejected(MailchimpAPIError):
    """The key is wrong, revoked, or belongs to another data center."""


class MailchimpNotFound(MailchimpAPIError):
    """The audience, template or campaign is gone."""


class MailchimpRateLimited(MailchimpAPIError):
    """Mailchimp kept answering 429 after the client waited."""


@frozen
class MailchimpPage:
    items: list[dict[str, Any]]
    total: int


def data_center(api_key: str) -> str | None:
    """The data center a key belongs to, such as us21, or None when the key has no valid suffix."""
    _, separator, suffix = api_key.rpartition("-")
    return suffix if separator and _DATA_CENTER.fullmatch(suffix) else None


def quoted(segment: str) -> str:
    return quote(segment, safe="")


class MailchimpClient:
    def __init__(
        self,
        api_key: str,
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
        max_rate_limit_waits: int = MAX_RATE_LIMIT_WAITS,
    ):
        center = data_center(api_key)
        if center is None:
            raise MailchimpKeyRejected("The Mailchimp key has no data center suffix.")
        self._api_key = api_key
        self._base_url = settings.MESSAGING_MAILCHIMP_API_URL.format(dc=center).rstrip("/")
        self._timeout = timeout
        self._max_rate_limit_waits = max_rate_limit_waits
        self._next_request_at = 0.0

    def __repr__(self) -> str:
        return "MailchimpClient()"

    def page(self, path: str, items_key: str, offset: int, params: dict[str, Any] | None = None) -> MailchimpPage:
        body = self.get(path, {**(params or {}), "count": PAGE_SIZE, "offset": offset})
        items = body.get(items_key)
        if items is None:
            items = []
        if not isinstance(items, list):
            raise MailchimpAPIError("Mailchimp sent an unexpected response.")
        total = body.get("total_items")
        # Without the total, paging can't tell the last page, so a short read would pass as the whole list.
        if not isinstance(total, int) or isinstance(total, bool):
            raise MailchimpAPIError("Mailchimp sent an unexpected response.")
        return MailchimpPage(items=[item for item in items if isinstance(item, dict)], total=total)

    def all(
        self, path: str, items_key: str, params: dict[str, Any] | None = None, *, whole: bool = False
    ) -> list[dict[str, Any]]:
        """With `whole`, a list that ends before Mailchimp's count of it raises."""
        rows: list[dict[str, Any]] = []
        while True:
            page = self.page(path, items_key, len(rows), params)
            rows.extend(page.items)
            if whole and len(rows) > page.total:
                raise MailchimpAPIError("Mailchimp sent an unexpected response.")
            if len(rows) >= page.total:
                return rows
            if not page.items:
                if whole:
                    raise MailchimpAPIError("Mailchimp sent an unexpected response.")
                return rows

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        headers = {"User-Agent": USER_AGENT, "Authorization": f"Bearer {self._api_key}"}
        waits = 0
        # A client that doesn't wait out a rate limit, like the key check, doesn't retry either.
        retries_left = MAX_TRANSIENT_RETRIES if self._max_rate_limit_waits else 0
        while True:
            self._pace()
            try:
                response = requests.get(
                    f"{self._base_url}/3.0{path}",
                    params=params,
                    headers=headers,
                    timeout=self._timeout,
                    allow_redirects=False,
                )
            except requests.RequestException as e:
                if retries_left:
                    time.sleep(TRANSIENT_RETRY_BASE_SECONDS ** (MAX_TRANSIENT_RETRIES - retries_left + 1))
                    retries_left -= 1
                    continue
                # The exception text can hold the request's details, so only its type leaves this function.
                raise MailchimpAPIError(f"Couldn't reach Mailchimp ({type(e).__name__}).") from None
            if response.status_code == 429:
                if waits >= self._max_rate_limit_waits:
                    raise MailchimpRateLimited("Mailchimp asked PostHog to slow down.", status_code=429)
                waits += 1
                time.sleep(_retry_after_seconds(response) or min(2**waits, MAX_WAIT_SECONDS))
                continue
            if response.status_code >= 500 and retries_left:
                time.sleep(TRANSIENT_RETRY_BASE_SECONDS ** (MAX_TRANSIENT_RETRIES - retries_left + 1))
                retries_left -= 1
                continue
            return _parse(response)

    def _pace(self) -> None:
        now = time.monotonic()
        if now < self._next_request_at:
            time.sleep(self._next_request_at - now)
        self._next_request_at = max(now, self._next_request_at) + 1 / REQUESTS_PER_SECOND


def _retry_after_seconds(response: requests.Response) -> float | None:
    # Mailchimp doesn't document Retry-After, so it's read only when a proxy in front of the API sends it.
    try:
        seconds = float(response.headers.get("Retry-After", ""))
    except ValueError:
        return None
    return min(max(seconds, 0.0), MAX_WAIT_SECONDS) or None


def _parse(response: requests.Response) -> dict[str, Any]:
    status = response.status_code
    if status in (401, 403):
        raise MailchimpKeyRejected("Mailchimp rejected the key.", status_code=status)
    if status == 404:
        raise MailchimpNotFound("Mailchimp couldn't find this.", status_code=status)
    if not response.ok:
        raise MailchimpAPIError(f"Mailchimp returned HTTP {status}.", status_code=status)
    try:
        body = response.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        raise MailchimpAPIError("Mailchimp sent an unexpected response.", status_code=status)
    return body
