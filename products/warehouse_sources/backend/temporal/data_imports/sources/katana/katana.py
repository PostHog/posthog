import time
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import RetryCallState, retry, retry_if_exception_type, stop_after_attempt

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.katana.settings import (
    KATANA_ENDPOINTS,
    KatanaEndpointConfig,
)

KATANA_BASE_URL = "https://api.katanamrp.com/v1"
# Katana caps list pages at 250 rows; use the max to minimise request count against the 60 req/min limit.
PAGE_SIZE = 250
# Katana allows 60 requests per 60 seconds. Space requests ~1/s so a large backfill stays under the
# limit instead of relying on 429 backoff for every page.
REQUEST_INTERVAL_SECONDS = 1.1
MAX_ATTEMPTS = 6
MAX_BACKOFF_SECONDS = 60.0


class KatanaRetryableError(Exception):
    """Transient server-side failure (5xx) that should be retried."""


class KatanaRateLimitError(Exception):
    """429 response. Carries the server's Retry-After hint (seconds) when present."""

    def __init__(self, retry_after: float | None) -> None:
        super().__init__("Katana rate limit exceeded")
        self.retry_after = retry_after


@dataclasses.dataclass
class KatanaResumeConfig:
    # Next page to fetch. On resume we re-fetch this page in full — a batch may be yielded mid-page,
    # so re-reading the whole page recovers any un-yielded tail; the delta merge dedupes the overlap.
    page: int = 1


class _Throttle:
    """Spaces outbound requests to honour Katana's 60 req/min budget without per-request 429s."""

    def __init__(self, interval_seconds: float) -> None:
        self._interval = interval_seconds
        self._last_request_at: float | None = None

    def wait(self) -> None:
        if self._last_request_at is not None:
            elapsed = time.monotonic() - self._last_request_at
            if elapsed < self._interval:
                time.sleep(self._interval - elapsed)
        self._last_request_at = time.monotonic()


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }


def _format_datetime_z(dt: datetime) -> str:
    """ISO 8601 with millisecond precision and a Z suffix (Katana filters expect ISO 8601)."""
    utc_dt = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    return utc_dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _format_incremental_value(value: Any) -> str:
    if isinstance(value, datetime):
        return _format_datetime_z(value)
    if isinstance(value, date):
        return _format_datetime_z(datetime.combine(value, datetime.min.time(), tzinfo=UTC))
    return str(value)


def _clamp_future_value_to_now(value: Any) -> Any:
    """Cap a future cursor at now so we never send a future `<field>_min` filter (a no-op that could
    otherwise wedge the sync if the source has future-dated rows)."""
    now = datetime.now(UTC)
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return now if aware > now else value
    if isinstance(value, date):
        return now.date() if value > now.date() else value
    return value


def _build_base_params(
    config: KatanaEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> dict[str, Any]:
    """Query params shared by every page of a sync (the server-side timestamp filter)."""
    params: dict[str, Any] = {}

    if should_use_incremental_field and db_incremental_field_last_value and config.incremental_fields:
        field_name = incremental_field or config.default_incremental_field
        clamped = _clamp_future_value_to_now(db_incremental_field_last_value)
        params[f"{field_name}_min"] = _format_incremental_value(clamped)

    return params


def _wait_katana(retry_state: RetryCallState) -> float:
    """Honour the server's Retry-After on 429; otherwise exponential backoff."""
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    if isinstance(exc, KatanaRateLimitError) and exc.retry_after is not None:
        return min(exc.retry_after, MAX_BACKOFF_SECONDS)
    return min(2.0**retry_state.attempt_number, MAX_BACKOFF_SECONDS)


def _request_page(
    session: requests.Session,
    url: str,
    params: dict[str, Any],
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    throttle: _Throttle,
) -> dict:
    """Single throttled request. Raises the retryable/terminal errors `_fetch_page` retries on."""
    throttle.wait()
    response = session.get(url, params=params, headers=headers, timeout=60)

    if response.status_code == 429:
        retry_after_header = response.headers.get("Retry-After")
        retry_after = float(retry_after_header) if retry_after_header else None
        raise KatanaRateLimitError(retry_after)

    if response.status_code >= 500:
        raise KatanaRetryableError(f"Katana API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Katana API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


@retry(
    retry=retry_if_exception_type(
        (
            KatanaRetryableError,
            KatanaRateLimitError,
            requests.ConnectionError,
            requests.ReadTimeout,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    wait=_wait_katana,
    stop=stop_after_attempt(MAX_ATTEMPTS),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    url: str,
    params: dict[str, Any],
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    throttle: _Throttle,
) -> dict:
    return _request_page(session, url, params, headers, logger, throttle)


def validate_credentials(api_key: str) -> bool:
    """Cheap token probe: `/user_info` returns 200 for a valid key regardless of resource scopes."""
    try:
        response = make_tracked_session().get(f"{KATANA_BASE_URL}/user_info", headers=_get_headers(api_key), timeout=15)
        return response.status_code == 200
    except Exception:
        return False


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[KatanaResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[Any]:
    config = KATANA_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)
    session = make_tracked_session()
    throttle = _Throttle(REQUEST_INTERVAL_SECONDS)
    batcher = Batcher(logger=logger, chunk_size=5000, chunk_size_bytes=200 * 1024 * 1024)

    base_params = _build_base_params(
        config, should_use_incremental_field, db_incremental_field_last_value, incremental_field
    )

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page = resume.page if resume else 1
    if resume:
        logger.debug(f"Katana: resuming {endpoint} from page {page}")

    url = f"{KATANA_BASE_URL}{config.path}"

    while True:
        params = {**base_params, "page": page, "limit": PAGE_SIZE}
        data = _fetch_page(session, url, params, headers, logger, throttle)
        items = data.get("data", [])

        for item in items:
            batcher.batch(item)
            if batcher.should_yield():
                yield batcher.get_table()
                # Save AFTER yielding, pointing at the CURRENT page: a crash re-reads this page in full
                # (recovering its un-yielded tail) and the merge dedupes the already-written prefix.
                resumable_source_manager.save_state(KatanaResumeConfig(page=page))

        # A short (or empty) page is the last one — Katana has no next-page cursor to follow.
        if len(items) < PAGE_SIZE:
            break

        page += 1

    if batcher.should_yield(include_incomplete_chunk=True):
        yield batcher.get_table()


def katana_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[KatanaResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = KATANA_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # Katana list endpoints always return newest-first by created_at and expose no sort override,
        # so rows arrive descending. The pipeline finalises the incremental watermark (max cursor) only
        # at the end for desc sources, which keeps it correct despite the fixed order.
        sort_mode="desc",
    )
