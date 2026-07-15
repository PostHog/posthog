from collections.abc import Iterator
from typing import Any
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.airops.settings import AIROPS_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session

AIROPS_BASE_URL = "https://api.airops.com"
# The executions endpoint caps `items` at 100.
EXECUTIONS_PAGE_SIZE = 100


class AirOpsRetryableError(Exception):
    """Raised for AirOps responses that are safe to retry (429 / 5xx)."""


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }


def _make_session(api_key: str) -> requests.Session:
    """Session for all AirOps traffic. The bearer token is set once on the session (so its redaction
    policy applies to every request and captured sample) and redirects are pinned off so a credentialed
    request can't be replayed against another host. Response capture is disabled because executions
    carry free-form `inputs`/`output` under arbitrary keys — a user can place credentials or other
    secrets there, and the name-based sample scrubbers can't reliably recognise them."""
    return make_tracked_session(
        headers=_get_headers(api_key),
        redact_values=(api_key,),
        allow_redirects=False,
        capture=False,
    )


@retry(
    retry=retry_if_exception_type(
        (
            AirOpsRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_json(session: requests.Session, url: str, logger: FilteringBoundLogger) -> Any:
    response = session.get(url, timeout=60)

    if response.status_code == 429 or response.status_code >= 500:
        raise AirOpsRetryableError(f"AirOps API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"AirOps API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def _iter_apps(session: requests.Session, logger: FilteringBoundLogger) -> Iterator[dict]:
    """List every app. The apps endpoint returns a plain (unwrapped) JSON array with no pagination."""
    data = _fetch_json(session, f"{AIROPS_BASE_URL}/public_api/airops_apps", logger)
    if not isinstance(data, list):
        # Defensive: the docs describe a bare array, but tolerate a `{data: [...]}` envelope if the
        # beta API ever wraps it, rather than crashing the sync.
        data = data.get("data", []) if isinstance(data, dict) else []
    yield from data


def _get_apps(session: requests.Session, logger: FilteringBoundLogger) -> Iterator[list[dict]]:
    apps = list(_iter_apps(session, logger))
    if apps:
        yield apps


def _get_executions(session: requests.Session, logger: FilteringBoundLogger) -> Iterator[list[dict]]:
    """Fan out over every app and page through its executions.

    Executions can only be listed per app, so we enumerate apps first and follow each app's
    cursor-paginated executions endpoint. Each row is stamped with `airops_app_id` so the flattened
    table can be joined back to its parent app (and so the primary key stays meaningful table-wide).
    """
    for app in _iter_apps(session, logger):
        # The app id is required to reach the child endpoint; a missing id means we'd silently drop an
        # app's executions, so fail loudly rather than sync partial data.
        app_id = app["id"]

        cursor: str | None = None
        while True:
            params: dict[str, Any] = {"airops_app_id": app_id, "items": EXECUTIONS_PAGE_SIZE}
            if cursor:
                params["cursor"] = cursor
            url = f"{AIROPS_BASE_URL}/public_api/airops_apps/{app_id}/executions?{urlencode(params)}"

            data = _fetch_json(session, url, logger)
            records = data.get("data", []) if isinstance(data, dict) else []
            for record in records:
                record["airops_app_id"] = app_id
            if records:
                yield records

            meta = data.get("meta", {}) if isinstance(data, dict) else {}
            cursor = meta.get("cursor")
            # Keep paging while a cursor is present. Only stop when the cursor runs out or `has_more`
            # is explicitly false, so a response that returns a cursor without `has_more` isn't dropped.
            if not cursor or meta.get("has_more") is False:
                break


def get_rows(api_key: str, endpoint: str, logger: FilteringBoundLogger) -> Iterator[list[dict]]:
    session = _make_session(api_key)

    if endpoint == "apps":
        yield from _get_apps(session, logger)
    elif endpoint == "executions":
        yield from _get_executions(session, logger)
    else:
        raise ValueError(f"Unknown AirOps endpoint: {endpoint}")


def airops_source(api_key: str, endpoint: str, logger: FilteringBoundLogger) -> SourceResponse:
    endpoint_config = AIROPS_ENDPOINTS[endpoint]

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


def validate_credentials(api_key: str) -> bool:
    """Cheapest probe that confirms the workspace API key is genuine: list apps and check for a 200."""
    try:
        response = _make_session(api_key).get(f"{AIROPS_BASE_URL}/public_api/airops_apps", timeout=10)
        return response.status_code == 200
    except Exception:
        return False
