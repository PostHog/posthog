import dataclasses
from collections.abc import Iterator
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.bluetally.settings import BLUETALLY_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

BLUETALLY_BASE_URL = "https://app.bluetallyapp.com/api/v1"
# BlueTally caps a single response at 1000 rows; using the max minimizes requests against the
# 10,000-requests-per-hour budget.
PAGE_SIZE = 1000
REQUEST_TIMEOUT_SECONDS = 60


class BluetallyRetryableError(Exception):
    pass


@dataclasses.dataclass
class BluetallyResumeConfig:
    # Offset of the next page to fetch. BlueTally paginates with limit/offset, so persisting the
    # offset is all we need to pick a full-refresh sync back up after a heartbeat timeout.
    offset: int = 0


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }


def _make_session(api_key: str) -> requests.Session:
    # `redact_values` masks the bearer token in logged URLs and captured HTTP samples so a failed or
    # sampled request can never persist the raw BlueTally credential in PostHog's HTTP telemetry.
    return make_tracked_session(headers=_get_headers(api_key), redact_values=(api_key,))


def _build_url(path: str, params: dict[str, Any]) -> str:
    query = {key: value for key, value in params.items() if value is not None and value != ""}
    return f"{BLUETALLY_BASE_URL}{path}?{urlencode(query)}"


@retry(
    retry=retry_if_exception_type((BluetallyRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(session: requests.Session, url: str, logger: FilteringBoundLogger) -> list[dict[str, Any]]:
    response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429 or response.status_code >= 500:
        raise BluetallyRetryableError(f"BlueTally API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        # Don't log the response body: it can echo back the Authorization header or other secrets.
        logger.error(f"BlueTally API error: status={response.status_code}, url={url}")
        response.raise_for_status()

    data = response.json()
    # Every list endpoint returns a bare JSON array. A non-list 200 is a permanent API-contract
    # violation (wrapped payload, proxy HTML, …), not a transient failure — raise a plain ValueError
    # so it surfaces immediately instead of burning the retry budget on something retries can't fix.
    if not isinstance(data, list):
        raise ValueError(f"BlueTally API returned a non-list response: url={url}")
    return data


def validate_credentials(api_key: str, tenant_id: str | None = None, path: str = "/assets") -> bool:
    url = _build_url(path, {"limit": 1, "tenant_id": tenant_id})
    try:
        response = _make_session(api_key).get(url, timeout=10)
        return response.status_code == 200
    except Exception:
        return False


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[BluetallyResumeConfig],
    tenant_id: str | None = None,
) -> Iterator[list[dict[str, Any]]]:
    config = BLUETALLY_ENDPOINTS[endpoint]
    # One session reused across every page so urllib3 keeps the connection alive.
    session = _make_session(api_key)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    offset = resume.offset if resume else 0
    if resume:
        logger.debug(f"BlueTally: resuming {endpoint} from offset={offset}")

    while True:
        url = _build_url(
            config.path,
            {
                "limit": PAGE_SIZE,
                "offset": offset,
                "sort": config.sort,
                "order": "asc",
                "tenant_id": tenant_id,
            },
        )
        page = _fetch_page(session, url, logger)
        if not page:
            break

        yield page

        # A short page means we've reached the end of the resource.
        if len(page) < PAGE_SIZE:
            break

        offset += len(page)
        # Save AFTER yielding so a crash re-runs from the last persisted offset rather than skipping
        # ahead; the merge dedupes any re-pulled rows on the primary key.
        resumable_source_manager.save_state(BluetallyResumeConfig(offset=offset))


def bluetally_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[BluetallyResumeConfig],
    tenant_id: Optional[str] = None,
) -> SourceResponse:
    config = BLUETALLY_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            tenant_id=tenant_id,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # We request `sort=created_at&order=asc`, so rows arrive oldest-first.
        sort_mode="asc",
    )
