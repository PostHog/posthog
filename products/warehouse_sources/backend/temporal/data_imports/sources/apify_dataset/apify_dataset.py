import dataclasses
from collections.abc import Iterator
from typing import Any
from urllib.parse import quote, urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.apify_dataset.settings import (
    APIFY_BASE_URL,
    PRIMARY_KEYS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

# One request to /datasets/{id}/items returns this many rows. The dataset endpoints carry a high
# rate limit (~400 req/s), so a large page keeps the round-trip count down on big datasets.
PAGE_SIZE = 1000


class ApifyRetryableError(Exception):
    pass


@dataclasses.dataclass
class ApifyResumeConfig:
    # Absolute offset of the next dataset row to fetch. Apify datasets are append-only and returned in
    # stable storage order, so an offset always points at the same row — making it a safe resume cursor.
    offset: int = 0


def _get_headers(api_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_token}",
        "Accept": "application/json",
    }


def _items_url(dataset_id: str, offset: int, limit: int) -> str:
    # `format=json` returns a JSON array of the raw rows; offset/limit drive the pagination.
    params = {"offset": offset, "limit": limit, "format": "json"}
    # Encode the dataset_id as a single path segment so a crafted value can't inject extra path
    # segments or query params (e.g. dropping the enforced offset/limit).
    return f"{APIFY_BASE_URL}/datasets/{quote(dataset_id, safe='')}/items?{urlencode(params)}"


def validate_credentials(api_token: str, dataset_id: str) -> tuple[bool, str | None]:
    """Probe the dataset itself so a bad token (401) and a wrong/inaccessible dataset (404) are both caught."""
    # Encode the dataset_id as a single path segment so a crafted value can't escape the path.
    url = f"{APIFY_BASE_URL}/datasets/{quote(dataset_id, safe='')}"
    try:
        response = make_tracked_session().get(url, headers=_get_headers(api_token), timeout=10)
    except Exception:
        return False, "Could not reach the Apify API. Please try again."

    if response.status_code == 200:
        return True, None
    if response.status_code in (401, 403):
        return False, "Invalid Apify API token, or the token cannot access this dataset."
    if response.status_code == 404:
        return False, "Dataset not found. Check the dataset ID and that the token can access it."
    return False, f"Unexpected response from Apify (status {response.status_code})."


@retry(
    retry=retry_if_exception_type((ApifyRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> tuple[list[dict[str, Any]], int]:
    """Fetch one page of dataset items. Returns the rows plus the dataset's total item count.

    Apify reports the total via the ``X-Apify-Pagination-Total`` response header rather than in the body
    (the body is a bare JSON array), so we read it from there to know when to stop paging.
    """
    response = session.get(url, headers=headers, timeout=60)

    if response.status_code == 429 or response.status_code >= 500:
        raise ApifyRetryableError(f"Apify API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Apify API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    items = response.json()
    if not isinstance(items, list):
        # The items endpoint always returns a JSON array for format=json; anything else means the
        # request was misrouted (e.g. an error object). That's a permanent contract violation, so raise
        # a non-retryable error to fail loudly rather than waiting through every retry attempt.
        raise ValueError(f"Unexpected Apify response shape (not a list), url={url}")

    total_header = response.headers.get("X-Apify-Pagination-Total")
    try:
        total = int(total_header) if total_header is not None else len(items)
    except (TypeError, ValueError):
        total = len(items)
    return items, total


def get_rows(
    api_token: str,
    dataset_id: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ApifyResumeConfig],
) -> Iterator[Any]:
    headers = _get_headers(api_token)
    batcher = Batcher(logger=logger, chunk_size=2000, chunk_size_bytes=100 * 1024 * 1024)
    # One session reused across every page so urllib3 keeps the connection alive between requests.
    session = make_tracked_session()

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    offset = resume.offset if resume else 0
    if resume:
        logger.debug(f"Apify: resuming dataset {dataset_id} from offset {offset}")

    while True:
        url = _items_url(dataset_id, offset, PAGE_SIZE)
        items, total = _fetch_page(session, url, headers, logger)

        if not items:
            break

        offset += len(items)
        more_pages = offset < total

        for item in items:
            batcher.batch(item)

            if batcher.should_yield():
                yield batcher.get_table()
                # Save AFTER yielding (and only when more rows remain) so a crash re-yields the last
                # page rather than skipping it. The dataset is append-only, so the re-pulled rows are
                # identical; full refresh tolerates the rare resume-window overlap.
                if more_pages:
                    resumable_source_manager.save_state(ApifyResumeConfig(offset=offset))

        if not more_pages:
            break

    if batcher.should_yield(include_incomplete_chunk=True):
        yield batcher.get_table()


def apify_dataset_source(
    api_token: str,
    dataset_id: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ApifyResumeConfig],
) -> SourceResponse:
    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_token=api_token,
            dataset_id=dataset_id,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=PRIMARY_KEYS.get(endpoint),
    )
