import dataclasses
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.pexels.settings import (
    PEXELS_ENDPOINTS,
    PexelsEndpointConfig,
)

PEXELS_BASE_URL = "https://api.pexels.com"
# Pexels caps `per_page` at 80; request the max to minimise round trips.
PER_PAGE = 80
REQUEST_TIMEOUT = 30


class PexelsRetryableError(Exception):
    pass


@dataclasses.dataclass
class PexelsResumeConfig:
    # 1-based page number to (re-)start from. Pexels uses page-number pagination.
    page: int = 1


def _get_headers(api_key: str) -> dict[str, str]:
    # Pexels sends the API key as the raw Authorization header value — no "Bearer " prefix.
    return {"Authorization": api_key, "Accept": "application/json"}


def _build_url(base_url: str, params: dict[str, Any]) -> str:
    return f"{base_url}?{urlencode(params)}" if params else base_url


@retry(
    retry=retry_if_exception_type(
        (
            PexelsRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger) -> dict:
    response = session.get(url, headers=headers, timeout=REQUEST_TIMEOUT)

    # 429 (rate limited) and 5xx are transient; retry with backoff. Pexels also exposes
    # X-Ratelimit-Reset, but exponential backoff is sufficient given the retry cap.
    if response.status_code == 429 or response.status_code >= 500:
        raise PexelsRetryableError(f"Pexels API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Pexels API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def validate_credentials(api_key: str) -> bool:
    # The curated endpoint needs no query params and a single row is the cheapest authenticated probe.
    url = _build_url(f"{PEXELS_BASE_URL}/v1/curated", {"per_page": 1})
    try:
        # Pexels sends the key as a raw Authorization value the sampler's name-based scrubber can't
        # recognise, so register it for redaction to keep it out of captured HTTP samples.
        session = make_tracked_session(redact_values=(api_key,))
        response = session.get(url, headers=_get_headers(api_key), timeout=REQUEST_TIMEOUT)
        return response.status_code == 200
    except Exception:
        return False


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PexelsResumeConfig],
    search_query: str | None = None,
) -> Iterator[list[dict[str, Any]]]:
    config = PEXELS_ENDPOINTS[endpoint]
    # `get_schemas` only offers the search tables when a query is set, but fail loudly here rather
    # than let a missing query become a literal `?query=None` if that guard ever regresses.
    if config.requires_query and not search_query:
        raise ValueError(f"Endpoint '{endpoint}' requires a search query but none was provided.")

    headers = _get_headers(api_key)
    # One session reused across every page so urllib3 keeps the connection alive. The raw
    # Authorization key is redacted from captured samples — the sampler can't infer that format.
    session = make_tracked_session(redact_values=(api_key,))

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page = resume.page if resume and resume.page else 1

    while True:
        params: dict[str, Any] = {"per_page": PER_PAGE, "page": page}
        if config.requires_query:
            params["query"] = search_query
        url = _build_url(f"{PEXELS_BASE_URL}{config.path}", params)

        data = _fetch_page(session, url, headers, logger)
        items = data.get(config.data_key, [])
        if not items:
            break

        yield items

        # Save the just-yielded page as the resume point so a crash re-fetches it rather than
        # skipping it; the re-fetched rows dedupe on the `id` primary key when merged.
        resumable_source_manager.save_state(PexelsResumeConfig(page=page))

        # `next_page` is present only while more pages remain; absence terminates pagination.
        if not data.get("next_page"):
            break
        page += 1


def pexels_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PexelsResumeConfig],
    search_query: str | None = None,
) -> SourceResponse:
    endpoint_config: PexelsEndpointConfig = PEXELS_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            search_query=search_query,
        ),
        primary_keys=endpoint_config.primary_keys,
        # Full refresh only — Pexels resources carry no stable datetime to partition on.
        partition_count=1,
        partition_size=1,
    )
