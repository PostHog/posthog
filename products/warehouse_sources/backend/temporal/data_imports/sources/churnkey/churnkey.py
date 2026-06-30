import dataclasses
from collections.abc import Iterator
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.churnkey.settings import (
    CHURNKEY_BASE_URL,
    CHURNKEY_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager


class ChurnkeyRetryableError(Exception):
    pass


@dataclasses.dataclass
class ChurnkeyResumeConfig:
    # Offset (number of records to skip) for the next page to fetch. The API paginates via
    # `limit`/`skip`, so the offset is the only state we need to resume a full refresh.
    skip: int = 0


def _get_headers(api_key: str, app_id: str) -> dict[str, str]:
    return {
        "x-ck-api-key": api_key,
        "x-ck-app": app_id,
        "content-type": "application/json",
        "accept": "application/json",
    }


@retry(
    retry=retry_if_exception_type((ChurnkeyRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> list[dict[str, Any]]:
    response = session.get(url, headers=headers, timeout=60)

    if response.status_code == 429 or response.status_code >= 500:
        raise ChurnkeyRetryableError(f"Churnkey API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Churnkey API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    data = response.json()
    # The sessions endpoint returns a bare JSON array, not a `{"data": [...]}` envelope.
    if not isinstance(data, list):
        return []
    return data


def validate_credentials(api_key: str, app_id: str) -> tuple[bool, Optional[int]]:
    """Probe the sessions endpoint with the smallest possible request.

    Returns ``(is_valid, status_code)``. A network failure surfaces as ``(False, None)``.
    """
    url = f"{CHURNKEY_BASE_URL}/sessions?{urlencode({'limit': 1})}"
    try:
        response = make_tracked_session().get(url, headers=_get_headers(api_key, app_id), timeout=10)
        return response.status_code == 200, response.status_code
    except Exception:
        return False, None


def get_rows(
    api_key: str,
    app_id: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ChurnkeyResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = CHURNKEY_ENDPOINTS[endpoint]
    headers = _get_headers(api_key, app_id)
    # One session reused across every page so urllib3 keeps the connection alive instead of
    # re-handshaking per request.
    session = make_tracked_session()
    limit = config.page_size

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    skip = resume.skip if resume else 0
    if resume:
        logger.debug(f"Churnkey: resuming {endpoint} from skip={skip}")

    while True:
        url = f"{CHURNKEY_BASE_URL}{config.path}?{urlencode({'limit': limit, 'skip': skip})}"
        page = _fetch_page(session, url, headers, logger)
        if not page:
            break

        yield page

        skip += limit
        # A short page means we've reached the end — stop without checkpointing further.
        if len(page) < limit:
            break

        # Save AFTER yielding so a crash resumes at the next page rather than skipping the
        # one we just emitted prematurely; merge dedupes any re-pulled rows on `_id`.
        resumable_source_manager.save_state(ChurnkeyResumeConfig(skip=skip))


def churnkey_source(
    api_key: str,
    app_id: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ChurnkeyResumeConfig],
) -> SourceResponse:
    config = CHURNKEY_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            app_id=app_id,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
