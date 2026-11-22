"""Read-only client for Resend's API, used by the provider import. See https://resend.com/docs/api-reference.

The customer owns the key, so per /routing-outbound-api-calls this honors `retry-after` here rather than going
through `posthog/egress/`. Resend shares one rate limit across all of a team's keys, so the import paces itself from
the rate limit headers on each response and leaves part of the limit for the customer's live sending.
"""

import re
import time
import threading
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import FIRST_EXCEPTION, ThreadPoolExecutor, wait
from typing import Any, TypeVar

from django.conf import settings

import requests

from posthog.dataclasses import frozen

PAGE_SIZE = 100
REQUESTS_PER_SECOND = 2
# Resend's limit is shared with the customer's live sends, so the import uses only this much of it.
SHARE_OF_LIMIT = 0.8
# A 429 or a full window means live sending needs more of the limit, so the import halves its share and wins it back
# over a few hundred requests.
MIN_SHARE_OF_LIMIT = 0.1
SHARE_REGAINED_PER_REQUEST = 0.002
# A request takes longer than the limit allows between requests, so the one-per-contact reads overlap.
MAX_PARALLEL_REQUESTS = 4
MAX_RATE_LIMIT_WAITS = 5
MAX_RETRY_AFTER_SECONDS = 60
# A long contact scan sees the odd timeout or 5xx. Retrying here keeps them from using up the whole step's retries.
MAX_TRANSIENT_RETRIES = 3
TRANSIENT_RETRY_BASE_SECONDS = 2
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


T = TypeVar("T")
R = TypeVar("R")


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
        max_transient_retries: int = MAX_TRANSIENT_RETRIES,
    ):
        self._api_key = api_key
        self._timeout = timeout
        self._max_rate_limit_waits = max_rate_limit_waits
        self._max_transient_retries = max_transient_retries
        self._next_request_at = 0.0
        self._paused_until = 0.0
        self._interval = 1 / REQUESTS_PER_SECOND
        self._share = SHARE_OF_LIMIT
        self._share_cut_at = float("-inf")
        self._longest_reset = 0
        self._lock = threading.Lock()

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

    def each(self, read: Callable[[T], R], items: Iterable[T]) -> list[R]:
        """`read` for every item, a few at a time, in the order of `items`. The first error is raised."""
        with ThreadPoolExecutor(max_workers=MAX_PARALLEL_REQUESTS) as pool:
            futures = [pool.submit(read, item) for item in items]
            done, _ = wait(futures, return_when=FIRST_EXCEPTION)
            errors = [error for future in futures if future in done and (error := future.exception())]
            if errors:
                # A rejected key or a rate limit fails every read, so the rest of the page must not keep sending.
                pool.shutdown(cancel_futures=True)
                raise errors[0]
            return [future.result() for future in futures]

    def _get(self, path: str, params: dict[str, Any] | None) -> dict[str, Any]:
        waits = 0
        retries = 0
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
                if retries < self._max_transient_retries:
                    retries += 1
                    time.sleep(TRANSIENT_RETRY_BASE_SECONDS**retries)
                    continue
                # The exception text can hold the request's details, so only its type leaves this function.
                raise ResendAPIError(f"Couldn't reach Resend ({type(e).__name__}).") from None
            self._follow_limit(response)
            if response.status_code == 429:
                if waits >= self._max_rate_limit_waits:
                    raise ResendRateLimited("Resend asked PostHog to slow down.", status_code=429)
                waits += 1
                self._pause(_retry_after_seconds(response))
                continue
            if response.status_code >= 500 and retries < self._max_transient_retries:
                retries += 1
                time.sleep(TRANSIENT_RETRY_BASE_SECONDS**retries)
                continue
            return _parse(response)

    def _pace(self) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                start_at = max(now, self._next_request_at)
                self._next_request_at = start_at + self._interval
            if start_at > now:
                time.sleep(start_at - now)
            # Another request can hit a full window while this one waits for its time, and then this one waits too.
            with self._lock:
                paused_for = self._paused_until - time.monotonic()
            if paused_for <= 0:
                return
            time.sleep(paused_for)

    def _pause(self, seconds: float) -> None:
        """Holds every request, including those already waiting for their time, for `seconds`."""
        with self._lock:
            self._hold_until(time.monotonic() + seconds)
        time.sleep(seconds)

    def _hold_until(self, moment: float) -> None:
        self._paused_until = max(self._paused_until, moment)
        self._next_request_at = max(self._next_request_at, moment)

    def _follow_limit(self, response: requests.Response) -> None:
        limit = _int_header(response, "ratelimit-limit")
        if not limit or limit < 1:
            return
        window = _policy_window_seconds(response)
        reset = min(_int_header(response, "ratelimit-reset") or 0, MAX_RETRY_AFTER_SECONDS)
        remaining = _int_header(response, "ratelimit-remaining")
        squeezed = response.status_code == 429 or remaining == 0
        with self._lock:
            if window is None:
                if not reset or reset < 1:
                    self._interval = max(self._interval, 1 / REQUESTS_PER_SECOND)
                    return
                # Seconds until the reset is never longer than the window, so the longest one seen is the safest guess.
                self._longest_reset = max(self._longest_reset, reset)
                window = float(self._longest_reset)
            now = time.monotonic()
            # Parallel requests in one window all see the same full window, and that is one sign, not several.
            if squeezed and now - self._share_cut_at >= window:
                self._share = max(self._share / 2, MIN_SHARE_OF_LIMIT)
                self._share_cut_at = now
            elif not squeezed:
                self._share = min(self._share + SHARE_REGAINED_PER_REQUEST, SHARE_OF_LIMIT)
            self._interval = window / (limit * self._share)
            if remaining == 0:
                self._hold_until(now + min(float(reset or window), MAX_RETRY_AFTER_SECONDS))


def _int_header(response: requests.Response, name: str) -> int | None:
    try:
        return int(str(response.headers.get(name, "")).strip())
    except ValueError:
        return None


def _policy_window_seconds(response: requests.Response) -> float | None:
    match = re.search(r"w=(\d+)", str(response.headers.get("ratelimit-policy", "")))
    try:
        seconds = int(match.group(1)) if match else 0
    except ValueError:
        return None
    return float(min(seconds, MAX_RETRY_AFTER_SECONDS)) if seconds > 0 else None


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
