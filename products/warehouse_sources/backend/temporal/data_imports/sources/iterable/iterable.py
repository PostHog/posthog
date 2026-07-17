import dataclasses
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlparse

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.iterable.settings import ITERABLE_ENDPOINTS

# Iterable is region-locked: a key issued in one data center only works against that data center.
ITERABLE_BASE_URLS: dict[str, str] = {
    "us": "https://api.iterable.com",
    "eu": "https://api.eu.iterable.com",
}

REQUEST_TIMEOUT_SECONDS = 60
# Safety bound on the pagination loop. Iterable's list endpoints normally return everything in a
# single response, but if one ever starts returning `nextPageUrl` we don't want an unbounded scan.
MAX_PAGES = 10_000


class IterableRetryableError(Exception):
    pass


@dataclasses.dataclass
class IterableResumeConfig:
    next_url: str


def base_url_for_region(region: str | None) -> str:
    return ITERABLE_BASE_URLS.get((region or "us").lower(), ITERABLE_BASE_URLS["us"])


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Api-Key": api_key,
        "Accept": "application/json",
    }


def validate_credentials(api_key: str, region: str | None) -> bool:
    # `/api/channels` is a cheap, low-cardinality endpoint that requires a valid server-side key.
    url = f"{base_url_for_region(region)}/api/channels"
    # `redact_values` masks the key in logs and sample capture: the sampler's name-based scrubber
    # doesn't recognise Iterable's `Api-Key` header, so the value would otherwise be captured raw.
    session = make_tracked_session(headers=_get_headers(api_key), redact_values=(api_key,))
    try:
        response = session.get(url, timeout=10)
        return response.status_code == 200
    except Exception:
        return False


def _is_same_origin(base_url: str, url: str) -> bool:
    base = urlparse(base_url)
    target = urlparse(url)
    return (target.scheme, target.netloc) == (base.scheme, base.netloc)


def _resolve_next_url(base_url: str, next_page: Any) -> str | None:
    """Normalize the `nextPageUrl` value from a response body into an absolute URL.

    Absolute URLs are only followed when they point at the selected Iterable base URL.
    The session carries the `Api-Key` header, so a `nextPageUrl` aimed at another host
    (e.g. an attacker-controlled value echoed back in a response) would leak the key —
    such off-host pages stop pagination instead.
    """
    if not next_page or not isinstance(next_page, str):
        return None
    if next_page.startswith("http://") or next_page.startswith("https://"):
        return next_page if _is_same_origin(base_url, next_page) else None
    return f"{base_url}{next_page}" if next_page.startswith("/") else f"{base_url}/{next_page}"


def get_rows(
    api_key: str,
    region: str | None,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[IterableResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = ITERABLE_ENDPOINTS[endpoint]
    base_url = base_url_for_region(region)
    # `redact_values` masks the key in logs and sample capture: the sampler's name-based scrubber
    # doesn't recognise Iterable's `Api-Key` header, so the value would otherwise be captured raw.
    session = make_tracked_session(headers=_get_headers(api_key), redact_values=(api_key,))

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume_config is not None and _is_same_origin(base_url, resume_config.next_url):
        url: str | None = resume_config.next_url
        logger.debug(f"Iterable: resuming {endpoint} from URL: {url}")
    else:
        # Either no resume state, or it points off-host (corrupted/poisoned) — start from the top.
        # The session carries the `Api-Key` header, so we never follow a resumed off-host URL.
        url = f"{base_url}{config.path}"

    @retry(
        retry=retry_if_exception_type((IterableRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(5),
        wait=wait_exponential_jitter(initial=1, max=30),
        reraise=True,
    )
    def fetch_page(page_url: str) -> dict[str, Any]:
        response = session.get(page_url, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code == 429 or response.status_code >= 500:
            raise IterableRetryableError(
                f"Iterable API error (retryable): status={response.status_code}, url={page_url}"
            )

        if not response.ok:
            logger.error(f"Iterable API error: status={response.status_code}, body={response.text}, url={page_url}")
            response.raise_for_status()

        return response.json()

    pages = 0
    while url is not None:
        data = fetch_page(url)
        items = data.get(config.data_key, [])

        next_url = _resolve_next_url(base_url, data.get("nextPageUrl"))

        if items:
            yield items
            # Save state AFTER yielding so a crash re-yields the last batch (merge dedupes on the
            # primary key) rather than skipping it.
            if next_url is not None:
                resumable_source_manager.save_state(IterableResumeConfig(next_url=next_url))

        pages += 1
        if pages >= MAX_PAGES:
            logger.warning(f"Iterable: hit MAX_PAGES={MAX_PAGES} cap for endpoint={endpoint}; stopping pagination")
            break

        url = next_url


def iterable_source(
    api_key: str,
    region: str | None,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[IterableResumeConfig],
) -> SourceResponse:
    config = ITERABLE_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            region=region,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=[config.primary_key],
    )
