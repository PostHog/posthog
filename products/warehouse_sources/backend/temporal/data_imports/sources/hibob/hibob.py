from collections.abc import Iterator
from typing import Any

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.hibob.settings import HIBOB_ENDPOINTS

HIBOB_BASE_URL = "https://api.hibob.com"
REQUEST_TIMEOUT_SECONDS = 120
# Rate limits are per endpoint (people/search is 50 req/min); 429s carry
# X-RateLimit headers but exponential backoff is sufficient. Repeated 401/403s
# trigger a 5-minute WAF block, so auth errors must never be retried.
MAX_RETRY_ATTEMPTS = 5


class HiBobRetryableError(Exception):
    pass


def _get_session(service_user_id: str, service_user_token: str) -> requests.Session:
    session = make_tracked_session(redact_values=(service_user_token,))
    session.auth = (service_user_id, service_user_token)
    return session


def validate_credentials(service_user_id: str, service_user_token: str) -> tuple[bool, str | None]:
    """Confirm the service user credentials are valid with a cheap tasks probe.

    Service users need explicit per-category permission grants (403); only 401
    means the credentials themselves are bad. Transport failures surface their
    real reason rather than masquerading as an auth error."""
    session = _get_session(service_user_id, service_user_token)
    try:
        response = session.get(f"{HIBOB_BASE_URL}/v1/tasks", timeout=10)
        if response.status_code == 401:
            return False, "Invalid HiBob Service User credentials"
        return True, None
    except Exception as e:
        return False, str(e)
    finally:
        session.close()


def get_rows(
    service_user_id: str,
    service_user_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    config = HIBOB_ENDPOINTS[endpoint]
    session = _get_session(service_user_id, service_user_token)
    url = f"{HIBOB_BASE_URL}{config.path}"

    @retry(
        retry=retry_if_exception_type((HiBobRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=2, max=90),
        reraise=True,
    )
    def fetch() -> dict[str, Any]:
        if config.method == "POST":
            response = session.post(url, json=config.body or {}, timeout=REQUEST_TIMEOUT_SECONDS)
        else:
            response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code == 429 or response.status_code >= 500:
            raise HiBobRetryableError(f"HiBob API error (retryable): status={response.status_code}, url={url}")

        if not response.ok:
            logger.error(f"HiBob API error: status={response.status_code}, body={response.text}, url={url}")
            response.raise_for_status()

        return response.json()

    # Both shipped endpoints return their full result set in one response.
    try:
        data = fetch()
        items = data.get(config.data_key, []) or []
        if items:
            yield items
    finally:
        session.close()


def hibob_source(
    service_user_id: str,
    service_user_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
) -> SourceResponse:
    config = HIBOB_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            service_user_id=service_user_id,
            service_user_token=service_user_token,
            endpoint=endpoint,
            logger=logger,
        ),
        primary_keys=[config.primary_key],
        partition_count=1,
        partition_size=1,
        sort_mode="asc",
    )
