from collections.abc import Iterator
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.my_hours.settings import MY_HOURS_ENDPOINTS

MY_HOURS_BASE_URL = "https://api2.myhours.com/api"
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRY_ATTEMPTS = 5
# Cheap list endpoint used to confirm an API key is genuine. The key is account-wide, so one probe
# validates access to every list endpoint.
DEFAULT_PROBE_PATH = "/Clients"


class MyHoursRetryableError(Exception):
    pass


def _headers(api_key: str) -> dict[str, str]:
    # My Hours expects the literal `apikey ` prefix before the key; omitting it (or using `Bearer`)
    # returns 400/401.
    return {"Authorization": f"apikey {api_key}", "Accept": "application/json"}


@retry(
    retry=retry_if_exception_type((MyHoursRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch(session: requests.Session, path: str, logger: FilteringBoundLogger) -> list[dict[str, Any]]:
    response = session.get(f"{MY_HOURS_BASE_URL}{path}", timeout=REQUEST_TIMEOUT_SECONDS)

    # 429 (the API throttles at ~100 calls/60s) and transient 5xx are retryable; back off and retry.
    if response.status_code == 429 or response.status_code >= 500:
        raise MyHoursRetryableError(f"My Hours API error (retryable): status={response.status_code}, path={path}")

    if not response.ok:
        logger.error(f"My Hours API error: status={response.status_code}, body={response.text}, path={path}")
        response.raise_for_status()

    data = response.json()
    # My Hours list endpoints return a bare JSON array of records.
    if not isinstance(data, list):
        raise MyHoursRetryableError(f"My Hours returned an unexpected payload for {path}: {type(data).__name__}")
    return data


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    config = MY_HOURS_ENDPOINTS[endpoint]
    session = make_tracked_session(headers=_headers(api_key), redact_values=(api_key,))

    # The list endpoints are unpaginated, so a single request returns the whole collection.
    items = _fetch(session, config.path, logger)
    if items:
        yield items


def my_hours_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
) -> SourceResponse:
    config = MY_HOURS_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(api_key=api_key, endpoint=endpoint, logger=logger),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
    )


def check_access(api_key: str, path: str = DEFAULT_PROBE_PATH) -> tuple[int, Optional[str]]:
    """Probe a single endpoint to validate the API key.

    Returns ``(status, message)``: ``200`` reachable, ``401``/``403`` auth failure, ``0`` for a
    connection problem, other HTTP status otherwise.
    """
    session = make_tracked_session(headers=_headers(api_key), redact_values=(api_key,))
    try:
        response = session.get(f"{MY_HOURS_BASE_URL}{path}", timeout=15)
    except Exception as e:
        return 0, f"Could not connect to My Hours: {e}"

    if response.status_code in (401, 403):
        return response.status_code, None

    if not response.ok:
        return response.status_code, f"My Hours returned HTTP {response.status_code}"

    return 200, None


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    status, message = check_access(api_key)
    if status == 200:
        return True, None
    if status in (401, 403):
        return False, "Invalid My Hours API key"
    return False, message or "Could not validate My Hours API key"
