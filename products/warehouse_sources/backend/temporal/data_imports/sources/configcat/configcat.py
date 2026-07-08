import base64
from collections.abc import Iterator
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.configcat.settings import CONFIGCAT_ENDPOINTS

CONFIGCAT_BASE_URL = "https://api.configcat.com"
REQUEST_TIMEOUT_SECONDS = 60
# Cheap org-level list used to confirm the Public API credential is genuine. The credential is
# account-wide, so one probe validates access to every list endpoint.
DEFAULT_PROBE_PATH = "/v1/organizations"


class ConfigCatRetryableError(Exception):
    pass


def _headers(username: str, password: str) -> dict[str, str]:
    # ConfigCat's Public Management API authenticates with HTTP Basic credentials (a username and
    # password pair generated on the Public API credentials page — not the SDK keys).
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}", "Accept": "application/json"}


@retry(
    retry=retry_if_exception_type((ConfigCatRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch(session: requests.Session, path: str, logger: FilteringBoundLogger) -> list[dict[str, Any]]:
    response = session.get(f"{CONFIGCAT_BASE_URL}{path}", timeout=REQUEST_TIMEOUT_SECONDS)

    # 429 (documented ~20 req/sec, ~500 req/min per endpoint) and transient 5xx are retryable.
    if response.status_code == 429 or response.status_code >= 500:
        raise ConfigCatRetryableError(f"ConfigCat API error (retryable): status={response.status_code}, path={path}")

    if not response.ok:
        logger.error(f"ConfigCat API error: status={response.status_code}, body={response.text}, path={path}")
        response.raise_for_status()

    data = response.json()
    # The Public Management API list endpoints return a bare JSON array of records.
    if not isinstance(data, list):
        raise ConfigCatRetryableError(f"ConfigCat returned an unexpected payload for {path}: {type(data).__name__}")
    return data


def get_rows(
    username: str,
    password: str,
    endpoint: str,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    config = CONFIGCAT_ENDPOINTS[endpoint]
    session = make_tracked_session(headers=_headers(username, password), redact_values=(username, password))

    # No pagination: the list endpoint returns the full collection in one response.
    items = _fetch(session, config.path, logger)
    if items:
        yield items


def configcat_source(
    username: str,
    password: str,
    endpoint: str,
    logger: FilteringBoundLogger,
) -> SourceResponse:
    config = CONFIGCAT_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            username=username,
            password=password,
            endpoint=endpoint,
            logger=logger,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
    )


def check_access(username: str, password: str, path: str = DEFAULT_PROBE_PATH) -> tuple[int, Optional[str]]:
    """Probe a single endpoint to validate the Public API credential.

    Returns ``(status, message)``: ``200`` reachable, ``401``/``403`` auth failure, ``0`` for a
    connection problem, other HTTP status otherwise.
    """
    session = make_tracked_session(headers=_headers(username, password), redact_values=(username, password))
    try:
        response = session.get(f"{CONFIGCAT_BASE_URL}{path}", timeout=15)
    except Exception as e:
        return 0, f"Could not connect to ConfigCat: {e}"

    if response.status_code in (401, 403):
        return response.status_code, None

    if not response.ok:
        return response.status_code, f"ConfigCat returned HTTP {response.status_code}"

    return 200, None


def validate_credentials(username: str, password: str) -> tuple[bool, str | None]:
    status, message = check_access(username, password)
    if status == 200:
        return True, None
    if status in (401, 403):
        return False, "Invalid ConfigCat Public API credentials"
    return False, message or "Could not validate ConfigCat Public API credentials"
