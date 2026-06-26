import dataclasses
from collections.abc import Iterator
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.pendo.settings import (
    DEFAULT_REGION,
    PENDO_ENDPOINTS,
    PENDO_REGION_BASE_URLS,
)

AGGREGATION_PATH = "/api/v1/aggregation"
# Pendo's aggregation endpoint isn't a bulk export tool (4 GB / 5-minute caps), so we page
# through it in bounded chunks via skip/limit pipeline stages.
AGGREGATION_PAGE_SIZE = 5000
# List endpoints return the whole array in one response; chunk it so we don't hold an
# unbounded list in memory and so resume state can advance per chunk.
LIST_CHUNK_SIZE = 1000
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 5


class PendoRetryableError(Exception):
    pass


@dataclasses.dataclass
class PendoResumeConfig:
    # Number of rows already yielded for this schema; on resume we skip past them.
    offset: int = 0


def get_base_url(region: Optional[str]) -> str:
    return PENDO_REGION_BASE_URLS.get((region or DEFAULT_REGION).lower(), PENDO_REGION_BASE_URLS[DEFAULT_REGION])


def _get_headers(integration_key: str) -> dict[str, str]:
    return {
        "x-pendo-integration-key": integration_key,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


@retry(
    retry=retry_if_exception_type((PendoRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(MAX_RETRIES),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _request(
    session: requests.Session,
    method: str,
    url: str,
    logger: FilteringBoundLogger,
    **kwargs: Any,
) -> requests.Response:
    response = session.request(method, url, timeout=REQUEST_TIMEOUT_SECONDS, **kwargs)

    if response.status_code == 429 or response.status_code >= 500:
        raise PendoRetryableError(f"Pendo API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        # Cap the body so an HTML error page (e.g. a WAF 503) can't blow up the log line.
        logger.error(f"Pendo API error: status={response.status_code}, body={response.text[:500]!r}, url={url}")
        response.raise_for_status()

    return response


def validate_credentials(integration_key: str, region: Optional[str]) -> tuple[bool, str | None]:
    # Probe a real list endpoint we also sync: a valid key returns 200 (even with an empty
    # array), a bad/insufficient key returns 401/403.
    url = f"{get_base_url(region)}/api/v1/page"
    try:
        # `redact_values` masks the integration key from logged URLs and captured HTTP samples.
        session = make_tracked_session(redact_values=(integration_key,))
        response = session.get(url, headers=_get_headers(integration_key), timeout=10)
    except (requests.RequestException, OSError):
        return False, "Could not reach Pendo. Check your network connection and the selected region."

    if response.status_code == 200:
        return True, None
    if response.status_code in (401, 403):
        return False, "Invalid Pendo integration key, or the key is missing the required permissions."
    return False, f"Pendo returned an unexpected status code: {response.status_code}"


def _iter_list_endpoint(
    session: requests.Session,
    base_url: str,
    path: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PendoResumeConfig],
    start_offset: int,
) -> Iterator[list[dict[str, Any]]]:
    # `expand=*` returns objects across every app in a multi-app subscription rather than
    # just the default app.
    url = f"{base_url}{path}?expand=*"
    response = _request(session, "GET", url, logger)
    data = response.json()
    items: list[dict[str, Any]] = data if isinstance(data, list) else data.get("results", [])

    offset = start_offset
    for i in range(offset, len(items), LIST_CHUNK_SIZE):
        chunk = items[i : i + LIST_CHUNK_SIZE]
        yield chunk
        offset += len(chunk)
        resumable_source_manager.save_state(PendoResumeConfig(offset=offset))


def _iter_aggregation(
    session: requests.Session,
    base_url: str,
    aggregation_source: str,
    sort_field: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PendoResumeConfig],
    start_offset: int,
) -> Iterator[list[dict[str, Any]]]:
    url = f"{base_url}{AGGREGATION_PATH}"
    offset = start_offset

    while True:
        body = {
            "response": {"mimeType": "application/json"},
            "request": {
                "requestId": f"posthog-{aggregation_source}",
                "pipeline": [
                    {"source": {aggregation_source: None}},
                    # Sort on a stable id so skip/limit paging is deterministic across requests.
                    {"sort": [sort_field]},
                    {"skip": offset},
                    {"limit": AGGREGATION_PAGE_SIZE},
                ],
            },
        }
        response = _request(session, "POST", url, logger, json=body)
        data = response.json()
        rows: list[dict[str, Any]] = data.get("results", []) if isinstance(data, dict) else data

        if not rows:
            break

        yield rows
        offset += len(rows)
        resumable_source_manager.save_state(PendoResumeConfig(offset=offset))

        if len(rows) < AGGREGATION_PAGE_SIZE:
            break


def get_rows(
    integration_key: str,
    region: Optional[str],
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PendoResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = PENDO_ENDPOINTS[endpoint]
    base_url = get_base_url(region)
    # `redact_values` masks the integration key from logged URLs and captured HTTP samples.
    session = make_tracked_session(headers=_get_headers(integration_key), redact_values=(integration_key,))

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    start_offset = resume.offset if resume else 0
    if start_offset:
        logger.debug(f"Pendo: resuming endpoint={endpoint} from offset={start_offset}")

    if config.is_aggregation:
        if config.aggregation_source is None:
            raise ValueError(f"Endpoint '{endpoint}' is marked as aggregation but has no aggregation_source")
        yield from _iter_aggregation(
            session,
            base_url,
            config.aggregation_source,
            config.primary_keys[0],
            logger,
            resumable_source_manager,
            start_offset,
        )
    else:
        if config.path is None:
            raise ValueError(f"Endpoint '{endpoint}' is not an aggregation but has no path")
        yield from _iter_list_endpoint(
            session,
            base_url,
            config.path,
            logger,
            resumable_source_manager,
            start_offset,
        )


def pendo_source(
    integration_key: str,
    region: Optional[str],
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PendoResumeConfig],
) -> SourceResponse:
    config = PENDO_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            integration_key=integration_key,
            region=region,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=config.primary_keys,
        # No source-level partitioning: Pendo timestamps are epoch-milliseconds, which the
        # datetime partitioner would misread as epoch-seconds, and the aggregation rows carry
        # no stable created_at field. Ship unpartitioned full-refresh tables.
    )
