import time
import urllib.parse as urlparse

import requests
import structlog

from posthog.dataclasses import frozen
from posthog.security.pinned_requests import SSRFBlockedError, pinned_session
from posthog.security.url_validation import strip_userinfo

logger = structlog.get_logger(__name__)

LLMS_TXT_MAX_BYTES = 1024 * 1024
LLMS_TXT_MAX_REDIRECTS = 3
LLMS_TXT_CONNECT_TIMEOUT_SECONDS = 3.05
LLMS_TXT_READ_TIMEOUT_SECONDS = 10.0
LLMS_TXT_TOTAL_BUDGET_SECONDS = 20.0
LLMS_TXT_READ_CHUNK_BYTES = 64 * 1024
LLMS_TXT_REDIRECT_STATUSES = {301, 302, 303, 307, 308}
LLMS_TXT_ACCEPTED_CONTENT_ENCODINGS = {"", "identity"}


class LlmsTxtFetchError(Exception):
    pass


@frozen
class FetchedLlmsTxt:
    content: str
    url: str


def _read_once(response: requests.Response, amt: int) -> bytes:
    raw = response.raw
    read1 = getattr(raw, "read1", None) or getattr(getattr(raw, "_fp", None), "read1", None)
    if read1 is None:
        raise LlmsTxtFetchError("Could not read the file.")
    return bytes(read1(amt))


def _read_response_body(response: requests.Response, deadline: float) -> bytes:
    chunks: list[bytes] = []
    total_bytes = 0
    while True:
        if time.monotonic() > deadline:
            raise LlmsTxtFetchError("The file took too long to load.")
        chunk = _read_once(response, LLMS_TXT_READ_CHUNK_BYTES)
        if not chunk:
            return b"".join(chunks)
        total_bytes += len(chunk)
        if total_bytes > LLMS_TXT_MAX_BYTES:
            raise LlmsTxtFetchError("The file is larger than 1 MB.")
        chunks.append(chunk)


def fetch_llms_txt(url: str) -> FetchedLlmsTxt:
    current_url = strip_userinfo(urlparse.urldefrag(url.strip())[0])
    # One budget for the whole chain: the read timeout bounds the gap between chunks, not the total
    # transfer, so a host that trickles bytes would otherwise hold a web worker indefinitely.
    deadline = time.monotonic() + LLMS_TXT_TOTAL_BUDGET_SECONDS

    for _redirect_count in range(LLMS_TXT_MAX_REDIRECTS + 1):
        read_timeout = min(LLMS_TXT_READ_TIMEOUT_SECONDS, deadline - time.monotonic())
        if read_timeout <= 0:
            raise LlmsTxtFetchError("The file took too long to load.")
        try:
            with pinned_session(current_url) as session:
                response = session.get(
                    current_url,
                    headers={
                        "Accept": "text/plain,text/markdown;q=0.9,*/*;q=0.1",
                        # Undecoded, so the size cap counts what we actually read off the wire.
                        "Accept-Encoding": "identity",
                        "User-Agent": "PostHog llms.txt fetcher",
                    },
                    timeout=(LLMS_TXT_CONNECT_TIMEOUT_SECONDS, read_timeout),
                    allow_redirects=False,
                    stream=True,
                )
                try:
                    if response.status_code in LLMS_TXT_REDIRECT_STATUSES:
                        location = response.headers.get("Location")
                        if not location:
                            raise LlmsTxtFetchError("The URL redirected without a destination.")
                        current_url = strip_userinfo(urlparse.urljoin(current_url, location))
                        continue

                    if response.status_code < 200 or response.status_code >= 300:
                        raise LlmsTxtFetchError(f"The URL returned HTTP {response.status_code}.")

                    content_type = response.headers.get("Content-Type", "")
                    media_type = content_type.split(";", 1)[0].strip().lower()
                    if media_type in {"text/html", "application/xhtml+xml"}:
                        raise LlmsTxtFetchError("The URL returned an HTML page instead of an llms.txt file.")

                    content_encoding = response.headers.get("Content-Encoding", "").strip().lower()
                    if content_encoding not in LLMS_TXT_ACCEPTED_CONTENT_ENCODINGS:
                        raise LlmsTxtFetchError("The URL returned a compressed file. Serve llms.txt as plain text.")

                    body = _read_response_body(response, deadline)
                    content = body.decode("utf-8-sig", errors="replace")
                    if not content.strip():
                        raise LlmsTxtFetchError("The file is empty.")
                    return FetchedLlmsTxt(content=content, url=current_url)
                finally:
                    response.close()
        except SSRFBlockedError as error:
            logger.info("llms_txt.url_blocked", reason=str(error))
            raise LlmsTxtFetchError("Enter a publicly accessible HTTP or HTTPS URL.") from error
        except requests.RequestException as error:
            # Deliberately not logging the exception or the URL: both routinely echo the full target,
            # and a customer-supplied URL can carry credentials or a signed token.
            logger.info("llms_txt.request_failed")
            raise LlmsTxtFetchError("Could not reach the URL.") from error

    raise LlmsTxtFetchError("The URL redirected too many times.")
