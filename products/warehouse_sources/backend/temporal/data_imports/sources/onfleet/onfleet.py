import base64
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.onfleet.settings import (
    ONFLEET_ENDPOINTS,
    OnfleetEndpointConfig,
)

ONFLEET_BASE_URL = "https://onfleet.com/api/v2"
# Onfleet enforces an internal 70s timeout on large list endpoints (e.g. /workers) before
# returning a 502, so give each request room up to that boundary.
REQUEST_TIMEOUT_SECONDS = 70
MAX_RETRIES = 5
# `/tasks/all` requires a `from` param; epoch 0 pulls the full history on the initial/full sync.
DEFAULT_FROM_MS = 0


class OnfleetRetryableError(Exception):
    pass


@dataclasses.dataclass
class OnfleetResumeConfig:
    # The `lastId` cursor returned by the previous page; the next request continues after it.
    last_id: str
    # The `from` epoch-ms lower bound in effect for this sync, re-sent on every page so the
    # server-side window stays applied across the whole paginated walk.
    from_ms: int


def _basic_auth_token(api_key: str) -> str:
    # Onfleet uses HTTP Basic auth with the API key as the username and an empty password.
    return base64.b64encode(f"{api_key}:".encode("ascii")).decode("ascii")


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Basic {_basic_auth_token(api_key)}",
        "Accept": "application/json",
    }


def _to_epoch_ms(value: Any) -> Optional[int]:
    """Coerce an incremental cursor value to UNIX epoch milliseconds for Onfleet's `from` filter.

    Onfleet stores and filters timestamps as epoch milliseconds, so the persisted watermark is
    already an int in the common case; datetimes/dates are accepted defensively.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, datetime):
        dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return int(dt.timestamp() * 1000)
    if isinstance(value, date):
        return int(datetime.combine(value, datetime.min.time(), tzinfo=UTC).timestamp() * 1000)
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _build_url(path: str, params: dict[str, Any]) -> str:
    clean = {key: value for key, value in params.items() if value is not None}
    if not clean:
        return f"{ONFLEET_BASE_URL}{path}"
    return f"{ONFLEET_BASE_URL}{path}?{urlencode(clean)}"


@retry(
    retry=retry_if_exception_type((OnfleetRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(MAX_RETRIES),
    wait=wait_exponential_jitter(initial=1, max=60),
    reraise=True,
)
def _fetch(session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger) -> Any:
    response = session.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

    # Onfleet rate-limits at 20 req/s org-wide (429) and returns 502 on the internal timeout.
    if response.status_code == 429 or response.status_code >= 500:
        raise OnfleetRetryableError(f"Onfleet API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Onfleet API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def get_credentials_status(api_key: str) -> Optional[int]:
    """Return the HTTP status of a cheap authenticated probe, or None on transport failure.

    `/organization` returns the caller's own organization — a light authenticated endpoint that
    only confirms the API key is genuine, not per-endpoint scope.
    """
    try:
        response = make_tracked_session().get(
            f"{ONFLEET_BASE_URL}/organization", headers=_get_headers(api_key), timeout=10
        )
        return response.status_code
    except Exception:
        return None


def _get_paginated_rows(
    session: requests.Session,
    headers: dict[str, str],
    config: OnfleetEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[OnfleetResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    """Walk `/tasks/all` via the `lastId` cursor, bounded by the server-side `from` window."""
    from_ms = _to_epoch_ms(db_incremental_field_last_value) if should_use_incremental_field else None
    if from_ms is None:
        from_ms = DEFAULT_FROM_MS

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    last_id: str | None = None
    if resume is not None:
        last_id = resume.last_id
        from_ms = resume.from_ms
        logger.debug(f"Onfleet: resuming {config.name} from lastId={last_id}, from={from_ms}")

    while True:
        params: dict[str, Any] = {"from": from_ms}
        if last_id:
            params["lastId"] = last_id

        data = _fetch(session, _build_url(config.path, params), headers, logger)
        items = data.get(config.data_key, []) or []
        next_id = data.get("lastId")

        if items:
            yield items
            # Save AFTER yielding so a crash re-yields the last page rather than skipping it —
            # merge dedupes the re-pulled rows on the primary key.
            if next_id and next_id != last_id:
                resumable_source_manager.save_state(OnfleetResumeConfig(last_id=next_id, from_ms=from_ms))

        # A missing (or non-advancing) lastId marks the final page.
        if not next_id or next_id == last_id:
            break
        last_id = next_id


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[OnfleetResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = ONFLEET_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)
    # One session reused across every page so urllib3 keeps the connection alive.
    session = make_tracked_session()

    if config.paginated:
        yield from _get_paginated_rows(
            session,
            headers,
            config,
            logger,
            resumable_source_manager,
            should_use_incremental_field,
            db_incremental_field_last_value,
        )
        return

    # Every other endpoint returns the full collection in a single response with no pagination.
    data = _fetch(session, _build_url(config.path, {}), headers, logger)
    if config.single_object:
        if data:
            yield [data]
    elif data:
        yield data


def onfleet_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[OnfleetResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = ONFLEET_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        # `/tasks/all` returns rows ascending by creation time; the single-batch endpoints are
        # order-insensitive. Onfleet timestamps are epoch-ms integers, which the datetime
        # partitioner would misbucket (it treats ints as epoch seconds), so partitioning is off.
        sort_mode="asc",
    )
