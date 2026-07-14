import dataclasses
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlencode, urlparse

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.vantage.settings import (
    VANTAGE_ENDPOINTS,
    VantageEndpointConfig,
)

VANTAGE_HOST = "api.vantage.sh"
VANTAGE_BASE_URL = f"https://{VANTAGE_HOST}/v2"

# The Vantage API caps `limit` at 1000; use the max to minimise the number of paginated requests
# (and thus stay well under the ~1,000 requests/hour and ~20 requests/minute per-key rate limits).
PAGE_SIZE = 1000


class VantageRetryableError(Exception):
    pass


class VantageUntrustedURLError(Exception):
    pass


def _is_trusted_vantage_url(url: str) -> bool:
    # `links.next` (and any resumed cursor derived from it) is server-controlled data. Before we
    # attach the bearer token and fetch it, pin the URL to Vantage's own HTTPS host and `/v2/` API
    # path so a spoofed or compromised response can't redirect the credential to an
    # attacker-controlled origin.
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    return parsed.scheme == "https" and parsed.hostname == VANTAGE_HOST and parsed.path.startswith("/v2/")


@dataclasses.dataclass
class VantageResumeConfig:
    # Full URL of the next page to fetch, taken verbatim from the response `links.next`. Vantage
    # encodes `page`/`limit` into it, so following it is enough to resume where we left off.
    next_url: str


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }


def validate_credentials(api_key: str) -> bool:
    # `/ping` is the cheapest authenticated endpoint - it requires a valid read token and returns
    # 401 for a bad/expired one, without touching any cost data (so it can't trip the stricter
    # Cost Report rate limits).
    url = f"{VANTAGE_BASE_URL}/ping"
    try:
        response = make_tracked_session(redact_values=(api_key,)).get(url, headers=_get_headers(api_key), timeout=10)
        return response.status_code == 200
    except Exception:
        return False


@retry(
    retry=retry_if_exception_type(
        (
            VantageRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session, page_url: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> dict:
    if not _is_trusted_vantage_url(page_url):
        raise VantageUntrustedURLError(
            f"Refusing to fetch untrusted Vantage URL: host must be {VANTAGE_HOST} over HTTPS"
        )

    response = session.get(page_url, headers=headers, timeout=60)

    # 429 (rate limited) and 5xx are transient - retry with backoff. Vantage returns rate-limit
    # status in headers and 429 on exceed; the exponential jitter keeps us within the per-key window.
    if response.status_code == 429 or response.status_code >= 500:
        raise VantageRetryableError(f"Vantage API error (retryable): status={response.status_code}, url={page_url}")

    if not response.ok:
        logger.error(f"Vantage API error: status={response.status_code}, body={response.text}, url={page_url}")
        response.raise_for_status()

    return response.json()


def _build_initial_url(config: VantageEndpointConfig) -> str:
    return f"{VANTAGE_BASE_URL}{config.path}?{urlencode({'limit': PAGE_SIZE})}"


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[VantageResumeConfig],
) -> Iterator[Any]:
    config = VANTAGE_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)
    batcher = Batcher(logger=logger, chunk_size=2000, chunk_size_bytes=100 * 1024 * 1024)
    # Reuse one session across every page so urllib3 keeps the connection alive. Redact the token
    # from logged URLs/samples, and never follow redirects - a valid `links.next` that 3xx-redirects
    # off-host would otherwise forward the bearer token to the redirect target.
    session = make_tracked_session(redact_values=(api_key,), allow_redirects=False)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.next_url:
        url = resume.next_url
        logger.debug(f"Vantage: resuming {endpoint} from URL: {url}")
    else:
        url = _build_initial_url(config)

    while True:
        data = _fetch_page(session, url, headers, logger)

        items = data.get(config.data_key, [])
        next_url = data.get("links", {}).get("next")

        for item in items:
            batcher.batch(item)

            if batcher.should_yield():
                yield batcher.get_table()
                # Save state AFTER yielding (and only when more pages remain) so a crash re-yields
                # the last page rather than skipping it - merge dedupes on the primary key.
                if next_url:
                    resumable_source_manager.save_state(VantageResumeConfig(next_url=next_url))

        if not next_url:
            break
        url = next_url

    if batcher.should_yield(include_incomplete_chunk=True):
        yield batcher.get_table()


def vantage_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[VantageResumeConfig],
) -> SourceResponse:
    endpoint_config = VANTAGE_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=endpoint_config.primary_keys,
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )
