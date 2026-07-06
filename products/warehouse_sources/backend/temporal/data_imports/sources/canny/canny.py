import dataclasses
from collections.abc import Iterator
from typing import Any

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.canny.settings import (
    CANNY_ENDPOINTS,
    CannyEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

CANNY_BASE_URL = "https://canny.io/api"
# Airbyte's community connector pages every Canny list endpoint at 100 records.
PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 5


class CannyRetryableError(Exception):
    """Raised on 429/5xx so tenacity retries; never reaches get_non_retryable_errors."""


@dataclasses.dataclass
class CannyResumeConfig:
    # Offset into the current endpoint's list. Each schema syncs independently, so a single
    # skip value is enough to resume — there is no cross-endpoint cursor to track.
    skip: int = 0


def _build_body(api_key: str, config: CannyEndpointConfig, skip: int) -> dict[str, Any]:
    body: dict[str, Any] = {"apiKey": api_key}
    if config.paginated:
        body["skip"] = skip
        body["limit"] = PAGE_SIZE
    return body


def _handle_response(response: requests.Response, url: str, logger: FilteringBoundLogger) -> dict[str, Any]:
    """Classify a single Canny response: retryable, terminal failure, or success body."""
    if response.status_code == 429 or response.status_code >= 500:
        raise CannyRetryableError(f"Canny API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Canny API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    data = response.json()
    # Canny returns 200 with an `{"error": "..."}` body for some failures (e.g. an invalid
    # API key). Surface it as an HTTPError so the friendly non-retryable mapping can match it.
    if isinstance(data, dict) and data.get("error"):
        raise requests.HTTPError(f"Canny API error: {data['error']} (url: {url})", response=response)

    return data


@retry(
    retry=retry_if_exception_type((CannyRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(MAX_RETRIES),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    url: str,
    body: dict[str, Any],
    logger: FilteringBoundLogger,
) -> dict[str, Any]:
    # Canny authenticates via the `apiKey` POST body parameter, so every list request is a
    # form-encoded POST rather than a GET.
    response = session.post(url, data=body, timeout=REQUEST_TIMEOUT_SECONDS)
    return _handle_response(response, url, logger)


def _extract_records(data: dict[str, Any], config: CannyEndpointConfig) -> list[dict[str, Any]]:
    records = data.get(config.data_key)
    if isinstance(records, list):
        return records
    return []


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CannyResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = CANNY_ENDPOINTS[endpoint]
    url = f"{CANNY_BASE_URL}{config.path}"
    # Redact the secret so it never lands in tracked HTTP logs/samples — it travels in the POST body.
    session = make_tracked_session(redact_values=(api_key,))

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    skip = resume.skip if resume is not None else 0
    if resume is not None:
        logger.debug(f"Canny: resuming endpoint={endpoint} from skip={skip}")

    while True:
        data = _fetch_page(session, url, _build_body(api_key, config, skip), logger)
        records = _extract_records(data, config)

        if records:
            yield records

        if not config.paginated or not data.get("hasMore"):
            break

        # Advance, then persist — saving AFTER yielding means a crash re-yields the last page
        # (the merge dedupes on the primary key) rather than skipping it.
        skip += PAGE_SIZE
        if records:
            resumable_source_manager.save_state(CannyResumeConfig(skip=skip))


def canny_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CannyResumeConfig],
) -> SourceResponse:
    config = CANNY_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
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


def validate_credentials(api_key: str) -> bool:
    # boards/list is the cheapest probe: no pagination, returns quickly, and requires only a
    # valid API key (every workspace has at least one board). Reuse the catalog path so this can
    # never drift from the synced endpoint.
    url = f"{CANNY_BASE_URL}{CANNY_ENDPOINTS['boards'].path}"
    try:
        response = make_tracked_session(redact_values=(api_key,)).post(
            url, data={"apiKey": api_key}, timeout=REQUEST_TIMEOUT_SECONDS
        )
    except Exception:
        return False

    if not response.ok:
        return False

    try:
        body = response.json()
    except ValueError:
        return False

    return not (isinstance(body, dict) and body.get("error"))
