from collections.abc import Iterator
from typing import Any

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.cohere.settings import (
    COHERE_ENDPOINTS,
    CohereEndpointConfig,
    CoherePagination,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session

# Cohere serves a single global API host; there are no regional variants.
COHERE_BASE_URL = "https://api.cohere.com/v1"


class CohereRetryableError(Exception):
    pass


class CohereError(Exception):
    pass


def _extract_items(data: dict[str, Any], config: CohereEndpointConfig, url: str) -> list[dict[str, Any]]:
    # A successful response that omits the envelope key is a shape mismatch, not empty data.
    # Every Cohere schema is full-refresh-only, so silently treating a missing key as an empty
    # page would clear the existing warehouse table; fail loudly instead of destroying data.
    if config.data_key not in data:
        raise CohereError(f"Cohere response missing expected '{config.data_key}' key: url={url}")
    return data[config.data_key]


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }


def validate_credentials(api_key: str) -> bool:
    # /models is the cheapest authenticated probe: a 200 confirms the key is genuine without
    # touching a user's data. An invalid key returns 401 ("invalid api token").
    url = f"{COHERE_BASE_URL}/models"
    try:
        # `redact_values` masks the API key in logged URLs and captured HTTP samples.
        response = make_tracked_session(redact_values=(api_key,)).get(
            url, headers=_get_headers(api_key), params={"page_size": 1}, timeout=10
        )
        return response.status_code == 200
    except Exception:
        return False


@retry(
    # ChunkedEncodingError is a mid-stream connection break; transient like ConnectionError/ReadTimeout.
    retry=retry_if_exception_type(
        (
            CohereRetryableError,
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
    session: requests.Session,
    url: str,
    headers: dict[str, str],
    params: dict[str, Any],
    logger: FilteringBoundLogger,
) -> dict[str, Any]:
    response = session.get(url, headers=headers, params=params, timeout=60)

    if response.status_code == 429 or response.status_code >= 500:
        raise CohereRetryableError(f"Cohere API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Cohere API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    config = COHERE_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)
    # One session reused across every page so urllib3 keeps the connection alive.
    # `redact_values` masks the API key in logged URLs and captured HTTP samples.
    session = make_tracked_session(redact_values=(api_key,))
    url = f"{COHERE_BASE_URL}{config.path}"

    if config.pagination == CoherePagination.NONE:
        data = _fetch_page(session, url, headers, {}, logger)
        items = _extract_items(data, config, url)
        if items:
            yield items
        return

    if config.pagination == CoherePagination.OFFSET:
        yield from _paginate_offset(session, url, headers, config, logger)
        return

    yield from _paginate_page_token(session, url, headers, config, logger)


def _paginate_offset(
    session: requests.Session,
    url: str,
    headers: dict[str, str],
    config: CohereEndpointConfig,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    offset = 0
    while True:
        data = _fetch_page(session, url, headers, {"limit": config.page_size, "offset": offset}, logger)
        items = _extract_items(data, config, url)
        if not items:
            break
        yield items
        # A short page means the last page; stop rather than issue an extra empty request.
        if len(items) < config.page_size:
            break
        offset += len(items)


def _paginate_page_token(
    session: requests.Session,
    url: str,
    headers: dict[str, str],
    config: CohereEndpointConfig,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    page_token: str | None = None
    while True:
        params: dict[str, Any] = {"page_size": config.page_size}
        if page_token:
            params["page_token"] = page_token
        data = _fetch_page(session, url, headers, params, logger)
        items = _extract_items(data, config, url)
        if items:
            yield items
        page_token = data.get(config.next_token_key)
        if not page_token:
            break


def cohere_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
) -> SourceResponse:
    config = COHERE_ENDPOINTS[endpoint]
    partitioned = config.partition_key is not None

    # Leave every partition field unset for endpoints without a creation timestamp (the model
    # catalog). Setting partition_count/size here would make the warehouse writer fall back to
    # primary_keys and md5-partition the table by `name`; None keeps it unpartitioned as intended.
    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(api_key=api_key, endpoint=endpoint, logger=logger),
        primary_keys=config.primary_keys,
        partition_count=1 if partitioned else None,
        partition_size=1 if partitioned else None,
        partition_mode="datetime" if partitioned else None,
        partition_format="month" if partitioned else None,
        partition_keys=[config.partition_key] if config.partition_key is not None else None,
    )
