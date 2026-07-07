from collections.abc import Iterator
from typing import Any
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter
from urllib3.util.retry import Retry

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.google_webfonts.settings import (
    GOOGLE_WEBFONTS_ENDPOINTS,
)

GOOGLE_WEBFONTS_BASE_URL = "https://www.googleapis.com"
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRY_ATTEMPTS = 5


class GoogleWebfontsRetryableError(Exception):
    pass


def _get_session(api_key: str) -> requests.Session:
    # The key is sent via the `X-goog-api-key` header rather than the `key` query param so it
    # never lands in a logged request URL. Google accepts either form.
    # `retry=Retry(total=0)` disables the adapter's default retries so tenacity is the single
    # retry layer — otherwise the two stack and multiply the backoff on 429/5xx.
    return make_tracked_session(
        headers={"X-goog-api-key": api_key, "Accept": "application/json"},
        redact_values=(api_key,),
        retry=Retry(total=0),
    )


def _build_url(path: str, params: dict[str, Any]) -> str:
    query = urlencode(params)
    return f"{GOOGLE_WEBFONTS_BASE_URL}{path}?{query}" if query else f"{GOOGLE_WEBFONTS_BASE_URL}{path}"


def validate_credentials(api_key: str) -> bool:
    """Confirm the API key is valid with a single catalog probe.

    An invalid key returns 400 (`API_KEY_INVALID`) and a missing key 403; only a genuine key
    returns 200. Connection-level failures (DNS, timeout, reset) raise `requests.RequestException`
    so the caller can tell "unreachable" apart from "invalid key" instead of blaming the credential.
    """
    config = GOOGLE_WEBFONTS_ENDPOINTS["webfonts"]
    params = {"sort": config.sort} if config.sort else {}
    response = _get_session(api_key).get(
        _build_url(config.path, params),
        timeout=10,
    )
    return response.status_code == 200


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    config = GOOGLE_WEBFONTS_ENDPOINTS[endpoint]
    session = _get_session(api_key)

    @retry(
        retry=retry_if_exception_type(
            (
                GoogleWebfontsRetryableError,
                requests.ReadTimeout,
                requests.ConnectionError,
                requests.exceptions.ChunkedEncodingError,
            )
        ),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=1, max=30),
        reraise=True,
    )
    def fetch(path: str, params: dict[str, Any]) -> dict[str, Any]:
        url = _build_url(path, params)
        response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code == 429 or response.status_code >= 500:
            raise GoogleWebfontsRetryableError(
                f"Google Webfonts API error (retryable): status={response.status_code}, url={url}"
            )

        if not response.ok:
            logger.error(f"Google Webfonts API error: status={response.status_code}, body={response.text}, url={url}")
            response.raise_for_status()

        return response.json()

    params: dict[str, Any] = {}
    if config.sort:
        params["sort"] = config.sort

    # The endpoint is unpaginated: the whole catalog arrives in a single `items` array.
    data = fetch(config.path, params)
    items = data.get(config.data_selector, []) or []
    if items:
        yield items


def google_webfonts_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
) -> SourceResponse:
    config = GOOGLE_WEBFONTS_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        sort_mode="asc",
    )
