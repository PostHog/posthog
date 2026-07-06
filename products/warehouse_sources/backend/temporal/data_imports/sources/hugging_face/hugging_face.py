import re
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
from products.warehouse_sources.backend.temporal.data_imports.sources.hugging_face.settings import (
    HUGGING_FACE_ENDPOINTS,
    HuggingFaceEndpointConfig,
)

HUGGING_FACE_BASE_URL = "https://huggingface.co"

# The Hub caps list endpoints at 1000 rows per page; larger pages don't return more.
PAGE_SIZE = 1000


class HuggingFaceRetryableError(Exception):
    pass


@dataclasses.dataclass
class HuggingFaceResumeConfig:
    # URL of the page to resume from. We checkpoint the *current* page (not the next one) after
    # yielding it, so a crash re-fetches and re-yields that page rather than skipping it — the delta
    # merge dedupes the re-pulled rows on the primary key.
    resume_url: str


def _get_headers(api_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_token}",
        "Accept": "application/json",
    }


def _parse_next_url(link_header: str) -> str | None:
    """Return the URL with rel="next" from the Hub's Link header, if any."""
    if not link_header:
        return None
    for part in link_header.split(","):
        part = part.strip()
        match = re.match(r'<([^>]+)>;\s*rel="next"', part)
        if match:
            return match.group(1)
    return None


def validate_credentials(api_token: str) -> bool:
    url = f"{HUGGING_FACE_BASE_URL}/api/whoami-v2"
    try:
        response = make_tracked_session().get(url, headers=_get_headers(api_token), timeout=10)
        return response.status_code == 200
    except Exception:
        return False


@retry(
    retry=retry_if_exception_type(
        (
            HuggingFaceRetryableError,
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
    session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> requests.Response:
    response = session.get(url, headers=headers, timeout=60)

    if response.status_code == 429 or response.status_code >= 500:
        raise HuggingFaceRetryableError(f"Hugging Face API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Hugging Face API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response


def _build_initial_url(config: HuggingFaceEndpointConfig, author: str) -> str:
    # Sort ascending by createdAt (immutable), so new repos append to the end and don't shift pages
    # we've already walked mid-sync. The Hub has no server-side timestamp range filter, so these
    # endpoints are full refresh only.
    params: dict[str, Any] = {
        "author": author,
        "sort": "createdAt",
        "direction": 1,
        "limit": PAGE_SIZE,
    }
    if config.full:
        params["full"] = "true"
    return f"{HUGGING_FACE_BASE_URL}{config.path}?{urlencode(params)}"


def get_rows(
    api_token: str,
    endpoint: str,
    author: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[HuggingFaceResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = HUGGING_FACE_ENDPOINTS[endpoint]
    headers = _get_headers(api_token)
    # One session reused across every page so urllib3 keeps the connection alive.
    session = make_tracked_session()

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None:
        url = resume.resume_url
        logger.debug(f"Hugging Face: resuming from URL: {url}")
    else:
        url = _build_initial_url(config, author)

    while True:
        response = _fetch_page(session, url, headers, logger)
        items = response.json()
        if not isinstance(items, list) or not items:
            break

        next_url = _parse_next_url(response.headers.get("Link", ""))

        yield items

        # Checkpoint AFTER yielding, and checkpoint the current page URL so a crash re-fetches this
        # page (merge dedupes on the primary key) rather than skipping it.
        if next_url:
            resumable_source_manager.save_state(HuggingFaceResumeConfig(resume_url=url))
        else:
            break

        url = next_url


def hugging_face_source(
    api_token: str,
    endpoint: str,
    author: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[HuggingFaceResumeConfig],
) -> SourceResponse:
    config = HUGGING_FACE_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_token=api_token,
            endpoint=endpoint,
            author=author,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="month",
        partition_keys=[config.partition_key],
    )
