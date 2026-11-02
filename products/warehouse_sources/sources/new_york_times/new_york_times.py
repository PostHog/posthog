import math
import time
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import (
    make_tracked_session,
    retry_with_deadline,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.interruptible_wait import (
    interruptible_wait,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.new_york_times.settings import (
    NEW_YORK_TIMES_ENDPOINTS,
    NewYorkTimesEndpointConfig,
)

NEW_YORK_TIMES_BASE_URL = "https://api.nytimes.com"

# Article Search returns 10 results per page and hard-caps at 100 pages (1000 results) per query.
ARTICLE_SEARCH_PAGE_SIZE = 10
ARTICLE_SEARCH_MAX_PAGES = 100

# NYT rate limits are tight (≈10 requests/minute) and Article Search 429s aggressively. NYT explicitly
# recommends sleeping several seconds between calls, so we throttle paging politely and let the retry
# handler absorb any 429s that still slip through.
REQUEST_DELAY_SECONDS = 6.0

TIMES_WIRE_PAGE_SIZE = 20
# The feed is newest first, so a run that stops early would advance the watermark past unread items.
# This only guards against an API that never returns a short page: 30 days of items fit well inside it.
TIMES_WIRE_MAX_PAGES = 1000
# The {time-period} path segment accepts at most 30 days of hours.
TIMES_WIRE_MAX_TIME_PERIOD_HOURS = 720

BOOKS_LIST_NAMES_PATH = "/svc/books/v3/lists/names.json"
BOOKS_LIST_PAGE_SIZE = 20


class NewYorkTimesRetryableError(Exception):
    pass


class NewYorkTimesPageCapError(Exception):
    pass


@dataclasses.dataclass(frozen=False)
class NewYorkTimesResumeConfig:
    # Zero-based Article Search page index to fetch next. Snapshot endpoints never populate this.
    page: int = 0
    # The begin_date (YYYYMMDD) window this run is paging through. Persisted so a resume continues the
    # exact same window rather than recomputing `now - lookback`, which would drift over a long sync.
    # Times Newswire reuses `page` and stores its ISO window start here.
    begin_date: str | None = None
    # Archive: the next month to fetch, as YYYY-MM.
    month: str | None = None
    # Books best-seller lists: the list in progress and its next edition date. A None date means the list
    # is finished and the run continues with the next list name.
    list_name_encoded: str | None = None
    published_date: str | None = None


def _get_headers() -> dict[str, str]:
    return {"Accept": "application/json"}


def _format_begin_date(value: Any) -> str:
    """Format an incremental cursor value as the YYYYMMDD string Article Search's begin_date expects."""
    if isinstance(value, datetime):
        return value.astimezone(UTC).strftime("%Y%m%d") if value.tzinfo else value.strftime("%Y%m%d")
    if isinstance(value, date):
        return value.strftime("%Y%m%d")
    # A pre-formatted string cursor — trust it as-is.
    return str(value)


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime(value.year, value.month, value.day)
    else:
        parsed = datetime.fromisoformat(str(value))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _format_iso_date(value: Any) -> str:
    if isinstance(value, datetime | date):
        return value.strftime("%Y-%m-%d")
    return str(value)[:10]


def _resolve_begin_date(
    config: NewYorkTimesEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> str | None:
    """Pick the begin_date window for an Article Search run.

    Uses the incremental watermark when we have one, otherwise falls back to a recent lookback window so
    the first sync (and full refreshes) stay inside NYT's 1000-result cap instead of trying to page all
    of history back to 1851.
    """
    if should_use_incremental_field and db_incremental_field_last_value:
        return _format_begin_date(db_incremental_field_last_value)
    if config.default_lookback_days is not None:
        return (datetime.now(UTC) - timedelta(days=config.default_lookback_days)).strftime("%Y%m%d")
    return None


def _build_url(path: str, api_key: str, params: dict[str, Any]) -> str:
    query = {**params, "api-key": api_key}
    return f"{NEW_YORK_TIMES_BASE_URL}{path}?{urlencode(query)}"


def _sanitize_url(url: str) -> str:
    """Drop the query string so the api-key (passed as a query param) never lands in logs or errors."""
    return url.split("?", 1)[0]


@retry_with_deadline(
    retry=retry_if_exception_type(
        (
            NewYorkTimesRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=2, max=60),
    reraise=True,
)
def _fetch_page(
    session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> dict[str, Any]:
    response = session.get(url, headers=headers, timeout=60)

    if response.status_code == 429 or response.status_code >= 500:
        raise NewYorkTimesRetryableError(f"New York Times API error (retryable): status={response.status_code}")

    if not response.ok:
        # The api-key rides in the query string, so never surface the raw URL. Raise an HTTPError whose
        # message matches the non-retryable-error keys (status + base host) without leaking the key.
        safe_url = _sanitize_url(url)
        logger.error(f"New York Times API error: status={response.status_code}, url={safe_url}")
        raise requests.HTTPError(
            f"{response.status_code} Client Error: {response.reason} for url: {safe_url}", response=response
        )

    return response.json()


def validate_credentials(api_key: str) -> bool:
    # Probe a cheap endpoint. A 401 means the key itself is bad or missing; anything else — including a
    # 403 from an app that has this particular API disabled — means the key is genuine. Users may enable
    # only the APIs they intend to sync, so a 403 must not block source creation.
    url = _build_url("/svc/mostpopular/v2/viewed/1.json", api_key, {})
    try:
        response = make_tracked_session(redact_values=(api_key,)).get(url, headers=_get_headers(), timeout=10)
        return response.status_code != 401
    except Exception:
        return False


def _select_rows(config: NewYorkTimesEndpointConfig, data: dict[str, Any]) -> list[dict[str, Any]]:
    node: Any = data
    for key in config.data_selector.split("."):
        node = node.get(key) if isinstance(node, dict) else None
    return node or []


def _get_snapshot_rows(
    session: requests.Session,
    config: NewYorkTimesEndpointConfig,
    api_key: str,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    url = _build_url(config.path, api_key, {})
    data = _fetch_page(session, url, _get_headers(), logger)
    rows = _select_rows(config, data)
    if rows:
        yield rows


def _get_article_search_rows(
    session: requests.Session,
    config: NewYorkTimesEndpointConfig,
    api_key: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[NewYorkTimesResumeConfig],
    query: str | None,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    begin_date: str | None
    if resume is not None and resume.begin_date is not None:
        begin_date = resume.begin_date
        page = resume.page
        logger.debug(f"New York Times: resuming article_search from page={page}, begin_date={begin_date}")
    else:
        begin_date = _resolve_begin_date(config, should_use_incremental_field, db_incremental_field_last_value)
        page = 0

    while page < ARTICLE_SEARCH_MAX_PAGES:
        params: dict[str, Any] = {"page": page, "sort": "oldest"}
        if begin_date:
            params["begin_date"] = begin_date
        if query:
            params["q"] = query

        url = _build_url(config.path, api_key, params)
        data = _fetch_page(session, url, _get_headers(), logger)
        rows = _select_rows(config, data)

        if not rows:
            break

        yield rows

        page += 1
        # Save AFTER yielding so a crash re-yields the last page rather than skipping it — merge dedupes
        # on `_id`.
        resumable_source_manager.save_state(NewYorkTimesResumeConfig(page=page, begin_date=begin_date))

        if len(rows) < ARTICLE_SEARCH_PAGE_SIZE:
            break

        if page >= ARTICLE_SEARCH_MAX_PAGES:
            logger.info(
                "New York Times: article_search hit the 100-page (1000-result) cap; remaining results in "
                "this window will be picked up by the next incremental sync"
            )
            break

        time.sleep(REQUEST_DELAY_SECONDS)


def _resolve_archive_start(
    config: NewYorkTimesEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> date:
    if should_use_incremental_field and db_incremental_field_last_value:
        start = _parse_datetime(db_incremental_field_last_value)
    else:
        start = datetime.now(UTC) - timedelta(days=config.default_lookback_days or 0)
    return date(start.year, start.month, 1)


def _next_month(month: date) -> date:
    return date(month.year + 1, 1, 1) if month.month == 12 else date(month.year, month.month + 1, 1)


def _get_archive_rows(
    session: requests.Session,
    config: NewYorkTimesEndpointConfig,
    api_key: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[NewYorkTimesResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.month is not None:
        month = date.fromisoformat(f"{resume.month}-01")
        logger.debug(f"New York Times: resuming archive from month={resume.month}")
    else:
        month = _resolve_archive_start(config, should_use_incremental_field, db_incremental_field_last_value)

    now = datetime.now(UTC)
    current_month = date(now.year, now.month, 1)

    while month <= current_month:
        path = config.path.format(year=month.year, month=month.month)
        data = _fetch_page(session, _build_url(path, api_key, {}), _get_headers(), logger)
        rows = _select_rows(config, data)

        month = _next_month(month)
        resumable_source_manager.save_state(NewYorkTimesResumeConfig(month=month.strftime("%Y-%m")))
        if rows:
            yield rows
        else:
            resumable_source_manager.safe_point()

        if month <= current_month:
            interruptible_wait(REQUEST_DELAY_SECONDS, safe_point=resumable_source_manager.safe_point)


def _resolve_times_wire_start(
    config: NewYorkTimesEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> datetime:
    if should_use_incremental_field and db_incremental_field_last_value:
        return _parse_datetime(db_incremental_field_last_value)
    return datetime.now(UTC) - timedelta(days=config.default_lookback_days or 1)


def _times_wire_hours_since(window_start: datetime) -> int:
    return max(1, math.ceil((datetime.now(UTC) - window_start).total_seconds() / 3600))


def _get_times_wire_rows(
    session: requests.Session,
    config: NewYorkTimesEndpointConfig,
    api_key: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[NewYorkTimesResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.begin_date is not None:
        window_start = _parse_datetime(resume.begin_date)
        page = resume.page
        logger.debug(f"New York Times: resuming times_wire from page={page}, window_start={resume.begin_date}")
    else:
        window_start = _resolve_times_wire_start(config, should_use_incremental_field, db_incremental_field_last_value)
        page = 0

    if _times_wire_hours_since(window_start) > TIMES_WIRE_MAX_TIME_PERIOD_HOURS:
        logger.warning(
            "New York Times: times_wire can only look back 30 days; items published before that are not synced"
        )

    while True:
        if page >= TIMES_WIRE_MAX_PAGES:
            raise NewYorkTimesPageCapError(
                f"New York Times: times_wire reached {TIMES_WIRE_MAX_PAGES} pages without reaching the end of the window"
            )

        # Recomputed per request so the window start stays fixed while a long sync pages through it.
        time_period = min(_times_wire_hours_since(window_start), TIMES_WIRE_MAX_TIME_PERIOD_HOURS)
        path = config.path.format(time_period=time_period)
        params = {"limit": TIMES_WIRE_PAGE_SIZE, "offset": page * TIMES_WIRE_PAGE_SIZE}
        data = _fetch_page(session, _build_url(path, api_key, params), _get_headers(), logger)
        rows = _select_rows(config, data)

        if not rows:
            break

        page += 1
        resumable_source_manager.save_state(NewYorkTimesResumeConfig(page=page, begin_date=window_start.isoformat()))
        yield rows

        if len(rows) < TIMES_WIRE_PAGE_SIZE:
            break

        interruptible_wait(REQUEST_DELAY_SECONDS, safe_point=resumable_source_manager.safe_point)


def _get_best_seller_edition(
    session: requests.Session,
    config: NewYorkTimesEndpointConfig,
    api_key: str,
    logger: FilteringBoundLogger,
    list_name_encoded: str,
    published_date: str,
) -> tuple[list[dict[str, Any]], str | None]:
    """Fetch one list edition, flattening list metadata onto each book. Returns the rows and the previous edition date."""
    path = config.path.format(date=published_date, list=list_name_encoded)
    rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        data = _fetch_page(session, _build_url(path, api_key, {"offset": offset}), _get_headers(), logger)
        results = data.get("results") or {}
        books = results.get("books") or []
        list_fields = {
            "list_name": results.get("list_name"),
            "list_name_encoded": list_name_encoded,
            "display_name": results.get("display_name"),
            "published_date": results.get("published_date") or published_date,
            "bestsellers_date": results.get("bestsellers_date"),
            "updated": results.get("updated"),
        }
        rows.extend({**book, **list_fields} for book in books)

        if len(books) < BOOKS_LIST_PAGE_SIZE:
            return rows, results.get("previous_published_date") or None

        offset += BOOKS_LIST_PAGE_SIZE
        interruptible_wait(REQUEST_DELAY_SECONDS)


def _get_best_seller_rows(
    session: requests.Session,
    config: NewYorkTimesEndpointConfig,
    api_key: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[NewYorkTimesResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    # Lists for one date can publish at different times, so editions on the watermark date are fetched
    # again; merge dedupes them.
    watermark = (
        _format_iso_date(db_incremental_field_last_value)
        if should_use_incremental_field and db_incremental_field_last_value
        else None
    )

    names_data = _fetch_page(session, _build_url(BOOKS_LIST_NAMES_PATH, api_key, {}), _get_headers(), logger)
    lists = sorted(
        (
            entry
            for entry in names_data.get("results") or []
            if entry.get("list_name_encoded") and entry.get("newest_published_date")
        ),
        key=lambda entry: entry["list_name_encoded"],
    )
    if watermark is not None:
        lists = [entry for entry in lists if entry["newest_published_date"] >= watermark]

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    resume_list = resume.list_name_encoded if resume is not None else None

    for entry in lists:
        list_name_encoded: str = entry["list_name_encoded"]
        edition_date: str | None = entry["newest_published_date"]
        if resume is not None and resume_list is not None:
            if list_name_encoded < resume_list:
                continue
            if list_name_encoded == resume_list:
                if resume.published_date is None:
                    continue
                edition_date = resume.published_date

        while edition_date is not None:
            interruptible_wait(REQUEST_DELAY_SECONDS, safe_point=resumable_source_manager.safe_point)
            rows, previous_date = _get_best_seller_edition(
                session, config, api_key, logger, list_name_encoded, edition_date
            )

            # Without a watermark only the newest edition is synced; with one, walk back to cover editions
            # published since the last sync. Each step must move back in time, so the walk always ends.
            next_date = (
                previous_date
                if watermark is not None and previous_date and watermark <= previous_date < edition_date
                else None
            )

            resumable_source_manager.save_state(
                NewYorkTimesResumeConfig(list_name_encoded=list_name_encoded, published_date=next_date)
            )
            if rows:
                yield rows
            else:
                resumable_source_manager.safe_point()
            edition_date = next_date


_CUSTOM_ITERATORS = {
    "archive": _get_archive_rows,
    "times_wire": _get_times_wire_rows,
    "books_best_sellers": _get_best_seller_rows,
}


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[NewYorkTimesResumeConfig],
    query: str | None = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = NEW_YORK_TIMES_ENDPOINTS[endpoint]
    # Redact the api-key (carried as a query param) from the tracked transport's logged URLs.
    session = make_tracked_session(redact_values=(api_key,))

    if config.paginated:
        yield from _get_article_search_rows(
            session,
            config,
            api_key,
            logger,
            resumable_source_manager,
            query,
            should_use_incremental_field,
            db_incremental_field_last_value,
        )
    elif endpoint in _CUSTOM_ITERATORS:
        yield from _CUSTOM_ITERATORS[endpoint](
            session,
            config,
            api_key,
            logger,
            resumable_source_manager,
            should_use_incremental_field,
            db_incremental_field_last_value,
        )
    else:
        yield from _get_snapshot_rows(session, config, api_key, logger)


def new_york_times_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[NewYorkTimesResumeConfig],
    query: str | None = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> SourceResponse:
    config = NEW_YORK_TIMES_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            query=query,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode=config.sort_mode,
    )
