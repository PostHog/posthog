import time
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import quote

import requests
from dateutil import parser as date_parser
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import (
    DEFAULT_RETRY,
    make_tracked_session,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.transistor.settings import (
    ANALYTICS_MAX_BACKFILL_DAYS,
    ANALYTICS_WINDOW_DAYS,
    MAX_SHOWS,
    MIN_REQUEST_INTERVAL_SECONDS,
    PAGE_SIZE,
    TRANSISTOR_BASE_URL,
    TRANSISTOR_ENDPOINTS,
    TransistorEndpointConfig,
)

REQUEST_TIMEOUT_SECONDS = 30

# Rows are yielded in bounded chunks so a show with a long download history never forces one
# oversized in-memory Arrow conversion downstream.
MAX_ROWS_PER_BATCH = 5000

# Transistor blocks for a full 10 seconds after a 429, which the transport's default backoff
# (0.5s factor over 3 attempts) can't wait out. Everything else stays as the shared default.
_TRANSISTOR_RETRY = DEFAULT_RETRY.new(total=5, backoff_factor=5)

# The documented parameter format is dd-mm-yyyy. The published response samples are
# inconsistent (some show mm-dd-yyyy), so download dates are parsed through an ordered ladder
# and the untouched value is kept alongside as `raw_date`.
_DOWNLOAD_DATE_FORMATS = ("%d-%m-%Y", "%Y-%m-%d", "%m-%d-%Y")


@dataclasses.dataclass
class TransistorResumeConfig:
    # Index into the show list (sorted by show id) of the next show still to fetch. Always 0
    # for `shows`, which is the parent list itself.
    show_index: int = 0
    # Next page to request within the current show's list endpoint. `None` starts at the API's
    # first page.
    page: Optional[int] = None
    # Analytics only: start of the next date window (ISO `YYYY-MM-DD`) for the current show.
    window_start: Optional[str] = None


class RequestThrottle:
    """Paces outbound requests to stay under Transistor's 10 requests / 10 seconds limit."""

    def __init__(self, min_interval_seconds: float) -> None:
        self._min_interval = min_interval_seconds
        self._last: float | None = None

    def wait(self) -> None:
        if self._last is not None:
            remaining = self._min_interval - (time.monotonic() - self._last)
            if remaining > 0:
                time.sleep(remaining)
        self._last = time.monotonic()


def _make_session(api_key: str) -> requests.Session:
    # `redact_values` masks the key wherever the tracked transport logs it; `capture=False`
    # because subscriber rows carry customer email addresses.
    return make_tracked_session(
        headers={"x-api-key": api_key, "Accept": "application/json"},
        redact_values=(api_key,),
        capture=False,
        retry=_TRANSISTOR_RETRY,
    )


def flatten_resource(item: dict[str, Any]) -> dict[str, Any]:
    """Flatten one JSON:API resource object into a warehouse row.

    `attributes` are hoisted to the row root, the resource `id`/`type` are set from the
    envelope (they win over any same-named attribute), and each relationship contributes a
    `<name>_id` (or `<name>_ids`) column so joins don't need the nested document.
    """
    attributes = item.get("attributes")
    row: dict[str, Any] = dict(attributes) if isinstance(attributes, dict) else {}
    row["id"] = item.get("id")
    row["type"] = item.get("type")

    relationships = item.get("relationships")
    if isinstance(relationships, dict):
        for name, relationship in relationships.items():
            if not isinstance(relationship, dict):
                continue
            data = relationship.get("data")
            if isinstance(data, dict):
                row[f"{name}_id"] = data.get("id")
            elif isinstance(data, list):
                row[f"{name}_ids"] = [entry.get("id") for entry in data if isinstance(entry, dict)]
    return row


def _fetch_json(
    session: requests.Session,
    throttle: RequestThrottle,
    url: str,
    params: dict[str, Any],
    logger: FilteringBoundLogger,
) -> dict[str, Any]:
    throttle.wait()
    response = session.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)

    # A show can be deleted mid-sync, and subscriber/webhook lookups 404 for shows that don't
    # have them; skipping the show beats failing the whole sync.
    if response.status_code == 404:
        logger.warning(f"Transistor: {url} returned 404, skipping")
        return {}

    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, dict) else {}


def paginate(
    session: requests.Session,
    throttle: RequestThrottle,
    url: str,
    params: dict[str, Any],
    logger: FilteringBoundLogger,
    start_page: int | None = None,
) -> Iterator[tuple[list[dict[str, Any]], int | None]]:
    """Walk a JSON:API list endpoint, yielding `(rows, next_page)` per page.

    The first request omits `pagination[page]` so the API's own base page applies (the docs
    say 0, responses report `currentPage` starting at 1), and every following page is derived
    from the response's `meta` block rather than from an assumed base.
    """
    page = start_page

    while True:
        request_params = {**params, "pagination[per]": PAGE_SIZE}
        if page is not None:
            request_params["pagination[page]"] = page

        payload = _fetch_json(session, throttle, url, request_params, logger)
        items = payload.get("data")
        rows = [flatten_resource(item) for item in items if isinstance(item, dict)] if isinstance(items, list) else []

        meta = payload.get("meta")
        current_page = meta.get("currentPage") if isinstance(meta, dict) else None
        total_pages = meta.get("totalPages") if isinstance(meta, dict) else None

        next_page: int | None = None
        if isinstance(current_page, int) and isinstance(total_pages, int):
            if current_page < total_pages:
                next_page = current_page + 1
        elif len(rows) >= PAGE_SIZE:
            # No pagination metadata (the webhooks list has none): keep walking only while
            # pages come back full.
            next_page = (page or 1) + 1

        yield rows, next_page

        if next_page is None:
            return
        page = next_page


def list_shows(
    session: requests.Session, throttle: RequestThrottle, logger: FilteringBoundLogger
) -> list[dict[str, Any]]:
    """Every show on the account, ordered by show id.

    The endpoint orders by updated date, which reshuffles whenever a show is edited. Fan-out
    resume state is an index into this list, so it is re-sorted into a stable order first.
    """
    shows: list[dict[str, Any]] = []
    for rows, _ in paginate(session, throttle, f"{TRANSISTOR_BASE_URL}/shows", {}, logger):
        shows.extend(rows)
        if len(shows) >= MAX_SHOWS:
            logger.warning(f"Transistor: show list capped at {MAX_SHOWS}; later shows are not synced")
            shows = shows[:MAX_SHOWS]
            break
    return sorted(shows, key=lambda show: str(show.get("id") or ""))


def format_api_date(value: date) -> str:
    """Format a date the way the analytics endpoints document their filters: dd-mm-yyyy."""
    return value.strftime("%d-%m-%Y")


def parse_download_date(raw: Any) -> date | None:
    if not isinstance(raw, str):
        return None
    for date_format in _DOWNLOAD_DATE_FORMATS:
        try:
            return datetime.strptime(raw.strip(), date_format).date()
        except ValueError:
            continue
    return None


def _coerce_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date_parser.parse(value).date()
        except (ValueError, OverflowError):
            return None
    return None


def date_windows(start: date, end: date, window_days: int = ANALYTICS_WINDOW_DAYS) -> Iterator[tuple[date, date]]:
    cursor = start
    while cursor <= end:
        window_end = min(cursor + timedelta(days=window_days - 1), end)
        yield cursor, window_end
        cursor = window_end + timedelta(days=1)


def _analytics_start_date(
    show: dict[str, Any],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    today: date,
) -> date:
    floor = today - timedelta(days=ANALYTICS_MAX_BACKFILL_DAYS)
    if should_use_incremental_field:
        watermark = _coerce_date(db_incremental_field_last_value)
        if watermark is not None:
            return max(watermark, floor)
    # A first sync reaches back to the show's own creation date, which is both the earliest
    # date that can have downloads and a natural bound on the backfill.
    created_at = _coerce_date(show.get("created_at"))
    return max(created_at, floor) if created_at is not None else floor


def _download_rows(show_id: str, extra: dict[str, Any], downloads: Any) -> Iterator[dict[str, Any]]:
    if not isinstance(downloads, list):
        return
    for entry in downloads:
        if not isinstance(entry, dict):
            continue
        parsed = parse_download_date(entry.get("date"))
        if parsed is None:
            continue
        yield {
            "show_id": show_id,
            **extra,
            "date": parsed.isoformat(),
            "raw_date": entry.get("date"),
            "downloads": entry.get("downloads"),
        }


def show_analytics_rows(show_id: str, payload: dict[str, Any]) -> Iterator[dict[str, Any]]:
    attributes = (payload.get("data") or {}).get("attributes") or {}
    yield from _download_rows(show_id, {}, attributes.get("downloads"))


def episode_analytics_rows(show_id: str, payload: dict[str, Any]) -> Iterator[dict[str, Any]]:
    attributes = (payload.get("data") or {}).get("attributes") or {}
    episodes = attributes.get("episodes")
    if not isinstance(episodes, list):
        return
    for episode in episodes:
        if not isinstance(episode, dict):
            continue
        episode_id = episode.get("id")
        if episode_id is None:
            continue
        extra = {
            "episode_id": str(episode_id),
            "episode_title": episode.get("title"),
            "episode_published_at": episode.get("published_at"),
        }
        yield from _download_rows(show_id, extra, episode.get("downloads"))


def _chunked(rows: Iterator[dict[str, Any]]) -> Iterator[list[dict[str, Any]]]:
    chunk: list[dict[str, Any]] = []
    for row in rows:
        chunk.append(row)
        if len(chunk) >= MAX_ROWS_PER_BATCH:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


def _list_request(endpoint: str, show_id: str) -> tuple[str, dict[str, Any]]:
    if endpoint == "episodes":
        # `order=asc` pins the walk to oldest-first by published date so a new episode
        # published mid-sync is appended rather than shifting every later page.
        return f"{TRANSISTOR_BASE_URL}/episodes", {"show_id": show_id, "order": "asc"}
    if endpoint == "subscribers":
        return f"{TRANSISTOR_BASE_URL}/subscribers", {"show_id": show_id}
    return f"{TRANSISTOR_BASE_URL}/webhooks", {"show_id": show_id}


def _analytics_request(endpoint: str, show_id: str, window_start: date, window_end: date) -> tuple[str, dict[str, Any]]:
    safe_show_id = quote(show_id, safe="")
    path = (
        f"{TRANSISTOR_BASE_URL}/analytics/{safe_show_id}"
        if endpoint == "show_analytics"
        else f"{TRANSISTOR_BASE_URL}/analytics/{safe_show_id}/episodes"
    )
    return path, {"start_date": format_api_date(window_start), "end_date": format_api_date(window_end)}


def get_rows(
    endpoint: str,
    api_key: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[TransistorResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    # One session reused across every request so urllib3 keeps the connection alive.
    session = _make_session(api_key)
    throttle = RequestThrottle(MIN_REQUEST_INTERVAL_SECONDS)
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    if endpoint == "shows":
        start_page = resume.page if resume is not None else None
        if start_page is not None:
            logger.debug(f"Transistor: resuming shows from page {start_page}")
        for rows, next_page in paginate(session, throttle, f"{TRANSISTOR_BASE_URL}/shows", {}, logger, start_page):
            if rows:
                yield rows
            # Saved after yielding so a crash re-yields the last page rather than skipping it —
            # merge dedupes on the primary key.
            if next_page is not None:
                resumable_source_manager.save_state(TransistorResumeConfig(page=next_page))
        return

    shows = list_shows(session, throttle, logger)
    start_index = resume.show_index if resume is not None else 0
    if start_index:
        logger.debug(f"Transistor: resuming {endpoint} from show index {start_index}")

    today = datetime.now(UTC).date()

    for index in range(start_index, len(shows)):
        show = shows[index]
        show_id = show.get("id")
        if show_id is None:
            continue
        show_id = str(show_id)
        # Resume hints only apply to the show the previous attempt stopped on.
        resume_for_show = resume if resume is not None and index == start_index else None

        if endpoint in ("show_analytics", "episode_analytics"):
            window_start = _coerce_date(resume_for_show.window_start) if resume_for_show is not None else None
            if window_start is None:
                window_start = _analytics_start_date(
                    show, should_use_incremental_field, db_incremental_field_last_value, today
                )

            windows = list(date_windows(window_start, today))
            if not windows:
                # Nothing left for this show (a watermark already at or past today), so move the
                # checkpoint on rather than leaving a resume stuck here.
                resumable_source_manager.save_state(TransistorResumeConfig(show_index=index + 1))
                continue

            for start, end in windows:
                url, params = _analytics_request(endpoint, show_id, start, end)
                payload = _fetch_json(session, throttle, url, params, logger)
                analytics_rows = (
                    show_analytics_rows(show_id, payload)
                    if endpoint == "show_analytics"
                    else episode_analytics_rows(show_id, payload)
                )
                yield from _chunked(analytics_rows)

                next_window_start = end + timedelta(days=1)
                if next_window_start <= today:
                    resumable_source_manager.save_state(
                        TransistorResumeConfig(show_index=index, window_start=next_window_start.isoformat())
                    )
                else:
                    resumable_source_manager.save_state(TransistorResumeConfig(show_index=index + 1))
            continue

        url, params = _list_request(endpoint, show_id)
        start_page = resume_for_show.page if resume_for_show is not None else None
        for rows, next_page in paginate(session, throttle, url, params, logger, start_page):
            if rows:
                yield [{**row, "show_id": show_id} for row in rows]
            if next_page is not None:
                resumable_source_manager.save_state(TransistorResumeConfig(show_index=index, page=next_page))
            else:
                resumable_source_manager.save_state(TransistorResumeConfig(show_index=index + 1))


def transistor_source(
    endpoint: str,
    api_key: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[TransistorResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config: TransistorEndpointConfig = TRANSISTOR_ENDPOINTS[endpoint]

    partition_kwargs: dict[str, Any] = {}
    if config.partition_key is not None:
        partition_kwargs = {
            "partition_count": 1,
            "partition_size": 1,
            "partition_mode": "datetime",
            "partition_format": "month",
            "partition_keys": [config.partition_key],
        }

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            endpoint=endpoint,
            api_key=api_key,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        # Every stream but `shows` is fetched show by show, so dates restart at each show and
        # the stream as a whole is not ascending. "desc" holds the incremental watermark back
        # until the sync completes, which is the safe reading for a non-monotonic stream;
        # mid-run progress is protected by the resumable state instead.
        sort_mode="desc",
        **partition_kwargs,
    )


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    """One cheap probe of the account root, which returns the authenticated user."""
    if not api_key or not api_key.strip():
        return False, "An API key is required."

    session = _make_session(api_key)
    try:
        response = session.get(TRANSISTOR_BASE_URL, timeout=REQUEST_TIMEOUT_SECONDS)
    except Exception:
        return False, "Could not reach the Transistor API. Please try again."

    if response.ok:
        return True, None

    if response.status_code in (401, 403):
        return False, (
            "Transistor rejected the API key. Generate a key under your Transistor account settings and reconnect."
        )
    return False, f"Transistor API returned an unexpected status code: {response.status_code}"
