from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional

import requests
from requests.exceptions import RequestException
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.shortcut.settings import (
    SHORTCUT_ENDPOINTS,
    ShortcutEndpointConfig,
)

SHORTCUT_BASE_URL = "https://api.app.shortcut.com/api/v3"
REQUEST_TIMEOUT = 60
MAX_RETRIES = 5


class ShortcutRetryableError(Exception):
    """Raised for transient Shortcut API failures (429 / 5xx) so tenacity retries them."""

    pass


def _get_headers(api_token: str) -> dict[str, str]:
    return {
        "Shortcut-Token": api_token,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _format_incremental_value(value: Any) -> str:
    """Format an incremental cursor value for Shortcut's `*_start` search filters (RFC 3339)."""
    if isinstance(value, datetime):
        utc_dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    return str(value)


def _build_search_body(
    config: ShortcutEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> dict[str, Any]:
    """Build the JSON body for `POST /stories/search`.

    Maps the user-selected incremental field to the matching server-side filter param.
    An empty body returns the full collection (initial sync / full refresh).
    """
    body: dict[str, Any] = {}
    if should_use_incremental_field and db_incremental_field_last_value is not None:
        field_name = incremental_field or "updated_at"
        param = config.incremental_params.get(field_name)
        if param:
            body[param] = _format_incremental_value(db_incremental_field_last_value)
    return body


def _parse_response(response: requests.Response, url: str, logger: FilteringBoundLogger) -> Any:
    """Classify a Shortcut response: retry on 429/5xx, fail on other 4xx, else return JSON."""
    # Shortcut returns 429 when the 200 req/min limit is exceeded, without documented
    # rate-limit headers, so we fall back to exponential backoff for those (and 5xx).
    if response.status_code == 429 or response.status_code >= 500:
        raise ShortcutRetryableError(f"Shortcut API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Shortcut API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def validate_credentials(api_token: str) -> tuple[bool, str | None]:
    """Probe the cheapest authenticated endpoint to confirm the token is genuine."""
    url = f"{SHORTCUT_BASE_URL}/member"
    try:
        with make_tracked_session(headers=_get_headers(api_token), redact_values=(api_token,)) as session:
            response = session.get(url, timeout=10)
    except RequestException as e:
        return False, str(e)

    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return False, "Invalid Shortcut API token. Generate a new token in Settings > API Tokens and reconnect."
    if response.status_code == 403:
        return False, "Your Shortcut API token does not have access to this workspace. Please check its permissions."
    return False, f"Shortcut API returned an unexpected status: {response.status_code}"


def get_rows(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[Any]:
    config = SHORTCUT_ENDPOINTS[endpoint]
    url = f"{SHORTCUT_BASE_URL}{config.path}"

    with make_tracked_session(headers=_get_headers(api_token), redact_values=(api_token,)) as session:

        @retry(
            retry=retry_if_exception_type((ShortcutRetryableError, requests.ReadTimeout, requests.ConnectionError)),
            stop=stop_after_attempt(MAX_RETRIES),
            wait=wait_exponential_jitter(initial=1, max=60),
            reraise=True,
        )
        def fetch(method: str, body: Optional[dict[str, Any]]) -> Any:
            response = session.request(method, url, json=body, timeout=REQUEST_TIMEOUT)
            return _parse_response(response, url, logger)

        if config.method == "POST":
            body = _build_search_body(
                config, should_use_incremental_field, db_incremental_field_last_value, incremental_field
            )
            data = fetch("POST", body)
        else:
            data = fetch("GET", None)

    # Every Shortcut list endpoint (and the stories search) returns a bare JSON array.
    if not isinstance(data, list):
        logger.warning(f"Shortcut endpoint {endpoint} returned a non-list response; skipping")
        return

    if data:
        yield data


def shortcut_source(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = SHORTCUT_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_token=api_token,
            endpoint=endpoint,
            logger=logger,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        ),
        primary_keys=[config.primary_key],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
