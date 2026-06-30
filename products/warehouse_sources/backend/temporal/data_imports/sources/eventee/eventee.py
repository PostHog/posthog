from collections.abc import Iterator
from typing import Any

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.eventee.settings import EVENTEE_ENDPOINTS

# The base URL is fixed: the Bearer token scopes to a single event, so there's no per-tenant host.
EVENTEE_BASE_URL = "https://api.eventee.com/public/v1"
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRY_ATTEMPTS = 5


class EventeeRetryableError(Exception):
    pass


def _get_session(api_key: str) -> requests.Session:
    return make_tracked_session(
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        redact_values=(api_key,),
    )


def validate_credentials(api_key: str) -> bool:
    """Confirm the token is genuine with a cheap probe. A valid token returns 200; an invalid or
    expired one returns 401 (`token_invalid`)."""
    try:
        response = _get_session(api_key).get(f"{EVENTEE_BASE_URL}/groups", timeout=10)
        return response.status_code == 200
    except Exception:
        return False


def _extract_rows(data: Any, data_key: str | None) -> list[dict[str, Any]]:
    """Normalize an Eventee response into a list of row dicts.

    `/content` returns an object bundling several lists, so a table sourced from it reads its rows
    from `data[data_key]`. The standalone endpoints return their list directly; `/registrations`
    can return a single object, so a bare dict is wrapped into a one-element list.
    """
    if data_key is not None:
        if isinstance(data, dict):
            value = data.get(data_key) or []
            return value if isinstance(value, list) else [value]
        return []

    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return [data]
    return []


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    config = EVENTEE_ENDPOINTS[endpoint]
    session = _get_session(api_key)

    @retry(
        retry=retry_if_exception_type((EventeeRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=2, max=60),
        reraise=True,
    )
    def fetch(path: str) -> Any:
        url = f"{EVENTEE_BASE_URL}{path}"
        response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code == 429 or response.status_code >= 500:
            raise EventeeRetryableError(f"Eventee API error (retryable): status={response.status_code}, url={url}")

        if not response.ok:
            logger.error(f"Eventee API error: status={response.status_code}, body={response.text}, url={url}")
            response.raise_for_status()

        return response.json()

    # Every endpoint returns its whole collection in a single response — no pagination.
    rows = _extract_rows(fetch(config.path), config.data_key)
    if rows:
        yield rows


def eventee_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
) -> SourceResponse:
    config = EVENTEE_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(api_key=api_key, endpoint=endpoint, logger=logger),
        primary_keys=config.primary_keys,
        partition_count=1 if config.partition_key else None,
        partition_size=1 if config.partition_key else None,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode="asc",
    )
