import time
import urllib.parse as urlparse

from posthog.dataclasses import frozen
from posthog.security.url_validation import strip_userinfo

from products.web_analytics.backend.public_url_fetch import (
    PUBLIC_URL_REDIRECT_STATUSES,
    PublicUrlFetchError,
    PublicUrlFetchFailure,
    fetch_public_url,
)

LLMS_TXT_MAX_BYTES = 1024 * 1024
LLMS_TXT_MAX_REDIRECTS = 3
LLMS_TXT_CONNECT_TIMEOUT_SECONDS = 3.05
LLMS_TXT_READ_TIMEOUT_SECONDS = 10.0
LLMS_TXT_TOTAL_BUDGET_SECONDS = 20.0
LLMS_TXT_REJECTED_MEDIA_TYPES = frozenset({"text/html", "application/xhtml+xml"})
LLMS_TXT_FETCH_FAILURE_MESSAGES: dict[PublicUrlFetchFailure, str] = {
    "blocked": "Enter a publicly accessible HTTP or HTTPS URL.",
    "compressed": "The URL returned a compressed file. Serve llms.txt as plain text.",
    "deadline": "The file took too long to load.",
    "media_type": "The URL returned an HTML page instead of an llms.txt file.",
    "read": "Could not read the file.",
    "too_large": "The file is larger than 1 MB.",
    "transport": "Could not reach the URL.",
}


class LlmsTxtFetchError(Exception):
    pass


@frozen
class FetchedLlmsTxt:
    content: str
    url: str


def fetch_llms_txt(url: str) -> FetchedLlmsTxt:
    current_url = strip_userinfo(urlparse.urldefrag(url.strip())[0])
    # One budget for the whole chain: the read timeout bounds the gap between chunks, not the total
    # transfer, so a host that trickles bytes would otherwise hold a web worker indefinitely.
    deadline = time.monotonic() + LLMS_TXT_TOTAL_BUDGET_SECONDS

    for _redirect_count in range(LLMS_TXT_MAX_REDIRECTS + 1):
        try:
            response = fetch_public_url(
                current_url,
                headers={
                    "Accept": "text/plain,text/markdown;q=0.9,*/*;q=0.1",
                    "User-Agent": "PostHog llms.txt fetcher",
                },
                max_bytes=LLMS_TXT_MAX_BYTES,
                deadline=deadline,
                connect_timeout_seconds=LLMS_TXT_CONNECT_TIMEOUT_SECONDS,
                read_timeout_seconds=LLMS_TXT_READ_TIMEOUT_SECONDS,
                rejected_media_types=LLMS_TXT_REJECTED_MEDIA_TYPES,
            )
        except PublicUrlFetchError as error:
            raise LlmsTxtFetchError(LLMS_TXT_FETCH_FAILURE_MESSAGES[error.failure]) from error

        if response.status_code in PUBLIC_URL_REDIRECT_STATUSES:
            location = response.headers.get("location")
            if not location:
                raise LlmsTxtFetchError("The URL redirected without a destination.")
            current_url = strip_userinfo(urlparse.urljoin(current_url, location))
            continue

        if response.status_code < 200 or response.status_code >= 300:
            raise LlmsTxtFetchError(f"The URL returned HTTP {response.status_code}.")

        content = response.body.decode("utf-8-sig", errors="replace")
        if not content.strip():
            raise LlmsTxtFetchError("The file is empty.")
        return FetchedLlmsTxt(content=content, url=current_url)

    raise LlmsTxtFetchError("The URL redirected too many times.")
