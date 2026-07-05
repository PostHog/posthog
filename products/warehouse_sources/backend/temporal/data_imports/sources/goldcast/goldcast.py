from collections.abc import Iterator
from typing import Any

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.goldcast.settings import (
    GOLDCAST_ENDPOINTS,
    GoldcastEndpointConfig,
)

GOLDCAST_BASE_URL = "https://customapi.goldcast.io"

REQUEST_TIMEOUT_SECONDS = 60


class GoldcastRetryableError(Exception):
    pass


def _get_headers(access_key: str) -> dict[str, str]:
    # Goldcast uses a static personal access token with the non-standard `Token` scheme
    # (not `Bearer`), created by an org admin in Studio Settings > Tokens.
    return {
        "Authorization": f"Token {access_key}",
        "Accept": "application/json",
    }


@retry(
    retry=retry_if_exception_type(
        (
            GoldcastRetryableError,
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
    response = session.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429 or response.status_code >= 500:
        raise GoldcastRetryableError(f"Goldcast API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        # Only a tightly capped excerpt of the body is logged: Goldcast error bodies can echo
        # customer tenant records, so the full response must never land verbatim in our logs.
        body_excerpt = response.text[:200]
        logger.error(f"Goldcast API error: status={response.status_code}, body_excerpt={body_excerpt!r}, url={url}")
        response.raise_for_status()

    return response.json()


def _extract_rows(data: Any) -> list[dict[str, Any]]:
    """Normalize a Goldcast response into a list of row dicts.

    Collection endpoints return a bare JSON array; the single-object organization endpoint may
    return an object. Some deployments could wrap results in a `results`/`data` envelope, so those
    are unwrapped defensively.
    """
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if isinstance(data, dict):
        for key in ("results", "data"):
            inner = data.get(key)
            if isinstance(inner, list):
                return [row for row in inner if isinstance(row, dict)]
        return [data]
    return []


def validate_credentials(access_key: str) -> bool:
    # `/core/organization/` is the cheapest authenticated probe (a single org object). A 200 means
    # the token is genuine and API access is enabled for the account.
    url = f"{GOLDCAST_BASE_URL}/core/organization/"
    try:
        # `redact_values` masks the token from any captured HTTP sample — it rides in the
        # non-standard `Token` auth header the name-based scrubbers can't recognise.
        response = make_tracked_session(redact_values=(access_key,)).get(
            url, headers=_get_headers(access_key), timeout=10
        )
        return response.status_code == 200
    except Exception:
        return False


def _iter_event_ids(session: requests.Session, headers: dict[str, str], logger: FilteringBoundLogger) -> Iterator[str]:
    """Yield every event id, used to drive the per-event fan-out endpoints."""
    data = _fetch(session, f"{GOLDCAST_BASE_URL}/event/", headers, logger)
    for event in _extract_rows(data):
        # `id` is the required fan-out key: a missing or empty value must raise loudly rather than
        # silently under-syncing its webinars/event_members with no signal in the logs.
        event_id = event["id"]
        if not event_id:
            raise ValueError(f"Goldcast event is missing a valid id: {event}")
        yield str(event_id)


def _get_fan_out_rows(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    config: GoldcastEndpointConfig,
) -> Iterator[list[dict[str, Any]]]:
    """Fetch a child endpoint once per event, stamping the parent event id onto each row."""
    for event_id in _iter_event_ids(session, headers, logger):
        url = f"{GOLDCAST_BASE_URL}{config.path.format(event=event_id)}"
        try:
            data = _fetch(session, url, headers, logger)
        except requests.HTTPError as exc:
            # An event with no child resources (or one deleted between enumeration and this fetch)
            # can 404. Skip it rather than failing the whole sync; any other error is re-raised.
            if exc.response is not None and exc.response.status_code == 404:
                logger.warning(f"Goldcast: {config.name} not found for event {event_id}, skipping")
                continue
            raise

        rows = _extract_rows(data)
        for row in rows:
            row[config.parent_event_field] = event_id
        if rows:
            yield rows


def get_rows(
    access_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    config = GOLDCAST_ENDPOINTS[endpoint]
    headers = _get_headers(access_key)
    # One session reused across every request so urllib3 keeps the connection alive.
    # `redact_values` masks the token from captured samples — it rides in the non-standard
    # `Token` auth header the name-based scrubbers can't recognise.
    session = make_tracked_session(redact_values=(access_key,))

    if config.fan_out_over_events:
        yield from _get_fan_out_rows(session, headers, logger, config)
        return

    data = _fetch(session, f"{GOLDCAST_BASE_URL}{config.path}", headers, logger)
    rows = _extract_rows(data)
    if rows:
        yield rows


def goldcast_source(
    access_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
) -> SourceResponse:
    endpoint_config = GOLDCAST_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(access_key=access_key, endpoint=endpoint, logger=logger),
        primary_keys=endpoint_config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="week" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )
