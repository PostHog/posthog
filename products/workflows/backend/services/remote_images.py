"""Downloads an email image from a third-party host, bounded in size and time, without following redirects."""

import time
from dataclasses import dataclass
from http.client import HTTPException

import requests
from urllib3.exceptions import HTTPError as Urllib3HTTPError

_TIMEOUT_SECONDS = 10


@dataclass(frozen=True)
class FetchedImage:
    content: bytes | None
    # The HTTP status, or None when no response arrived.
    status: int | None
    # Why there is no content: "status", "too_large", "too_slow", or the network error's class name.
    failure: str | None


def fetch_image(url: str, *, deadline: float, max_bytes: int) -> FetchedImage:
    """The caller checks the host first: this follows no redirects, so the host checked is the host read."""
    try:
        with requests.get(
            url,
            timeout=_TIMEOUT_SECONDS,
            allow_redirects=False,
            stream=True,
            headers={"Accept-Encoding": "identity"},
        ) as response:
            if response.status_code != 200:
                return FetchedImage(content=None, status=response.status_code, failure="status")
            # `read1` returns what one socket read gives, so a host that sends a byte at a time can't hold the
            # thread past the deadline. A buffered read waits until it has the whole chunk.
            read = getattr(getattr(response.raw, "_fp", None), "read1", None) or response.raw.read
            content = b""
            while chunk := read(16 * 1024):
                content += chunk
                if len(content) > max_bytes:
                    return FetchedImage(content=None, status=200, failure="too_large")
                if time.monotonic() > deadline:
                    return FetchedImage(content=None, status=200, failure="too_slow")
            return FetchedImage(content=content, status=200, failure=None)
    # The raw read raises socket and HTTP errors itself, outside what requests wraps.
    except (requests.RequestException, OSError, HTTPException, Urllib3HTTPError) as error:
        return FetchedImage(content=None, status=None, failure=type(error).__name__)
