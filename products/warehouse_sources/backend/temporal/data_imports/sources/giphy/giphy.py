import dataclasses
from collections.abc import Iterator
from typing import Any, Optional
from urllib.parse import urlencode, urlsplit

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.giphy.settings import (
    GIPHY_ENDPOINTS,
    GiphyEndpointConfig,
)

GIPHY_BASE_URL = "https://api.giphy.com/v1"
# Beta keys cap search at limit=50; 50 is within every documented endpoint cap
# (trending/search) and works for both beta and production keys.
PAGE_SIZE = 50
REQUEST_TIMEOUT_SECONDS = 60
# GIPHY beta keys are rate limited to 100 calls/hour; back off generously on 429.
MAX_RETRY_ATTEMPTS = 5


class GiphyRetryableError(Exception):
    pass


@dataclasses.dataclass
class GiphyResumeConfig:
    # GIPHY paginates with a numeric offset. The endpoint and (for search) query
    # are rebuilt deterministically from job inputs on resume, so only the offset
    # needs persisting.
    offset: int


def _get_session(api_key: str) -> requests.Session:
    # The API key rides in the query string (GIPHY has no header auth), so register it for
    # value-based redaction — otherwise it leaks into tracked request URLs and captured samples.
    return make_tracked_session(headers={"Accept": "application/json"}, redact_values=(api_key,))


def _build_url(api_key: str, config: GiphyEndpointConfig, offset: int, search_query: str | None) -> str:
    params: dict[str, Any] = {"api_key": api_key}
    if not config.is_term_list:
        params["limit"] = PAGE_SIZE
        params["offset"] = offset
    if config.requires_query:
        params["q"] = search_query
    return f"{GIPHY_BASE_URL}{config.path}?{urlencode(params)}"


def validate_credentials(api_key: str) -> bool:
    """Confirm the API key is genuine with one cheap trending request."""
    url = _build_url(api_key, GIPHY_ENDPOINTS["gifs_trending"], offset=0, search_query=None)
    try:
        response = _get_session(api_key).get(url, timeout=10)
        return response.status_code == 200
    except Exception:
        return False


@retry(
    retry=retry_if_exception_type((GiphyRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
    wait=wait_exponential_jitter(initial=5, max=120),
    reraise=True,
)
def _fetch_page(session: requests.Session, url: str, logger: FilteringBoundLogger) -> dict[str, Any]:
    response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429 or response.status_code >= 500:
        raise GiphyRetryableError(f"GIPHY API error (retryable): status={response.status_code}")

    if not response.ok:
        logger.error("GIPHY API error", status=response.status_code, body=response.text)
        # raise_for_status() would embed the full request URL — including the api_key
        # query param — in the exception, which surfaces in the schema's latest_error.
        # Rebuild the error from the path only so the key never leaks.
        safe = urlsplit(response.url)
        raise requests.HTTPError(
            f"{response.status_code} Client Error: {response.reason} for url: {safe.scheme}://{safe.netloc}{safe.path}",
            response=response,
        )

    return response.json()


def _normalize_items(config: GiphyEndpointConfig, data: dict[str, Any]) -> list[dict[str, Any]]:
    items = data.get(config.data_key, []) or []
    if config.is_term_list:
        # `/trending/searches` returns a flat list of strings; wrap each so the
        # row has the `search_term` primary-key column.
        return [{"search_term": term} for term in items]
    return list(items)


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[GiphyResumeConfig],
    search_query: str | None = None,
) -> Iterator[list[dict[str, Any]]]:
    config = GIPHY_ENDPOINTS[endpoint]

    if config.requires_query and not (search_query or "").strip():
        raise ValueError(
            f"GIPHY endpoint '{endpoint}' requires a search query. Set the search query on the source and reconnect."
        )

    session = _get_session(api_key)

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    offset = resume_config.offset if resume_config is not None else 0
    if resume_config is not None:
        logger.debug("GIPHY: resuming from offset", endpoint=endpoint, offset=offset)

    while True:
        url = _build_url(api_key, config, offset, search_query)
        data = _fetch_page(session, url, logger)
        items = _normalize_items(config, data)

        if items:
            yield items

        # Term lists and any empty page terminate immediately.
        if config.is_term_list or not items:
            break

        pagination = data.get("pagination") or {}
        count = pagination.get("count")
        page_len = count if isinstance(count, int) else len(items)
        next_offset = offset + page_len

        total_count = pagination.get("total_count")
        if isinstance(total_count, int) and next_offset >= total_count:
            break

        # A short page means we've reached the end of the result set.
        if page_len < PAGE_SIZE:
            break

        # GIPHY caps the offset it will serve; requesting beyond it 400s, so stop
        # rather than fail the sync.
        if config.max_offset is not None and next_offset > config.max_offset:
            logger.debug("GIPHY: reached offset cap", endpoint=endpoint, max_offset=config.max_offset)
            break

        offset = next_offset
        # Save state AFTER yielding so a crash re-yields the last page (merge
        # dedupes on the primary key) rather than skipping it.
        resumable_source_manager.save_state(GiphyResumeConfig(offset=offset))


def giphy_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[GiphyResumeConfig],
    search_query: Optional[str] = None,
) -> SourceResponse:
    config = GIPHY_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            search_query=search_query,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
    )
