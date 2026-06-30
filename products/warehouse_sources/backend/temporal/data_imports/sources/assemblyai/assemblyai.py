import dataclasses
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlencode, urljoin, urlsplit

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.assemblyai.settings import ASSEMBLYAI_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

# AssemblyAI offers a US base URL and an EU data-residency variant. The Authorization header is the
# raw API key (no "Bearer" prefix).
BASE_URLS: dict[str, str] = {
    "us": "https://api.assemblyai.com",
    "eu": "https://api.eu.assemblyai.com",
}
DEFAULT_REGION = "us"

# List endpoint max page size is 200.
PAGE_SIZE = 200

REQUEST_TIMEOUT_SECONDS = 60


class AssemblyAIRetryableError(Exception):
    pass


@dataclasses.dataclass
class AssemblyAIResumeConfig:
    # Absolute URL of the next list page to fetch (from page_details.next_url). Following it walks
    # newest-to-oldest through the transcript list via the API's before_id cursor.
    next_url: str | None = None


def base_url_for_region(region: str | None) -> str:
    return BASE_URLS.get((region or DEFAULT_REGION).lower(), BASE_URLS[DEFAULT_REGION])


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": api_key,
        "Accept": "application/json",
    }


def _pinned_url(base_url: str, url: str) -> str:
    """Resolve a page_details URL (absolute or relative) and pin it to the selected base host.

    next_url comes from the API response body (and is persisted in resume state), so a tampered
    response must not be able to redirect the credential-bearing request to another host. Anything
    that resolves off the selected base origin is rejected.
    """
    resolved = url if url.startswith(("http://", "https://")) else urljoin(base_url, url)
    base, target = urlsplit(base_url), urlsplit(resolved)
    if (target.scheme, target.netloc) != (base.scheme, base.netloc):
        raise ValueError(f"AssemblyAI pagination URL {resolved!r} is not on the selected host {base_url!r}")
    return resolved


@retry(
    retry=retry_if_exception_type(
        (AssemblyAIRetryableError, requests.ReadTimeout, requests.ConnectionError),
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch(session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger) -> dict:
    response = session.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429 or response.status_code >= 500:
        raise AssemblyAIRetryableError(f"AssemblyAI API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"AssemblyAI API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def validate_credentials(api_key: str, region: str | None) -> bool:
    # Cheapest probe that exercises the token: list a single transcript.
    base_url = base_url_for_region(region)
    url = f"{base_url}/v2/transcript?{urlencode({'limit': 1})}"
    try:
        response = make_tracked_session().get(url, headers=_get_headers(api_key), timeout=10)
        return response.status_code == 200
    except Exception:
        return False


def _hydrate_transcript(
    session: requests.Session,
    base_url: str,
    transcript_id: str,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
) -> dict[str, Any]:
    """Fetch the full transcript object for a single id."""
    url = f"{base_url}/v2/transcript/{transcript_id}"
    return _fetch(session, url, headers, logger)


def get_rows(
    api_key: str,
    region: str | None,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[AssemblyAIResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = ASSEMBLYAI_ENDPOINTS[endpoint]
    base_url = base_url_for_region(region)
    headers = _get_headers(api_key)
    # One session reused across every list page and hydration request so urllib3 keeps the
    # connection alive instead of re-handshaking per request.
    session = make_tracked_session()

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.next_url:
        # Persisted state is still untrusted input — pin it to the selected host before fetching.
        url = _pinned_url(base_url, resume.next_url)
        logger.debug(f"AssemblyAI: resuming from URL: {url}")
    else:
        url = f"{base_url}{config.path}?{urlencode({'limit': PAGE_SIZE})}"

    while True:
        data = _fetch(session, url, headers, logger)

        items = data.get(endpoint, [])
        if not items:
            break

        if config.hydrate:
            rows = [_hydrate_transcript(session, base_url, item["id"], headers, logger) for item in items]
        else:
            rows = items

        yield rows

        next_url = data.get("page_details", {}).get("next_url")
        if not next_url:
            break

        # Save AFTER yielding the page so a crash re-yields the just-finished page rather than
        # skipping it — merge dedupes on the primary key. Resume picks up at the next page.
        url = _pinned_url(base_url, next_url)
        resumable_source_manager.save_state(AssemblyAIResumeConfig(next_url=url))


def assemblyai_source(
    api_key: str,
    region: str | None,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[AssemblyAIResumeConfig],
) -> SourceResponse:
    endpoint_config = ASSEMBLYAI_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            region=region,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=endpoint_config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="week" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
        # The list endpoint returns transcripts newest-first and exposes no ascending sort, so rows
        # arrive in descending creation order. Full refresh only, so this never drives a watermark.
        sort_mode="desc",
    )
