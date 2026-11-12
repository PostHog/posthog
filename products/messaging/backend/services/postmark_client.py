"""Read-only client for Postmark's API, used by the provider import. See https://postmarkapp.com/developer/api/overview.

The customer owns the token, so per /routing-outbound-api-calls this honors 429 here rather than going through
`posthog/egress/`. Postmark publishes no request limit and says only to slow down on a 429, so the import stays at a low
rate to leave room for the customer's live sending.
"""

import enum
import json
import time
from collections.abc import Iterator
from dataclasses import field
from typing import Any

from django.conf import settings

import requests

from posthog.dataclasses import frozen

PAGE_SIZE = 100
REQUESTS_PER_SECOND = 2
MAX_RATE_LIMIT_WAITS = 5
MAX_RATE_LIMIT_WAIT_SECONDS = 60
DEFAULT_TIMEOUT_SECONDS = 30
# A suppression dump has no pages, so one response holds the whole list.
DUMP_TIMEOUT_SECONDS = 120
# The import worker is shared, so a list bigger than this stops the step instead of using up the worker's memory.
MAX_DUMP_BYTES = 100 * 1024 * 1024
USER_AGENT = "posthog-messaging-import/1.0"
# Postmark's code for a token that can't use the message streams API.
NO_STREAMS_PERMISSION_CODE = 1220
# Postmark's code for a template or layout that doesn't exist.
TEMPLATE_NOT_FOUND_CODE = 1101


class PostmarkAPIError(Exception):
    def __init__(self, message: str, status_code: int | None = None, error_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code


class PostmarkTokenRejected(PostmarkAPIError):
    """The token is wrong, revoked, or of the wrong kind for this endpoint."""


class PostmarkTokenCannotRead(PostmarkTokenRejected):
    """The token is real but its user doesn't have access to this data."""


class PostmarkRateLimited(PostmarkAPIError):
    """Postmark kept answering 429 after the client waited."""


class PostmarkResponseTooLarge(PostmarkAPIError):
    """The response was bigger than the caller allows."""


class TokenKind(enum.Enum):
    SERVER = "X-Postmark-Server-Token"
    ACCOUNT = "X-Postmark-Account-Token"


@frozen
class PostmarkServer:
    id: int
    name: str
    delivery_type: str
    settings: dict[str, Any]
    # None when the account token's user can't see this server's tokens.
    token: str | None = field(repr=False)


class _Pace:
    """Shared by a client and the clients it makes per server, so a whole import holds to one rate."""

    def __init__(self) -> None:
        self._next_request_at = 0.0

    def wait(self) -> None:
        now = time.monotonic()
        if now < self._next_request_at:
            time.sleep(self._next_request_at - now)
        self._next_request_at = max(now, self._next_request_at) + 1 / REQUESTS_PER_SECOND


class PostmarkClient:
    def __init__(
        self,
        token: str,
        kind: TokenKind,
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
        max_rate_limit_waits: int = MAX_RATE_LIMIT_WAITS,
        pace: _Pace | None = None,
    ):
        self._token = token
        self.kind = kind
        self._timeout = timeout
        self._max_rate_limit_waits = max_rate_limit_waits
        self._pace = pace or _Pace()

    def __repr__(self) -> str:
        return f"PostmarkClient({self.kind.name})"

    def for_server(self, server: PostmarkServer) -> "PostmarkClient":
        if not server.token:
            raise PostmarkTokenCannotRead(f"Postmark shares no token for the server {server.name}.")
        return PostmarkClient(
            server.token, TokenKind.SERVER, self._timeout, self._max_rate_limit_waits, pace=self._pace
        )

    def servers(self) -> list[PostmarkServer]:
        """A server token sees its own server. An account token sees every server in the account, oldest first."""
        if self.kind == TokenKind.SERVER:
            return [_to_server(self.get("/server"), self._token)]
        rows = self.offset_pages("/servers", "Servers", {}, count_param="count", offset_param="offset")
        servers = [_to_server(row, _first_token(row)) for page, _next in rows for row in page]
        return sorted(servers, key=lambda server: server.id)

    def offset_pages(
        self,
        path: str,
        items_key: str,
        params: dict[str, Any],
        *,
        offset: int = 0,
        count_param: str = "Count",
        offset_param: str = "Offset",
    ) -> Iterator[tuple[list[dict[str, Any]], int | None]]:
        """Yields each page and the offset of the next one, which is None on the last page."""
        while True:
            body = self.get(path, {**params, count_param: PAGE_SIZE, offset_param: offset})
            rows = body.get(items_key)
            total = body.get("TotalCount")
            if not isinstance(rows, list) or not isinstance(total, int):
                raise PostmarkAPIError(f"Postmark sent an unexpected response for {path}.")
            next_offset = offset + len(rows)
            # An empty page ends the list even when the total says otherwise, so a wrong total can't loop forever.
            done = not rows or next_offset >= total
            yield rows, None if done else next_offset
            if done:
                return
            offset = next_offset

    def get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        timeout: int | None = None,
        max_bytes: int | None = None,
    ) -> dict[str, Any]:
        waits = 0
        while True:
            self._pace.wait()
            try:
                response = requests.get(
                    f"{settings.MESSAGING_POSTMARK_API_URL}{path}",
                    params=params,
                    headers={
                        "Accept": "application/json",
                        self.kind.value: self._token,
                        "User-Agent": USER_AGENT,
                    },
                    timeout=timeout or self._timeout,
                    allow_redirects=False,
                    stream=max_bytes is not None,
                )
                content = _read_capped(response, max_bytes) if max_bytes is not None else None
            except requests.RequestException as e:
                # The exception text can hold the request's details, so only its type leaves this function.
                raise PostmarkAPIError(f"Couldn't reach Postmark ({type(e).__name__}).") from None
            if response.status_code == 429:
                if waits >= self._max_rate_limit_waits:
                    raise PostmarkRateLimited("Postmark asked PostHog to slow down.", status_code=429)
                time.sleep(_rate_limit_wait_seconds(response, waits))
                waits += 1
                continue
            return _parse(response, content)


def _read_capped(response: requests.Response, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    size = 0
    with response:
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            size += len(chunk)
            if size > max_bytes:
                raise PostmarkResponseTooLarge("Postmark sent more data than PostHog reads in one response.")
            chunks.append(chunk)
    return b"".join(chunks)


def identify_token(
    token: str, timeout: int = DEFAULT_TIMEOUT_SECONDS, max_rate_limit_waits: int = MAX_RATE_LIMIT_WAITS
) -> PostmarkClient:
    """Finds which kind of token this is. Postmark answers 401 to a token of the wrong kind, so it takes up to two reads.

    Raises PostmarkTokenRejected when neither kind works.
    """
    pace = _Pace()
    server_client = PostmarkClient(token, TokenKind.SERVER, timeout, max_rate_limit_waits, pace)
    try:
        server_client.get("/server")
        return server_client
    except PostmarkTokenCannotRead:
        raise
    except PostmarkTokenRejected:
        pass
    account_client = PostmarkClient(token, TokenKind.ACCOUNT, timeout, max_rate_limit_waits, pace)
    account_client.get("/servers", {"count": 1, "offset": 0})
    return account_client


def _to_server(row: dict[str, Any], token: str | None) -> PostmarkServer:
    # `ApiTokens` stays out of `settings`, because item notes read from it and the run stores those notes.
    return PostmarkServer(
        id=int(row.get("ID") or 0),
        name=str(row.get("Name") or row.get("ID") or ""),
        delivery_type=str(row.get("DeliveryType") or "Live"),
        settings={key: value for key, value in row.items() if key != "ApiTokens"},
        token=token,
    )


def _first_token(row: dict[str, Any]) -> str | None:
    tokens = row.get("ApiTokens")
    return str(tokens[0]) if isinstance(tokens, list) and tokens else None


def _rate_limit_wait_seconds(response: requests.Response, waits: int) -> float:
    """Postmark's docs give no wait time for a 429, so without a `Retry-After` the wait doubles each time."""
    try:
        seconds = float(response.headers["retry-after"])
    except (KeyError, ValueError):
        seconds = float(2**waits)
    return min(max(seconds, 0.0), MAX_RATE_LIMIT_WAIT_SECONDS)


def _parse(response: requests.Response, content: bytes | None = None) -> dict[str, Any]:
    try:
        body = json.loads(content) if content is not None else response.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        body = {}
    if response.ok:
        return body
    status = response.status_code
    error_code = body.get("ErrorCode")
    error_code = error_code if isinstance(error_code, int) else None
    if status == 401:
        raise PostmarkTokenRejected("Postmark rejected the token.", status_code=status, error_code=error_code)
    if status == 403 or error_code == NO_STREAMS_PERMISSION_CODE:
        raise PostmarkTokenCannotRead("The token can't read this data.", status_code=status, error_code=error_code)
    code_text = f", error code {error_code}" if error_code is not None else ""
    raise PostmarkAPIError(f"Postmark returned HTTP {status}{code_text}.", status_code=status, error_code=error_code)
