import time
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.decagon.settings import DECAGON_ENDPOINTS

DECAGON_BASE_URL = "https://api.decagon.ai"

REQUEST_TIMEOUT_SECONDS = 60

# Server-side page size of /conversation/export, per Decagon's docs.
DECAGON_PAGE_SIZE = 100

# Decagon's export reference names the next-page response field three different ways:
# `next_page_cursor` in the parameter prose, `next_cursor` in the official example code,
# and `next_page_updated_after` in the example response. Production responses carry no
# usable `next_page_cursor` (reading only that name made the walk stop after one page),
# so accept every documented name. All of them feed the same `cursor` request param.
NEXT_CURSOR_KEYS = ("next_page_cursor", "next_cursor", "next_page_updated_after")

# Decagon enforces a hard limit of 1 request/second across all API endpoints and
# automatically IP-bans gross violators, so requests are spaced client-side rather
# than relying on 429 backoff alone.
MIN_SECONDS_BETWEEN_REQUESTS = 1.0

# Maps a conversation row column to the `timestamp_filter` enum value that makes the
# export's min_timestamp/max_timestamp params bound that column. The filter for the
# `last_message_at` column is named `last_message_time`; both spellings are the
# vendor's, not a typo.
TIMESTAMP_FILTER_BY_FIELD: dict[str, str] = {
    "created_at": "created_at",
    "updated_at": "updated_at",
    "last_message_at": "last_message_time",
}


class DecagonRetryableError(Exception):
    pass


@dataclasses.dataclass
class DecagonResumeConfig:
    # The next-page export cursor returned by Decagon (see NEXT_CURSOR_KEYS).
    cursor: str
    # The incremental window the cursor belongs to. A resumed run must reissue exactly
    # these params alongside the cursor: the stored watermark can advance while a walk
    # is in flight, and pairing a recomputed min_timestamp with a cursor positioned
    # inside the old window would skip rows at the window boundary. Optional so states
    # saved before these fields existed still parse.
    min_timestamp: Optional[int] = None
    timestamp_filter: Optional[str] = None


class RequestThrottle:
    """Spaces consecutive requests at least `min_interval` seconds apart."""

    def __init__(self, min_interval: float = MIN_SECONDS_BETWEEN_REQUESTS) -> None:
        self._min_interval = min_interval
        self._last_request_at: Optional[float] = None

    def wait(self) -> None:
        if self._last_request_at is not None:
            remaining = self._min_interval - (time.monotonic() - self._last_request_at)
            if remaining > 0:
                time.sleep(remaining)
        self._last_request_at = time.monotonic()


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }


def _to_epoch_seconds(value: Any) -> int:
    """Coerce an incremental watermark to Unix epoch seconds for the `min_timestamp` param.

    The watermark is stored from the ISO 8601 `updated_at` column, but the pipeline may hand
    it back as a datetime, a date, or an epoch number depending on how it round-tripped
    through storage. int() truncates any sub-second part, so the boundary second is
    re-fetched and the merge dedupes it on the primary key.
    """
    if isinstance(value, datetime):
        dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return int(dt.timestamp())
    if isinstance(value, date):
        return int(datetime.combine(value, datetime.min.time(), tzinfo=UTC).timestamp())
    return int(value)


def _next_cursor(data: dict[str, Any]) -> Optional[str]:
    # Skip falsy values rather than returning the first key present: a response that
    # carries `next_page_cursor: null` alongside a populated alias must keep paginating.
    for key in NEXT_CURSOR_KEYS:
        value = data.get(key)
        if value:
            # Cursors can be integers (a last-updated epoch watermark in Decagon's example
            # response); requests and the saved resume state both want strings.
            return str(value)
    return None


def validate_credentials(api_key: str) -> bool:
    """Probe the export endpoint (the only one this source calls) to confirm the key works."""
    try:
        response = make_tracked_session(redact_values=(api_key,)).get(
            f"{DECAGON_BASE_URL}/conversation/export",
            headers=_get_headers(api_key),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        return response.status_code == 200
    except Exception:
        return False


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[DecagonResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: Optional[str] = None,
) -> Iterator[list[dict[str, Any]]]:
    config = DECAGON_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)
    url = f"{DECAGON_BASE_URL}{config.path}"
    session = make_tracked_session(redact_values=(api_key,))
    throttle = RequestThrottle()

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    cursor: Optional[str] = resume_config.cursor if resume_config else None

    min_timestamp: Optional[int] = None
    timestamp_filter: Optional[str] = None
    if resume_config:
        # Resume the walk exactly where it stopped: same window, same cursor. See the
        # DecagonResumeConfig field comments for why the window is not recomputed here.
        min_timestamp = resume_config.min_timestamp
        timestamp_filter = resume_config.timestamp_filter
        logger.debug(f"Decagon: resuming {endpoint} from saved cursor")
    elif should_use_incremental_field and db_incremental_field_last_value is not None and incremental_field:
        filter_name = TIMESTAMP_FILTER_BY_FIELD.get(incremental_field)
        if filter_name:
            # min_timestamp takes epoch seconds (the vendor's own example is
            # `?min_timestamp=1782864000`). Whether the bound is inclusive is undocumented;
            # the truncation in _to_epoch_seconds re-fetches the boundary second either way,
            # and the merge dedupes it on the primary key.
            min_timestamp = _to_epoch_seconds(db_incremental_field_last_value)
            timestamp_filter = filter_name
        else:
            logger.warning(
                f"Decagon: incremental field {incremental_field} has no server-side timestamp "
                f"filter; walking the full export instead"
            )

    @retry(
        retry=retry_if_exception_type((DecagonRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(5),
        # The 1 rps limit means a 429 needs a generous backoff, not a quick retry.
        wait=wait_exponential_jitter(initial=2, max=60),
        reraise=True,
    )
    def fetch_page(params: dict[str, str]) -> dict[str, Any]:
        throttle.wait()
        response = session.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code == 429 or response.status_code >= 500:
            raise DecagonRetryableError(f"Decagon API error (retryable): status={response.status_code}, url={url}")

        if not response.ok:
            logger.error(f"Decagon API error: status={response.status_code}, body={response.text}, url={url}")
            response.raise_for_status()

        return response.json()

    # A conversation that receives new messages re-enters the export stream on a later
    # page, so a single walk can emit the same conversation twice. Full-refresh writes
    # are plain appends (no primary-key merge), so re-emissions are skipped client-side;
    # the next sync picks up the newer version. Incremental writes merge on the primary
    # key and the writer keeps the last occurrence per key within a batch, so there the
    # re-emission must flow through (dropping it would keep the stale version) and the
    # set, which grows unboundedly across a large export, is not needed.
    seen_ids: Optional[set[str]] = None if should_use_incremental_field else set()

    while True:
        # An omitted cursor starts the stream at the oldest conversations.
        params: dict[str, str] = {"cursor": cursor} if cursor else {}
        if min_timestamp is not None and timestamp_filter is not None:
            params["min_timestamp"] = str(min_timestamp)
            params["timestamp_filter"] = timestamp_filter
        data = fetch_page(params)

        items = data.get(config.data_key) or []
        next_cursor = _next_cursor(data)

        fresh: list[dict[str, Any]] = []
        for item in items:
            # Direct access on purpose: conversation_id is the primary key, so a row
            # without one should fail the sync loudly rather than land in the warehouse
            # unkeyed and undeduplicatable.
            item_id = item["conversation_id"]
            if seen_ids is not None:
                if item_id in seen_ids:
                    continue
                seen_ids.add(item_id)
            fresh.append(item)

        if fresh:
            yield fresh
            # Save state only after yielding, so a crash re-yields the last batch rather
            # than skipping it (the duplicate rows a resumed re-yield can produce are
            # bounded to one page, and are cleaned up by the next full refresh or merged
            # away on the primary key).
            if next_cursor:
                resumable_source_manager.save_state(
                    DecagonResumeConfig(
                        cursor=next_cursor,
                        min_timestamp=min_timestamp,
                        timestamp_filter=timestamp_filter,
                    )
                )

        # The next-page cursor is null once the stream is exhausted. Also stop if the
        # server ever returns the cursor we just used, to guard against spinning on
        # one page forever.
        if not next_cursor or next_cursor == cursor:
            if not next_cursor and len(items) >= DECAGON_PAGE_SIZE:
                # A full page that ends the walk is legitimate only when the total row
                # count happens to be a multiple of the page size; far more often it means
                # Decagon renamed the pagination field again and rows were truncated.
                logger.warning(
                    f"Decagon: {endpoint} stream ended on a full page of {len(items)} items without a "
                    f"next-page cursor (response keys: {sorted(data.keys())}). If the synced row count "
                    f"looks truncated, check the export pagination contract."
                )
            break

        cursor = next_cursor


def decagon_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[DecagonResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: Optional[str] = None,
) -> SourceResponse:
    config = DECAGON_ENDPOINTS[endpoint]

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
        partition_mode="datetime",
        partition_format="month",
        partition_keys=[config.partition_key],
        # The export walks oldest to newest (`order` defaults to asc), so the pipeline can
        # checkpoint the incremental watermark as batches arrive.
        sort_mode="asc",
    )
