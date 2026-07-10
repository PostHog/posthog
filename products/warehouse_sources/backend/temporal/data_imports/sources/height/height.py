from collections.abc import Iterator
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.height.settings import HEIGHT_ENDPOINTS

HEIGHT_BASE_URL = "https://api.height.app"
REQUEST_TIMEOUT_SECONDS = 60
# Cheap endpoint used to confirm an API key is genuine. The key is workspace-wide, so one probe
# validates access to every list endpoint.
DEFAULT_PROBE_PATH = "/users"


class HeightRetryableError(Exception):
    pass


def _headers(api_key: str) -> dict[str, str]:
    # Height's scheme is the literal word `api-key` followed by the secret, not a Bearer token.
    return {"Authorization": f"api-key {api_key}", "Accept": "application/json"}


@retry(
    retry=retry_if_exception_type((HeightRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_list(
    session: requests.Session,
    path: str,
    logger: FilteringBoundLogger,
) -> list[dict[str, Any]]:
    response = session.get(
        f"{HEIGHT_BASE_URL}{path}",
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    if response.status_code == 429 or response.status_code >= 500:
        raise HeightRetryableError(f"Height API error (retryable): status={response.status_code}, path={path}")

    if not response.ok:
        logger.error(f"Height API error: status={response.status_code}, body={response.text}, path={path}")
        response.raise_for_status()

    data = response.json()
    # Height list endpoints wrap records in a top-level `list` key.
    if not isinstance(data, dict) or not isinstance(data.get("list"), list):
        raise HeightRetryableError(f"Height returned an unexpected payload for {path}: {type(data).__name__}")
    return data["list"]


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    config = HEIGHT_ENDPOINTS[endpoint]
    session = make_tracked_session(headers=_headers(api_key), redact_values=(api_key,))

    # These endpoints are unpaginated single-shot lists, so one request returns the full collection.
    rows = _fetch_list(session, config.path, logger)
    if rows:
        yield rows


def height_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
) -> SourceResponse:
    config = HEIGHT_ENDPOINTS[endpoint]

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
        response = session.get(f"{HEIGHT_BASE_URL}{path}", timeout=15)
    except Exception as e:
        return 0, f"Could not connect to Height: {e}"

    if response.status_code in (401, 403):
        return response.status_code, None

    if not response.ok:
        return response.status_code, f"Height returned HTTP {response.status_code}"

    return 200, None


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    status, message = check_access(api_key)
    if status == 200:
        return True, None
    if status in (401, 403):
        return False, "Invalid Height API key"
    return False, message or "Could not validate Height API key"
