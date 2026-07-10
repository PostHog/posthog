import json
import random
import dataclasses
from collections.abc import Iterator
from datetime import date, datetime
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import RetryCallState, retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.linode.settings import (
    LINODE_ENDPOINTS,
    LinodeEndpointConfig,
)

LINODE_BASE_URL = "https://api.linode.com/v4"

# Max allowed page_size is 500 (min 25). Using the max minimizes request count against the 200 req/min
# paginated-GET rate limit.
PAGE_SIZE = 500

# Cap on how long we honor a rate-limit Retry-After before retrying, so a misreported header can't
# stall a worker indefinitely. The source iterator runs in a thread pool while the activity heartbeat
# fires from the event loop, so a 60s wait here does not trip the heartbeat timeout.
MAX_RETRY_AFTER_SECONDS = 60.0


class LinodeRetryableError(Exception):
    """Raised for 429/5xx responses so the tenacity layer retries. Carries the server's Retry-After
    (seconds) when present so we can wait exactly as long as Linode asks."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


def _get_headers(api_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_token}",
        "Accept": "application/json",
    }


def _format_filter_value(value: Any) -> Any:
    """Format an incremental cursor value for a Linode X-Filter comparison.

    Integer cursors (event id) pass through unchanged. Datetime/date cursors are rendered as the
    `YYYY-MM-DDTHH:MM:SS` form Linode uses for its own timestamp fields (no timezone offset)."""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%dT%H:%M:%S")
    return value


def _build_x_filter(field: str, value: Any) -> dict[str, Any]:
    """Build the JSON X-Filter body. Always orders ascending on the cursor field so pages arrive in
    the order SourceResponse.sort_mode ("asc") promises; adds a `+gte` bound when a watermark exists.

    The header is sent identically on every page request, so the server applies the filter and order
    to the full result set — pagination naturally terminates at the watermark, no client-side stop
    needed (unlike APIs that only window the first page)."""
    x_filter: dict[str, Any] = {"+order_by": field, "+order": "asc"}
    if value is not None:
        x_filter[field] = {"+gte": _format_filter_value(value)}
    return x_filter


@dataclasses.dataclass
class LinodeResumeConfig:
    # Next page (1-indexed) to fetch. The X-Filter header (built from the run's fixed watermark) and
    # page_size are constant across a run, so the page number alone is enough to resume.
    next_page: int


def _page_url(path: str, page: int) -> str:
    return f"{LINODE_BASE_URL}{path}?{urlencode({'page': page, 'page_size': PAGE_SIZE})}"


def validate_credentials(api_token: str) -> tuple[bool, str | None]:
    """Confirm the token is genuine by hitting /profile, which any valid token can read regardless of
    its granted scopes — so a token that only has scopes for some endpoints still validates."""
    try:
        response = make_tracked_session().get(f"{LINODE_BASE_URL}/profile", headers=_get_headers(api_token), timeout=10)
    except requests.exceptions.RequestException as e:
        return False, str(e)

    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return False, "Invalid Linode API token"
    return False, f"Linode API returned {response.status_code}: {response.text}"


_backoff_wait = wait_exponential_jitter(initial=1, max=30)


def _retry_wait(state: RetryCallState) -> float:
    """Honor Linode's Retry-After on a rate limit (capped, plus jitter), else exponential backoff."""
    if state.outcome is not None and state.outcome.failed:
        exc = state.outcome.exception()
        if isinstance(exc, LinodeRetryableError) and exc.retry_after is not None:
            return min(float(exc.retry_after), MAX_RETRY_AFTER_SECONDS) + random.uniform(0, 1)
    return _backoff_wait(state)


@retry(
    retry=retry_if_exception_type(
        (
            LinodeRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            # A mid-stream connection break on a chunked body; transient like ConnectionError but not a
            # subclass of it, so it needs its own entry.
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=_retry_wait,
    reraise=True,
)
def _fetch_page(session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger) -> dict:
    response = session.get(url, headers=headers, timeout=60)

    if response.status_code == 429 or response.status_code >= 500:
        retry_after = response.headers.get("Retry-After")
        raise LinodeRetryableError(
            f"Linode API error (retryable): status={response.status_code}, url={url}",
            retry_after=float(retry_after) if retry_after and retry_after.isdigit() else None,
        )

    if not response.ok:
        logger.error(f"Linode API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def get_rows(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[LinodeResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[Any]:
    config = LINODE_ENDPOINTS[endpoint]
    headers = _get_headers(api_token)

    # Attach the X-Filter header for incremental/append endpoints. Honor the user's chosen cursor
    # field, falling back to the endpoint's declared filterable field. On the first sync the watermark
    # is None, so we send only the ordering (no +gte bound) and pull the full available window.
    if config.incremental_field is not None and should_use_incremental_field:
        cursor_field = incremental_field or config.incremental_field
        headers["X-Filter"] = json.dumps(_build_x_filter(cursor_field, db_incremental_field_last_value))

    batcher = Batcher(logger=logger, chunk_size=2000, chunk_size_bytes=100 * 1024 * 1024)
    session = make_tracked_session()

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page = resume.next_page if resume is not None else 1
    if resume is not None:
        logger.debug(f"Linode: resuming {endpoint} from page {page}")

    while True:
        data = _fetch_page(session, _page_url(config.path, page), headers, logger)
        items = data.get("data") or []
        total_pages = data.get("pages") or 1

        for item in items:
            batcher.batch(item)
            if batcher.should_yield():
                yield batcher.get_table()
                # Save AFTER yielding so a crash re-fetches from the next page rather than re-yielding
                # already-committed rows (events are append-only and would duplicate otherwise). Only
                # persist while pages remain.
                if page < total_pages:
                    resumable_source_manager.save_state(LinodeResumeConfig(next_page=page + 1))

        if page >= total_pages:
            break
        page += 1

    if batcher.should_yield(include_incomplete_chunk=True):
        yield batcher.get_table()


def linode_source(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[LinodeResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    endpoint_config: LinodeEndpointConfig = LINODE_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_token=api_token,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        ),
        primary_keys=endpoint_config.primary_keys,
        # The X-Filter header orders results ascending on the cursor field, so rows arrive oldest-first
        # and the watermark advances safely after each batch.
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )
