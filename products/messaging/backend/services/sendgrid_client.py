"""Read-only client for SendGrid's v3 API, used by the provider import.

See https://www.twilio.com/docs/sendgrid/api-reference. The customer owns the key, so per /routing-outbound-api-calls
this honors SendGrid's rate limit headers here rather than going through `posthog/egress/`.
"""

import json
import time
from collections.abc import Iterator
from typing import Any
from urllib.parse import parse_qs, urlparse

from django.conf import settings

import requests

from posthog.dataclasses import frozen

# SendGrid's documented maximum for the suppression lists.
SUPPRESSION_PAGE_SIZE = 500
TEMPLATE_PAGE_SIZE = 200
# Each endpoint has its own limit that SendGrid doesn't publish, and the customer's live sending shares the account.
REQUESTS_PER_SECOND = 2
MAX_RATE_LIMIT_WAITS = 5
# A long import sees the odd timeout or 5xx. Retrying here keeps them from using up the whole step's retries.
MAX_TRANSIENT_RETRIES = 3
TRANSIENT_RETRY_BASE_SECONDS = 2
MAX_RATE_LIMIT_WAIT_SECONDS = 120
DEFAULT_RATE_LIMIT_WAIT_SECONDS = 5.0
RELATIVE_RESET_LIMIT_SECONDS = 86_400
DEFAULT_TIMEOUT_SECONDS = 30
MAX_RESPONSE_BYTES = 100 * 1024 * 1024
RESPONSE_CHUNK_BYTES = 1024 * 1024
USER_AGENT = "posthog-messaging-import/1.0"


class SendGridAPIError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class SendGridKeyRejected(SendGridAPIError):
    """The key is wrong, deleted or disabled."""


class SendGridScopeMissing(SendGridAPIError):
    """SendGrid accepts the key but won't let it read this path."""

    def __init__(self, path: str):
        super().__init__(f"SendGrid refused to let this key read {path}.", status_code=403)
        self.path = path


class SendGridResponseTooLarge(SendGridAPIError):
    """A response past MAX_RESPONSE_BYTES, such as an unsubscribe group too large for one import."""


class SendGridRateLimited(SendGridAPIError):
    """SendGrid kept answering 429 after the client waited as long as it said to."""


@frozen
class SendGridPage:
    data: list[Any]
    # Where the next page starts, or None on the last page. An int for offset paging, a string for token paging.
    next_position: str | int | None


class SendGridClient:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
        max_rate_limit_waits: int = MAX_RATE_LIMIT_WAITS,
    ):
        self._api_key = api_key
        self._base_url = base_url
        self._timeout = timeout
        self._max_rate_limit_waits = max_rate_limit_waits
        self._next_request_at = 0.0

    def __repr__(self) -> str:
        return "SendGridClient()"

    def scopes(self) -> set[str]:
        body = self.get("/v3/scopes")
        scopes = body.get("scopes") if isinstance(body, dict) else None
        if not isinstance(scopes, list):
            raise SendGridAPIError("SendGrid sent an unexpected response for /v3/scopes.")
        return {str(scope) for scope in scopes}

    def offset_pages(
        self, path: str, offset: int = 0, page_size: int = SUPPRESSION_PAGE_SIZE, params: dict[str, Any] | None = None
    ) -> Iterator[SendGridPage]:
        """Pages of an endpoint that answers with a bare array. A short page is the last one."""
        while True:
            data = self.get(path, {**(params or {}), "limit": page_size, "offset": offset})
            if not isinstance(data, list):
                raise SendGridAPIError(f"SendGrid sent an unexpected response for {path}.")
            offset += len(data)
            yield SendGridPage(data=data, next_position=offset if len(data) == page_size else None)
            if len(data) < page_size:
                return

    def token_pages(self, path: str, page_token: str | None, page_size: int, **params: Any) -> Iterator[SendGridPage]:
        """Pages of an endpoint that answers `{"result": [...], "_metadata": {"next": url}}`."""
        token = page_token
        while True:
            query: dict[str, Any] = {**params, "page_size": page_size}
            if token:
                query["page_token"] = token
            body = self.get(path, query)
            data = body.get("result") if isinstance(body, dict) else None
            if not isinstance(data, list):
                raise SendGridAPIError(f"SendGrid sent an unexpected response for {path}.")
            next_token = _next_page_token(body)
            if next_token is not None and next_token == token:
                raise SendGridAPIError(f"SendGrid sent the same page twice for {path}.")
            yield SendGridPage(data=data, next_position=next_token)
            if next_token is None:
                return
            token = next_token

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        waits = 0
        # A client that doesn't wait out a rate limit, like the key check, doesn't retry either.
        retries_left = MAX_TRANSIENT_RETRIES if self._max_rate_limit_waits else 0
        while True:
            self._pace()
            try:
                response = requests.get(
                    f"{self._base_url}{path}",
                    params=params,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Accept": "application/json",
                        "User-Agent": USER_AGENT,
                    },
                    timeout=self._timeout,
                    allow_redirects=False,
                    stream=True,
                )
            except requests.RequestException as e:
                if retries_left:
                    time.sleep(TRANSIENT_RETRY_BASE_SECONDS ** (MAX_TRANSIENT_RETRIES - retries_left + 1))
                    retries_left -= 1
                    continue
                # The exception text can hold the request's details, so only its type leaves this function.
                raise SendGridAPIError(f"Couldn't reach SendGrid ({type(e).__name__}).") from None
            if response.status_code == 429 or (response.status_code >= 500 and retries_left):
                # A response that is retried is never read, so its connection goes back now.
                response.close()
            if response.status_code == 429:
                if waits >= self._max_rate_limit_waits:
                    raise SendGridRateLimited("SendGrid asked PostHog to slow down.", status_code=429)
                waits += 1
                time.sleep(_seconds_until_reset(response))
                continue
            if response.status_code >= 500 and retries_left:
                time.sleep(TRANSIENT_RETRY_BASE_SECONDS ** (MAX_TRANSIENT_RETRIES - retries_left + 1))
                retries_left -= 1
                continue
            self._respect_exhausted_limit(response)
            try:
                return _parse(response, path)
            except requests.RequestException as e:
                # The body arrives after the headers, so a connection that drops while it streams is retried too.
                if retries_left:
                    time.sleep(TRANSIENT_RETRY_BASE_SECONDS ** (MAX_TRANSIENT_RETRIES - retries_left + 1))
                    retries_left -= 1
                    continue
                raise SendGridAPIError(f"Couldn't reach SendGrid ({type(e).__name__}).") from None
            finally:
                response.close()

    def _pace(self) -> None:
        now = time.monotonic()
        if now < self._next_request_at:
            time.sleep(self._next_request_at - now)
        self._next_request_at = max(now, self._next_request_at) + 1 / REQUESTS_PER_SECOND

    def _respect_exhausted_limit(self, response: requests.Response) -> None:
        if response.headers.get("X-RateLimit-Remaining") == "0":
            self._next_request_at = max(self._next_request_at, time.monotonic() + _seconds_until_reset(response))


def connect(
    api_key: str, timeout: int = DEFAULT_TIMEOUT_SECONDS, max_rate_limit_waits: int = MAX_RATE_LIMIT_WAITS
) -> tuple[SendGridClient, set[str]]:
    """A client on the host that accepts this key, with the key's scopes. A key of an EU subuser only works on the EU
    host and SendGrid has no call that says which host a key belongs to, so this asks each of them."""
    global_client = SendGridClient(api_key, settings.MESSAGING_SENDGRID_API_URL, timeout, max_rate_limit_waits)
    try:
        return global_client, global_client.scopes()
    except SendGridKeyRejected:
        eu_client = SendGridClient(api_key, settings.MESSAGING_SENDGRID_EU_API_URL, timeout, max_rate_limit_waits)
        return eu_client, eu_client.scopes()


def _next_page_token(body: dict[str, Any]) -> str | None:
    # Only the token leaves the response. PostHog never requests a URL SendGrid sends, because the key would go with it.
    next_url = (body.get("_metadata") or {}).get("next")
    if not isinstance(next_url, str) or not next_url:
        return None
    tokens = parse_qs(urlparse(next_url).query).get("page_token")
    if not tokens:
        raise SendGridAPIError("SendGrid sent a next page without a page token.")
    return tokens[0]


def _seconds_until_reset(response: requests.Response) -> float:
    try:
        reset = float(response.headers.get("X-RateLimit-Reset", ""))
    except ValueError:
        return DEFAULT_RATE_LIMIT_WAIT_SECONDS
    # Most endpoints send a Unix time, and the suppression lists send the seconds left in the window.
    wait = reset if reset < RELATIVE_RESET_LIMIT_SECONDS else reset - time.time()
    # A reset already in the past means the clocks disagree, so wait a moment rather than not at all.
    return min(max(wait, 1.0), MAX_RATE_LIMIT_WAIT_SECONDS)


def _parse(response: requests.Response, path: str) -> Any:
    status = response.status_code
    if status == 401:
        raise SendGridKeyRejected("SendGrid rejected the key.", status_code=status)
    if status == 403:
        raise SendGridScopeMissing(path)
    if not response.ok:
        raise SendGridAPIError(f"SendGrid returned HTTP {status}.", status_code=status)
    body = bytearray()
    # A group's unsubscribes come in one response with no paging, so its size is capped while it downloads.
    for chunk in response.iter_content(RESPONSE_CHUNK_BYTES):
        body += chunk
        if len(body) > MAX_RESPONSE_BYTES:
            raise SendGridResponseTooLarge(f"SendGrid's response for {path} is too large for one import.")
    try:
        return json.loads(body)
    except ValueError:
        raise SendGridAPIError(f"SendGrid sent an unexpected response for {path}.") from None
