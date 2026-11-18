"""Read-only client for Mailgun's API, used by the provider import.
See https://documentation.mailgun.com/docs/mailgun/api-reference/api-overview.

The customer owns the key, so per /routing-outbound-api-calls this honors rate limits here rather than going through
`posthog/egress/`. A request only ever goes to the configured host of its region: a `paging.next` URL contributes its
path and query, and never its host, so a wrong URL in a response can't send the key anywhere else.
"""

import time
from enum import StrEnum
from typing import Any
from urllib.parse import quote, urlsplit

from django.conf import settings

import requests

from posthog.dataclasses import frozen

SUPPRESSION_PAGE_SIZE = 1000
TEMPLATE_PAGE_SIZE = 100
DOMAIN_PAGE_SIZE = 1000
SUBACCOUNT_PAGE_SIZE = 100
# Mailgun doesn't publish a limit for these reads, and the windows vary by API, so stay gentle next to live sending.
REQUESTS_PER_SECOND = 2
MAX_RATE_LIMIT_WAITS = 5
# A long import sees the odd timeout or 5xx. Retrying here keeps them from using up the whole step's retries.
MAX_TRANSIENT_RETRIES = 3
TRANSIENT_RETRY_BASE_SECONDS = 2
MAX_WAIT_SECONDS = 60
DEFAULT_TIMEOUT_SECONDS = 30
USER_AGENT = "posthog-messaging-import/1.0"
ON_BEHALF_OF_HEADER = "X-Mailgun-On-Behalf-Of"
# Below this, X-RateLimit-Reset can't be an epoch timestamp, so it counts milliseconds from now.
_EPOCH_MILLISECONDS_FLOOR = 10**11


class MailgunRegion(StrEnum):
    US = "us"
    EU = "eu"


class MailgunAPIError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class MailgunKeyRejected(MailgunAPIError):
    """The key is wrong, can only send, or its role has no access to this data."""


class MailgunNotFound(MailgunAPIError):
    """The domain, list or template is gone. Mailgun says a 404 can also be temporary, because it's eventually consistent."""


class MailgunRateLimited(MailgunAPIError):
    """Mailgun kept answering 429 after the client waited as long as it told it to."""


@frozen
class MailgunPage:
    items: list[dict[str, Any]]
    # The path and query of the next page, or None on the last page.
    next_after: str | None


def _base_url(region: MailgunRegion) -> str:
    return (
        settings.MESSAGING_MAILGUN_EU_API_URL if region == MailgunRegion.EU else settings.MESSAGING_MAILGUN_US_API_URL
    )


def quoted(segment: str) -> str:
    return quote(segment, safe="")


class MailgunClient:
    def __init__(
        self,
        api_key: str,
        region: MailgunRegion,
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
        max_rate_limit_waits: int = MAX_RATE_LIMIT_WAITS,
    ):
        self._api_key = api_key
        self.region = region
        self._timeout = timeout
        self._max_rate_limit_waits = max_rate_limit_waits
        self._next_request_at = 0.0

    def __repr__(self) -> str:
        return f"MailgunClient({self.region})"

    def domains(self) -> list[dict[str, Any]]:
        """Every domain in this region, subaccounts included, in a stable order."""
        domains: list[dict[str, Any]] = []
        while True:
            body = self.get(
                "/v4/domains",
                {"limit": DOMAIN_PAGE_SIZE, "skip": len(domains), "sort": "name:asc", "include_subaccounts": "true"},
            )
            items = _items(body)
            domains.extend(items)
            if not items or len(domains) >= int(body.get("total_count") or 0):
                return domains

    def subaccount_ids(self) -> list[str]:
        """Open subaccounts this key can act for. A plan or key without subaccounts answers with an error, so none."""
        ids: list[str] = []
        skip = 0
        while True:
            try:
                body = self.get(
                    "/v5/accounts/subaccounts", {"limit": SUBACCOUNT_PAGE_SIZE, "skip": skip, "closed": "false"}
                )
            except (MailgunKeyRejected, MailgunNotFound):
                return ids
            except MailgunAPIError as e:
                if e.status_code == 400:
                    return ids
                raise
            rows = [row for row in body.get("subaccounts") or [] if isinstance(row, dict)]
            ids.extend(str(row["id"]) for row in rows if row.get("id") and row.get("status") in (None, "open"))
            skip += len(rows)
            if not rows or skip >= int(body.get("total") or 0):
                return ids

    def page(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        after: str | None = None,
        on_behalf_of: str | None = None,
    ) -> MailgunPage:
        if after and not _is_relative(after):
            raise MailgunAPIError("The saved Mailgun page isn't a path on Mailgun's API.")
        body = self.get(after, None, on_behalf_of) if after else self.get(path, params, on_behalf_of)
        items = _items(body)
        paging = body.get("paging")
        next_url = paging.get("next") if isinstance(paging, dict) else None
        next_after = _relative(next_url)
        # Mailgun's last page still names a next page, which comes back empty.
        if not items or next_after == after:
            next_after = None
        return MailgunPage(items=items, next_after=next_after)

    def versions(self, template_path: str, on_behalf_of: str | None = None) -> list[dict[str, Any]]:
        versions: list[dict[str, Any]] = []
        after: str | None = None
        params: dict[str, Any] | None = {"limit": TEMPLATE_PAGE_SIZE}
        while True:
            body = self.get(after or f"{template_path}/versions", None if after else params, on_behalf_of)
            template = body.get("template")
            rows = template.get("versions") if isinstance(template, dict) else None
            rows = [row for row in rows or [] if isinstance(row, dict)]
            versions.extend(rows)
            paging = body.get("paging")
            next_after = _relative(paging.get("next") if isinstance(paging, dict) else None)
            if not rows or not next_after or next_after == after:
                return versions
            after = next_after

    def get(
        self, path_and_query: str, params: dict[str, Any] | None = None, on_behalf_of: str | None = None
    ) -> dict[str, Any]:
        headers = {"User-Agent": USER_AGENT}
        if on_behalf_of:
            headers[ON_BEHALF_OF_HEADER] = on_behalf_of
        waits = 0
        # A client that doesn't wait out a rate limit, like the key check, doesn't retry either.
        retries_left = MAX_TRANSIENT_RETRIES if self._max_rate_limit_waits else 0
        while True:
            self._pace()
            try:
                response = requests.get(
                    f"{_base_url(self.region)}{path_and_query}",
                    params=params,
                    auth=("api", self._api_key),
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
                raise MailgunAPIError(f"Couldn't reach Mailgun ({type(e).__name__}).") from None
            if response.status_code == 429:
                if waits >= self._max_rate_limit_waits:
                    raise MailgunRateLimited("Mailgun asked PostHog to slow down.", status_code=429)
                waits += 1
                time.sleep(_reset_wait_seconds(response) or min(2**waits, MAX_WAIT_SECONDS))
                continue
            if response.status_code >= 500 and retries_left:
                time.sleep(TRANSIENT_RETRY_BASE_SECONDS ** (MAX_TRANSIENT_RETRIES - retries_left + 1))
                retries_left -= 1
                continue
            body = _parse(response)
            if _remaining(response) == 0 and self._max_rate_limit_waits:
                time.sleep(_reset_wait_seconds(response) or 1)
            return body

    def _pace(self) -> None:
        now = time.monotonic()
        if now < self._next_request_at:
            time.sleep(self._next_request_at - now)
        self._next_request_at = max(now, self._next_request_at) + 1 / REQUESTS_PER_SECOND


def _items(body: dict[str, Any]) -> list[dict[str, Any]]:
    # Mailgun documents `items` as "array | null" for an empty list.
    items = body.get("items")
    if items is None:
        return []
    if not isinstance(items, list):
        raise MailgunAPIError("Mailgun sent an unexpected response.")
    return [item for item in items if isinstance(item, dict)]


def _is_relative(path_and_query: str) -> bool:
    return path_and_query.startswith("/") and not path_and_query.startswith("//")


def _relative(url: Any) -> str | None:
    if not isinstance(url, str) or not url:
        return None
    parts = urlsplit(url)
    if not parts.path.startswith("/"):
        return None
    relative = f"{parts.path}?{parts.query}" if parts.query else parts.path
    return relative if _is_relative(relative) else None


def _remaining(response: requests.Response) -> int | None:
    try:
        return int(response.headers.get("X-RateLimit-Remaining", ""))
    except ValueError:
        return None


def _reset_wait_seconds(response: requests.Response) -> float | None:
    """How long X-RateLimit-Reset asks to wait. The docs say both "Unix milliseconds" and "until the limit resets", so
    this reads either an epoch timestamp or a duration."""
    try:
        reset = float(response.headers.get("X-RateLimit-Reset", ""))
    except ValueError:
        return None
    milliseconds = reset - time.time() * 1000 if reset >= _EPOCH_MILLISECONDS_FLOOR else reset
    return min(max(milliseconds / 1000, 0.0), MAX_WAIT_SECONDS) or None


def _parse(response: requests.Response) -> dict[str, Any]:
    status = response.status_code
    if status in (401, 403):
        raise MailgunKeyRejected("Mailgun rejected the key.", status_code=status)
    if status == 404:
        raise MailgunNotFound("Mailgun couldn't find this.", status_code=status)
    if not response.ok:
        raise MailgunAPIError(f"Mailgun returned HTTP {status}.", status_code=status)
    try:
        body = response.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        raise MailgunAPIError("Mailgun sent an unexpected response.", status_code=status)
    return body
