import time
import codecs
from collections.abc import Callable
from email.message import Message
from http.client import HTTPException

import requests
import structlog

from posthog.dataclasses import frozen
from posthog.security.pinned_requests import SSRFBlockedError, pinned_session
from posthog.security.url_validation import strip_userinfo

from products.messaging.backend.services.website_brand import absolute_http_url

logger = structlog.get_logger(__name__)

_MAX_REDIRECTS = 3
_CONNECT_TIMEOUT_SECONDS = 3.0
_READ_TIMEOUT_SECONDS = 5.0
_READ_CHUNK_BYTES = 64 * 1024
_UNCOMPRESSED_ENCODINGS = frozenset({"", "identity"})
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_USER_AGENT = "Mozilla/5.0 (compatible; PostHogBrandDetector/1.0; +https://posthog.com)"


class WebsiteFetchError(Exception):
    pass


@frozen
class ByteLimit:
    max_bytes: int
    keep_prefix: bool = False


@frozen
class FetchedResource:
    url: str
    content_type: str
    charset: str | None
    body: bytes

    def text(self) -> str:
        return self.body.decode(self.charset or "utf-8", errors="replace")


def fetch_public_resource(url: str, *, accept: str, limit: ByteLimit, deadline: float) -> FetchedResource:
    current = url
    for _hop in range(_MAX_REDIRECTS + 1):
        outcome = _fetch_one_hop(current, accept=accept, limit=limit, deadline=deadline)
        if isinstance(outcome, FetchedResource):
            return outcome
        current = _next_hop(current, redirect_location=outcome)
    raise WebsiteFetchError("too_many_redirects")


def _fetch_one_hop(url: str, *, accept: str, limit: ByteLimit, deadline: float) -> FetchedResource | str:
    remaining = _remaining_seconds(deadline)
    try:
        with pinned_session(url) as session:
            response = session.get(
                url,
                headers={"User-Agent": _USER_AGENT, "Accept": accept, "Accept-Encoding": "identity"},
                timeout=(min(_CONNECT_TIMEOUT_SECONDS, remaining), min(_READ_TIMEOUT_SECONDS, remaining)),
                allow_redirects=False,
                stream=True,
            )
            with response:
                return _read_response(response, url=url, limit=limit, deadline=deadline)
    except SSRFBlockedError as error:
        logger.info("messaging.website_fetch.blocked", reason=str(error))
        raise WebsiteFetchError("blocked") from error
    except requests.RequestException as error:
        logger.info("messaging.website_fetch.transport_failed", error_type=type(error).__name__)
        raise WebsiteFetchError("transport") from error
    except ValueError as error:
        logger.info("messaging.website_fetch.malformed_url")
        raise WebsiteFetchError("malformed_url") from error
    except (OSError, HTTPException) as error:
        logger.info("messaging.website_fetch.read_failed", error_type=type(error).__name__)
        raise WebsiteFetchError("read_failed") from error


def _read_response(
    response: requests.Response, *, url: str, limit: ByteLimit, deadline: float
) -> FetchedResource | str:
    if response.status_code in _REDIRECT_STATUSES:
        location = response.headers.get("Location")
        if not location:
            raise WebsiteFetchError("redirect_without_location")
        return location
    if not 200 <= response.status_code < 300:
        raise WebsiteFetchError(f"status_{response.status_code}")
    if response.headers.get("Content-Encoding", "").strip().lower() not in _UNCOMPRESSED_ENCODINGS:
        raise WebsiteFetchError("compressed")
    declared_size = response.headers.get("Content-Length", "")
    if not limit.keep_prefix and declared_size.isdigit() and int(declared_size) > limit.max_bytes:
        raise WebsiteFetchError("too_large")
    content_type, charset = _parse_content_type(response.headers.get("Content-Type", ""))
    body = _read_limited(_available_bytes_reader(response), limit, deadline)
    return FetchedResource(url=url, content_type=content_type, charset=charset, body=body)


def _parse_content_type(header: str) -> tuple[str, str | None]:
    message = Message()
    message["Content-Type"] = header
    return (message.get_content_type() if header else ""), _text_charset(message.get_content_charset())


def _text_charset(charset: str | None) -> str | None:
    if not charset:
        return None
    try:
        name = codecs.lookup(charset).name
        str(b"x", name, "replace")
    except LookupError:
        return None
    return name


def _available_bytes_reader(response: requests.Response) -> Callable[[int], bytes]:
    raw = response.raw
    read_available = getattr(raw, "read1", None) or getattr(getattr(raw, "_fp", None), "read1", None)
    if read_available is None:
        raise WebsiteFetchError("unreadable")
    return read_available


def _read_limited(read_available: Callable[[int], bytes], limit: ByteLimit, deadline: float) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while chunk := read_available(_READ_CHUNK_BYTES):
        _remaining_seconds(deadline)
        total += len(chunk)
        if total > limit.max_bytes:
            if not limit.keep_prefix:
                raise WebsiteFetchError("too_large")
            chunks.append(chunk[: len(chunk) - (total - limit.max_bytes)])
            break
        chunks.append(chunk)
    return b"".join(chunks)


def _next_hop(current: str, *, redirect_location: str) -> str:
    next_url = absolute_http_url(current, redirect_location)
    if next_url is None:
        raise WebsiteFetchError("unsupported_redirect")
    try:
        return strip_userinfo(next_url)
    except ValueError as error:
        raise WebsiteFetchError("unsupported_redirect") from error


def _remaining_seconds(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise WebsiteFetchError("deadline")
    return remaining
