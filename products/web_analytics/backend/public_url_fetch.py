import time
from typing import Literal

import requests
import structlog

from posthog.dataclasses import frozen
from posthog.security.pinned_requests import SSRFBlockedError, pinned_session

logger = structlog.get_logger(__name__)

PublicUrlFetchFailure = Literal["blocked", "compressed", "deadline", "media_type", "read", "too_large", "transport"]

PUBLIC_URL_READ_CHUNK_BYTES = 64 * 1024
PUBLIC_URL_ACCEPTED_CONTENT_ENCODINGS = {"", "identity"}
PUBLIC_URL_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


class PublicUrlFetchError(Exception):
    def __init__(self, failure: PublicUrlFetchFailure, message: str | None = None) -> None:
        self.failure = failure
        super().__init__(message or failure)


@frozen
class FetchedPublicUrl:
    status_code: int
    headers: dict[str, str]
    body: bytes


def _read_once(response: requests.Response, amount: int) -> bytes:
    raw = response.raw
    read_once = getattr(raw, "read1", None) or getattr(getattr(raw, "_fp", None), "read1", None)
    if read_once is None:
        raise PublicUrlFetchError("read")
    return bytes(read_once(amount))


def _read_response_body(response: requests.Response, *, deadline: float, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total_bytes = 0
    while True:
        if time.monotonic() > deadline:
            raise PublicUrlFetchError("deadline")
        chunk = _read_once(response, PUBLIC_URL_READ_CHUNK_BYTES)
        if time.monotonic() > deadline:
            raise PublicUrlFetchError("deadline")
        if not chunk:
            return b"".join(chunks)
        total_bytes += len(chunk)
        if total_bytes > max_bytes:
            raise PublicUrlFetchError("too_large")
        chunks.append(chunk)


def fetch_public_url(
    url: str,
    *,
    headers: dict[str, str],
    max_bytes: int,
    deadline: float,
    connect_timeout_seconds: float,
    read_timeout_seconds: float,
    rejected_media_types: frozenset[str] = frozenset(),
) -> FetchedPublicUrl:
    if max_bytes < 1:
        raise ValueError("max_bytes must be positive")

    remaining_seconds = deadline - time.monotonic()
    if remaining_seconds <= 0:
        raise PublicUrlFetchError("deadline")

    request_headers = {**headers, "Accept-Encoding": "identity"}
    try:
        with pinned_session(url) as session:
            response = session.get(
                url,
                headers=request_headers,
                timeout=(
                    min(connect_timeout_seconds, remaining_seconds),
                    min(read_timeout_seconds, remaining_seconds),
                ),
                allow_redirects=False,
                stream=True,
            )
            try:
                response_headers = {name.lower(): value for name, value in response.headers.items()}
                if not 200 <= response.status_code < 300:
                    return FetchedPublicUrl(status_code=response.status_code, headers=response_headers, body=b"")

                media_type = response_headers.get("content-type", "").split(";", 1)[0].strip().lower()
                if media_type in rejected_media_types:
                    raise PublicUrlFetchError("media_type")

                content_encoding = response_headers.get("content-encoding", "").strip().lower()
                if content_encoding not in PUBLIC_URL_ACCEPTED_CONTENT_ENCODINGS:
                    raise PublicUrlFetchError("compressed")

                declared_size = response_headers.get("content-length")
                if declared_size and declared_size.isdigit() and int(declared_size) > max_bytes:
                    raise PublicUrlFetchError("too_large")

                return FetchedPublicUrl(
                    status_code=response.status_code,
                    headers=response_headers,
                    body=_read_response_body(response, deadline=deadline, max_bytes=max_bytes),
                )
            finally:
                response.close()
    except SSRFBlockedError as error:
        logger.info("web_analytics.public_url_fetch.url_blocked", reason=str(error))
        raise PublicUrlFetchError("blocked") from error
    except requests.RequestException as error:
        # The exception and URL can contain credentials or signed query parameters, so neither is logged.
        logger.info("web_analytics.public_url_fetch.request_failed")
        raise PublicUrlFetchError("transport") from error
