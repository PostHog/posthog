from collections.abc import Iterator
from typing import Any

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.browserbase.settings import BROWSERBASE_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session

BROWSERBASE_BASE_URL = "https://api.browserbase.com/v1"


class BrowserbaseRetryableError(Exception):
    pass


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "X-BB-API-Key": api_key,
        "Accept": "application/json",
    }


@retry(
    retry=retry_if_exception_type(
        (
            BrowserbaseRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch(session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger) -> Any:
    response = session.get(url, headers=headers, timeout=60)

    # 429 (rate limited) and 5xx are transient; retry with backoff. Browserbase sends standard
    # x-ratelimit-* / retry-after headers, but exponential jitter is a safe default without them.
    if response.status_code == 429 or response.status_code >= 500:
        raise BrowserbaseRetryableError(f"Browserbase API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        # Log only status and url — the response body can echo imported third-party data.
        logger.error(f"Browserbase API error: status={response.status_code}, url={url}")
        response.raise_for_status()

    return response.json()


def validate_credentials(api_key: str) -> bool:
    # `/projects` is the cheapest authenticated probe: a project-scoped key can always list at least
    # its own project, so a 200 confirms the key is genuine without needing any session data.
    # `redact_values` masks the key in tracked logs/samples. `capture=False` keeps response bodies out
    # of HTTP sample storage — project objects can carry arbitrary customer fields the name-based
    # scrubbers can't recognise. Transport errors (timeout, DNS, reset) propagate rather than being
    # swallowed as False, so a temporary outage isn't reported as a bad key.
    url = f"{BROWSERBASE_BASE_URL}/projects"
    response = make_tracked_session(redact_values=(api_key,), capture=False).get(
        url, headers=_get_headers(api_key), timeout=10
    )
    return response.status_code == 200


def get_rows(api_key: str, endpoint: str, logger: FilteringBoundLogger) -> Iterator[list[dict[str, Any]]]:
    config = BROWSERBASE_ENDPOINTS[endpoint]
    # `capture=False`: session objects carry arbitrary `userMetadata` (and projects can carry other
    # customer-defined fields) that the name-based sample scrubbers can't recognise, so keep response
    # bodies out of HTTP sample storage entirely. Requests are still metered and logged (status + url).
    session = make_tracked_session(redact_values=(api_key,), capture=False)
    headers = _get_headers(api_key)

    # Browserbase list endpoints return a plain JSON array with no pagination, page, or cursor params,
    # so a single request yields the whole collection. The pipeline batches the yielded rows for us.
    data = _fetch(session, f"{BROWSERBASE_BASE_URL}{config.path}", headers, logger)

    # A non-list success body is an unexpected/error shape. Raise so the sync fails loudly instead of
    # finishing "successfully" with zero rows and silently hiding the bad response.
    if not isinstance(data, list):
        raise ValueError(f"Browserbase: expected a list for endpoint {endpoint}, got {type(data).__name__}")

    if data:
        yield data


def browserbase_source(api_key: str, endpoint: str, logger: FilteringBoundLogger) -> SourceResponse:
    endpoint_config = BROWSERBASE_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(api_key=api_key, endpoint=endpoint, logger=logger),
        primary_keys=endpoint_config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )
