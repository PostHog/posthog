from collections.abc import Iterable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.sources.easypost.settings import EASYPOST_ENDPOINTS
from products.warehouse_sources.sources.sdk import (
    ResumableSourceManager,
    SourceResponse,
    frozen,
    make_tracked_session,
    retry_with_deadline,
)

EASYPOST_BASE_URL = "https://api.easypost.com/v2"
# EasyPost caps page_size at 100 across cursor-paginated list endpoints.
PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 60
# Lower bound for runs with no watermark. It is earlier than any EasyPost account.
EARLIEST_START_DATETIME = datetime(2010, 1, 1, tzinfo=UTC)
# EasyPost list requests span at most 31 days (https://support.easypost.com/hc/en-us/articles/360043967372).
DATE_WINDOW = timedelta(days=30)


class EasypostRetryableError(Exception):
    pass


@frozen
class EasypostResumeConfig:
    # `before_id` of the page we last yielded. EasyPost paginates newest-first, so advancing the
    # cursor means asking for records created *before* this id. `None` resumes from the first page.
    before_id: str | None = None
    # Same, for endpoints that page oldest-first via `after_id`.
    after_id: str | None = None
    # Path value (e.g. report type) the cursor belongs to, for endpoints walked once per value.
    path_value: str | None = None
    # Window the cursor belongs to. A resumed run cannot recompute it from a new `now`.
    window_end: str | None = None


def _ensure_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _parse_datetime(value: Any) -> datetime | None:
    """Parse an EasyPost ISO-8601 timestamp (e.g. ``2024-01-15T10:30:00Z``) to an aware UTC datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return _ensure_utc(value)
    if isinstance(value, str):
        try:
            return _ensure_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
        except ValueError:
            return None
    return None


def _format_datetime(value: datetime) -> str:
    """Format a datetime for EasyPost's ``start_datetime`` filter (ISO-8601, UTC, ``Z`` suffix)."""
    return _ensure_utc(value).strftime("%Y-%m-%dT%H:%M:%SZ")


@retry_with_deadline(
    retry=retry_if_exception_type((EasypostRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(session: requests.Session, url: str, params: dict[str, Any], logger: FilteringBoundLogger) -> Any:
    response = session.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429 or response.status_code >= 500:
        raise EasypostRetryableError(f"EasyPost API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"EasyPost API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def validate_credentials(api_key: str) -> bool:
    """Probe a cheap list endpoint. EasyPost API keys carry full account access (no per-endpoint
    scopes), so a 200 means the key is genuine and active; anything else (401 invalid, 403 inactive)
    is a credential failure."""
    session = make_tracked_session(redact_values=(api_key,))
    session.auth = (api_key, "")
    try:
        response = session.get(
            f"{EASYPOST_BASE_URL}/shipments", params={"page_size": 1}, timeout=REQUEST_TIMEOUT_SECONDS
        )
        return response.status_code == 200
    except Exception:
        return False


def _strip_fields(value: Any, redacted_fields: tuple[str, ...]) -> Any:
    # Recurse so a nested object (a child user's own `children`) cannot carry the field through.
    if isinstance(value, dict):
        return {k: _strip_fields(v, redacted_fields) for k, v in value.items() if k not in redacted_fields}
    if isinstance(value, list):
        return [_strip_fields(v, redacted_fields) for v in value]
    return value


def _redact(items: list[dict[str, Any]], redacted_fields: tuple[str, ...]) -> list[dict[str, Any]]:
    if not redacted_fields:
        return items
    return _strip_fields(items, redacted_fields)


@frozen
class _DateWindow:
    # Rows in (start, end] belong to the window, so a boundary record lands in exactly one window.
    # A side set to None has no bound.
    start: datetime | None
    end: datetime | None

    def request_params(self) -> dict[str, str]:
        if self.start is None or self.end is None:
            return {}
        return {
            "start_datetime": _format_datetime(self.start),
            # Padded so a record at `end` comes back whether EasyPost treats the bound as inclusive or not.
            "end_datetime": _format_datetime(self.end + timedelta(seconds=1)),
        }

    def is_after_end(self, created: datetime | None) -> bool:
        return created is not None and self.end is not None and created > self.end

    def is_at_or_before_start(self, created: datetime | None) -> bool:
        return created is not None and self.start is not None and created <= self.start


def _date_windows(upper: datetime, lower: datetime) -> Iterator[_DateWindow]:
    window_end = upper
    while window_end > lower:
        window_start = max(window_end - DATE_WINDOW, lower)
        yield _DateWindow(start=window_start, end=window_end)
        window_end = window_start


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[EasypostResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[list[dict[str, Any]]]:
    config = EASYPOST_ENDPOINTS[endpoint]
    incremental_field_name = incremental_field or "created_at"

    # The fields stripped from rows are secrets; keep the raw responses out of HTTP sample capture too.
    session = make_tracked_session(redact_values=(api_key,), capture=not config.redacted_fields)
    session.auth = (api_key, "")
    collection_key = config.response_key or config.name

    if not config.paginated:
        # Lookup endpoints answer with the whole collection in one response — no cursor and no
        # `has_more`, so there is nothing to resume from or to watermark against.
        data = _fetch_page(session, f"{EASYPOST_BASE_URL}{config.path}", {}, logger)
        collection = data if config.returns_bare_list else data.get(collection_key, [])
        if collection:
            yield _redact(collection, config.redacted_fields)
        return

    last_value_dt: datetime | None = None
    if should_use_incremental_field and db_incremental_field_last_value is not None:
        last_value_dt = _parse_datetime(db_incremental_field_last_value)

    path_values: tuple[str | None, ...] = config.path_values or (None,)
    cursor_param = "after_id" if config.ascending else "before_id"
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    start_index = 0
    cursor_id: str | None = None
    resume_window_end: datetime | None = None
    if resume and resume.path_value in path_values:
        start_index = path_values.index(resume.path_value)
        cursor_id = resume.after_id if config.ascending else resume.before_id
        resume_window_end = _parse_datetime(resume.window_end)
    if cursor_id:
        logger.debug(f"EasyPost: resuming {endpoint} from {cursor_param}={cursor_id}")

    run_end = datetime.now(UTC).replace(microsecond=0)

    for path_value in path_values[start_index:]:
        url = f"{EASYPOST_BASE_URL}{config.path.format(path_value) if path_value else config.path}"

        windows: Iterable[_DateWindow]
        if config.supports_start_datetime:
            windows = _date_windows(resume_window_end or run_end, last_value_dt or EARLIEST_START_DATETIME)
        else:
            windows = [_DateWindow(start=last_value_dt, end=None)]
        resume_window_end = None

        for window in windows:
            while True:
                params: dict[str, Any] = {"page_size": PAGE_SIZE, **window.request_params()}
                if cursor_id:
                    params[cursor_param] = cursor_id

                data = _fetch_page(session, url, params, logger)
                items = data.get(collection_key, [])
                if not items:
                    break

                has_more = bool(data.get("has_more", False))

                reached_window_start = False
                rows: list[dict[str, Any]] = []
                for item in items:
                    created = _parse_datetime(item.get(incremental_field_name))
                    if window.is_at_or_before_start(created):
                        reached_window_start = True
                        break
                    if not window.is_after_end(created):
                        rows.append(item)

                if rows:
                    yield _redact(rows, config.redacted_fields)
                    # Save the cursor for the page we just yielded (not the next one) so a crash re-fetches
                    # and re-yields this page — merge dedupes on the `id` primary key — rather than skipping it.
                    cursor_fields = {"after_id": cursor_id} if config.ascending else {"before_id": cursor_id}
                    resumable_source_manager.save_state(
                        EasypostResumeConfig(
                            **cursor_fields,
                            path_value=path_value,
                            window_end=_format_datetime(window.end) if window.end is not None else None,
                        )
                    )

                if reached_window_start or not has_more:
                    break

                cursor_id = items[-1]["id"]

            cursor_id = None
            if window.start is not None and window.end is not None:
                # Most old windows are empty, so mark each finished window as a point the run can stop at.
                resumable_source_manager.save_state(
                    EasypostResumeConfig(path_value=path_value, window_end=_format_datetime(window.start))
                )
                resumable_source_manager.safe_point()


def easypost_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[EasypostResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = EASYPOST_ENDPOINTS[endpoint]

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
        # EasyPost list endpoints return records newest-first (descending creation time), except
        # the ones that page forward with `after_id`.
        sort_mode="asc" if config.ascending else "desc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
