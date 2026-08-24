import urllib.parse as urlparse

import requests

from posthog.dataclasses import frozen
from posthog.security.pinned_requests import SSRFBlockedError, pinned_session
from posthog.security.url_validation import strip_userinfo

LLMS_TXT_MAX_BYTES = 1024 * 1024
LLMS_TXT_MAX_REDIRECTS = 3
LLMS_TXT_TIMEOUT = (3.05, 10.0)
LLMS_TXT_REDIRECT_STATUSES = {301, 302, 303, 307, 308}


class LlmsTxtFetchError(Exception):
    pass


@frozen
class FetchedLlmsTxt:
    content: str
    url: str


def _read_response_body(response: requests.Response) -> bytes:
    chunks: list[bytes] = []
    total_bytes = 0
    for chunk in response.iter_content(chunk_size=64 * 1024):
        if not chunk:
            continue
        total_bytes += len(chunk)
        if total_bytes > LLMS_TXT_MAX_BYTES:
            raise LlmsTxtFetchError("The file is larger than 1 MB.")
        chunks.append(chunk)
    return b"".join(chunks)


def fetch_llms_txt(url: str) -> FetchedLlmsTxt:
    current_url = strip_userinfo(urlparse.urldefrag(url.strip())[0])

    for _redirect_count in range(LLMS_TXT_MAX_REDIRECTS + 1):
        try:
            with pinned_session(current_url) as session:
                response = session.get(
                    current_url,
                    headers={
                        "Accept": "text/plain,text/markdown;q=0.9,*/*;q=0.1",
                        "User-Agent": "PostHog llms.txt fetcher",
                    },
                    timeout=LLMS_TXT_TIMEOUT,
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

                    content_length = response.headers.get("Content-Length", "")
                    if content_length.isdigit() and int(content_length) > LLMS_TXT_MAX_BYTES:
                        raise LlmsTxtFetchError("The file is larger than 1 MB.")

                    body = _read_response_body(response)
                    content = body.decode("utf-8-sig", errors="replace")
                    if not content.strip():
                        raise LlmsTxtFetchError("The file is empty.")
                    return FetchedLlmsTxt(content=content, url=current_url)
                finally:
                    response.close()
        except SSRFBlockedError as error:
            raise LlmsTxtFetchError("Enter a publicly accessible HTTP or HTTPS URL.") from error
        except requests.RequestException as error:
            raise LlmsTxtFetchError("Could not reach the URL.") from error

    raise LlmsTxtFetchError("The URL redirected too many times.")
