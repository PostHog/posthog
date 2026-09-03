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
from products.warehouse_sources.backend.temporal.data_imports.sources.decagon.settings import (
    DECAGON_ENDPOINTS,
    DecagonEndpointConfig,
)

DECAGON_BASE_URL = "https://api.decagon.ai"

REQUEST_TIMEOUT_SECONDS = 60

# Server-side page size of /conversation/export, per Decagon's docs.
DECAGON_PAGE_SIZE = 100

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

# Fallback window value for endpoints whose incremental bound is mandatory. Used when a
# walk has no natural window (a full refresh, or an incremental sync's first run), so it
# fetches full history instead of omitting the param the endpoint requires.
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


class DecagonRetryableError(Exception):
    pass


@dataclasses.dataclass
class DecagonResumeConfig:
    # Position of the next unfetched page, one field per pagination mode: the next-page
    # cursor ("cursor"), the next page number ("page"), or the next row offset ("offset").
    cursor: Optional[str] = None
    page: Optional[int] = None
    offset: Optional[int] = None
    # Rows already received across the walk ("page" mode). Counts what the server actually
    # returned rather than page * page_size, so termination against the reported total
    # stays exact even if the server caps the requested page size.
    rows_walked: Optional[int] = None
    # The incremental window the position belongs to, in the format the endpoint's
    # incremental_param takes (the field is named after the exports' param). A resumed
    # run must reissue exactly this alongside the position: the stored watermark can
    # advance while a walk is in flight, and recomputing the window would pair a fresh
    # lower bound with a position inside the old window. Optional so states saved before
    # these fields existed still parse.
    min_timestamp: Optional[int | str] = None
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
    """Coerce an incremental watermark to Unix epoch seconds.

    The watermark is stored from an ISO 8601 column, but the pipeline may hand it back as
    a datetime, a date, or an epoch number depending on how it round-tripped through
    storage. int() truncates any sub-second part, so the boundary second is re-fetched and
    a merge dedupes it on the primary key.
    """
    if isinstance(value, datetime):
        dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return int(dt.timestamp())
    if isinstance(value, date):
        return int(datetime.combine(value, datetime.min.time(), tzinfo=UTC).timestamp())
    return int(value)


def _incremental_window_value(config: DecagonEndpointConfig, value: Any) -> int | str:
    if config.incremental_param_format == "iso8601":
        return datetime.fromtimestamp(_to_epoch_seconds(value), UTC).isoformat()
    return _to_epoch_seconds(value)


def _next_cursor(data: dict[str, Any], cursor_keys: tuple[str, ...]) -> Optional[str]:
    # Skip falsy values rather than returning the first key present: a response that
    # carries `next_page_cursor: null` alongside a populated alias must keep paginating.
    for key in cursor_keys:
        value = data.get(key)
        if value:
            # Cursors can be integers (a last-updated epoch watermark in Decagon's example
            # response); requests and the saved resume state both want strings.
            return str(value)
    return None


def validate_credentials(api_key: str) -> bool:
    """Probe the conversations export (the cheapest authenticated read) to confirm the key works."""
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

    cursor: Optional[str] = None
    page = 1
    offset = 0
    rows_walked = 0
    window_value: Optional[int | str] = None
    timestamp_filter: Optional[str] = None

    if resume_config:
        cursor = resume_config.cursor
        page = resume_config.page if resume_config.page is not None else 1
        offset = resume_config.offset if resume_config.offset is not None else 0
        rows_walked = resume_config.rows_walked if resume_config.rows_walked is not None else 0
        # Resume the walk exactly where it stopped: same window, same position. See the
        # DecagonResumeConfig field comments for why the window is not recomputed here.
        window_value = resume_config.min_timestamp
        timestamp_filter = resume_config.timestamp_filter
        logger.debug(f"Decagon: resuming {endpoint} from saved state")
    elif (
        should_use_incremental_field
        and db_incremental_field_last_value is not None
        and incremental_field
        and config.incremental_param
    ):
        if config.timestamp_filter_param:
            filter_name = TIMESTAMP_FILTER_BY_FIELD.get(incremental_field)
            if filter_name:
                window_value = _incremental_window_value(config, db_incremental_field_last_value)
                timestamp_filter = filter_name
            else:
                logger.warning(
                    f"Decagon: incremental field {incremental_field} has no server-side timestamp "
                    f"filter; walking the full export instead"
                )
        else:
            window_value = _incremental_window_value(config, db_incremental_field_last_value)
            if config.primary_keys is None and isinstance(window_value, int):
                # Keyless streams append without a merge to dedupe re-fetched rows, so an
                # inclusive bound would re-import the watermark second on every sync and
                # inflate counts indefinitely. Advance past it instead: an event landing in
                # that same second after the walk read it is the rarer failure, and a full
                # refresh trues the table up.
                window_value += 1

    if window_value is None and config.incremental_param and config.incremental_param_required:
        # No prior state and no watermark left the window unset, but this endpoint 400s
        # on a request that omits the bound entirely. The epoch keeps a full walk honest
        # (every row is included) while still satisfying the requirement.
        window_value = _incremental_window_value(config, _EPOCH)

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

    def save_position(**position: Any) -> None:
        # Persisted only after a yield, so a crash re-yields the last batch rather than
        # skipping it (the duplicate rows a resumed re-yield can produce are bounded to
        # one page, and are cleaned up by the next full refresh or merged away on the
        # primary key).
        resumable_source_manager.save_state(
            DecagonResumeConfig(min_timestamp=window_value, timestamp_filter=timestamp_filter, **position)
        )

    # A row can re-enter the stream on a later page of one walk (a conversation that
    # receives new messages re-enters the export). Full-refresh writes are plain appends
    # (no primary-key merge), so re-emissions are skipped client-side; the next sync picks
    # up the newer version. Incremental writes merge on the primary key and the writer
    # keeps the last occurrence per key within a batch, so there the re-emission must flow
    # through (dropping it would keep the stale version) and the set, which grows
    # unboundedly across a large export, is not needed. Keyless streams have nothing to
    # dedupe on and always flow through.
    seen_keys: Optional[set[tuple[Any, ...]]] = (
        set() if config.primary_keys is not None and not should_use_incremental_field else None
    )

    while True:
        params: dict[str, str] = dict(config.extra_params)
        if config.pagination == "cursor":
            # An omitted cursor starts the stream at the oldest rows.
            if cursor:
                params["cursor"] = cursor
        elif config.pagination == "page":
            params["page"] = str(page)
            if config.page_size is not None:
                params["page_size"] = str(config.page_size)
        elif config.pagination == "offset":
            params["offset"] = str(offset)
            if config.page_size is not None:
                params["limit"] = str(config.page_size)
        if window_value is not None and config.incremental_param:
            params[config.incremental_param] = str(window_value)
            if timestamp_filter and config.timestamp_filter_param:
                params[config.timestamp_filter_param] = timestamp_filter

        data = fetch_page(params)
        items = data.get(config.data_key) or []

        fresh: list[dict[str, Any]] = []
        for item in items:
            if config.primary_keys is not None:
                # Direct access on purpose: these fields are the primary key, so a row
                # missing one should fail the sync loudly rather than land in the
                # warehouse unkeyed and undeduplicatable.
                key = tuple(item[k] for k in config.primary_keys)
                if seen_keys is not None:
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)
            fresh.append(item)

        if config.pagination == "single":
            if fresh:
                yield fresh
            break

        if config.pagination == "cursor":
            next_cursor = _next_cursor(data, config.next_cursor_keys or ())
            more = data.get(config.has_more_key) if config.has_more_key else None

            if fresh:
                yield fresh
                if next_cursor and more is not False:
                    save_position(cursor=next_cursor)

            if config.has_more_key is not None and not more:
                break
            # The next-page cursor is null once the stream is exhausted. Also stop if the
            # server ever returns the cursor we just used, to guard against spinning on
            # one page forever.
            if not next_cursor or next_cursor == cursor:
                if config.has_more_key is None and not next_cursor and len(items) >= DECAGON_PAGE_SIZE:
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
            continue

        total = data.get(config.total_key) if config.total_key else None

        if config.pagination == "page":
            # Terminate against the reported total using rows actually kept: a row that
            # shifted pages mid-walk arrives twice but counts once toward the server's
            # unique total, so counting raw items could reach the total a page early and
            # drop the final page. Counting kept rows also stays exact if the server caps
            # the requested page size. A page that contributes nothing new cannot make
            # progress against the total, so it ends the walk rather than spinning on a
            # server that ignores the page param. A missing or malformed total falls back
            # to short-page termination, the only end signal left besides an empty page.
            rows_walked += len(fresh)
            if isinstance(total, int | float):
                exhausted = not fresh or rows_walked >= total
            else:
                exhausted = not items or (config.page_size is not None and len(items) < config.page_size)
            if fresh:
                yield fresh
                if not exhausted:
                    save_position(page=page + 1, rows_walked=rows_walked)
            if exhausted:
                break
            page += 1
            continue

        # Offset mode: advance by the rows actually received rather than by page_size, so
        # a server that caps `limit` below what we asked still walks every row. The offset
        # itself is the cumulative row count, so the total check needs no separate counter.
        next_offset = offset + len(items)
        if isinstance(total, int | float):
            exhausted = not items or next_offset >= total
        else:
            exhausted = not items or (config.page_size is not None and len(items) < config.page_size)
        if fresh:
            yield fresh
            if not exhausted:
                save_position(offset=next_offset)
        if exhausted:
            break
        offset = next_offset

    # Walked to completion, so drop any checkpoint: a retried attempt of this job would
    # otherwise resume at the final page and append its rows again.
    resumable_source_manager.clear_state()


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
    partitioned = config.partition_key is not None

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
        partition_count=1 if partitioned else None,
        partition_size=1 if partitioned else None,
        partition_mode="datetime" if partitioned else None,
        partition_format="month" if partitioned else None,
        partition_keys=[config.partition_key] if config.partition_key is not None else None,
        sort_mode=config.sort_mode,
        chunk_size=config.chunk_size,
        chunk_size_bytes=config.chunk_size_bytes,
    )
