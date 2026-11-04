import json
import hashlib
from collections import Counter
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Any, Optional
from urllib.parse import quote, urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.sources.kernel.settings import (
    BROWSER_TELEMETRY_EVENTS,
    KERNEL_ENDPOINTS,
    SENSITIVE_FIELDS,
    TELEMETRY_DROPPED_DATA_FIELDS,
    TELEMETRY_RETENTION_DAYS,
    KernelEndpointConfig,
)
from products.warehouse_sources.sources.sdk import (
    ResumableSourceManager,
    SourceResponse,
    frozen,
    make_tracked_session,
    retry_with_deadline,
)

KERNEL_BASE_URL = "https://api.onkernel.com"

# Kernel caps list page size at 100 (1-100, default 20).
PAGE_SIZE = 100

AUDIT_LOGS_ENDPOINT = "audit_logs"
AUDIT_LOG_MAX_WINDOW = timedelta(days=28)
AUDIT_LOG_MIN_WINDOW = timedelta(hours=1)
AUDIT_LOG_RETENTION = timedelta(days=365)


@frozen
class KernelResumeConfig:
    # List endpoints: the offset of the next page.
    offset: int | None = None
    # audit_logs: the start of the next time window, as an ISO timestamp.
    audit_log_start: str | None = None
    # browser_telemetry_events: the browser session to read next, and the offset cursor of its next
    # page. Sessions are read in id order, and a None cursor starts the session at its first event.
    telemetry_session_id: str | None = None
    telemetry_cursor: int | None = None
    # List and telemetry endpoints: the last page is handed on, so a resume reads nothing again.
    completed: bool = False


class KernelRetryableError(Exception):
    pass


class KernelResourceDisabledError(Exception):
    pass


class KernelUnexpectedResponseError(Exception):
    """Raised when a list response is neither a JSON array nor a recognized wrapped shape.

    Every endpoint is a full refresh, so a body we can't parse must fail loudly: treating it
    as an empty page would let the sync "succeed" with zero rows and overwrite the existing
    warehouse table with nothing.
    """

    pass


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }


def _build_url(path: str, params: dict[str, Any]) -> str:
    query = urlencode(params)
    return f"{KERNEL_BASE_URL}{path}?{query}" if query else f"{KERNEL_BASE_URL}{path}"


def _extract_items(body: Any) -> list[dict[str, Any]]:
    """Pull the row list out of a Kernel list response.

    Kernel signals pagination through headers (X-Has-More / X-Next-Offset), so the body is
    expected to be a bare JSON array. We defensively also accept the common wrapped shapes
    ({"data": [...]} etc.) since this has not been verified against a live API. An empty array
    (or empty wrapped list) is a legitimate "no more rows" signal. Any other shape is
    unexpected, and we raise rather than return [] - a silent empty result would let a full
    refresh overwrite the table with zero rows.
    """
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        for key in ("data", "items", "results", "records"):
            value = body.get(key)
            if isinstance(value, list):
                return value
    raise KernelUnexpectedResponseError(f"Unexpected Kernel list response shape: {type(body).__name__}")


def _error_code(response: requests.Response) -> Optional[str]:
    try:
        body = response.json()
    except ValueError:
        return None
    code = body.get("code") if isinstance(body, dict) else None
    return code if isinstance(code, str) else None


def _parse_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _format_datetime(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _add_audit_log_ids(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Give each audit record a deterministic id, including duplicate copies."""
    seen: Counter[str] = Counter()
    for row in rows:
        if "id" in row:
            continue
        digest = hashlib.sha256(json.dumps(row, sort_keys=True, default=str).encode()).hexdigest()
        row["id"] = f"{digest}-{seen[digest]}"
        seen[digest] += 1
    return rows


def _redact_sensitive_fields(item: Any, nested_sensitive_fields: Optional[dict[str, frozenset[str]]] = None) -> Any:
    """Drop credential-bearing fields (see SENSITIVE_FIELDS) before a row is batched.

    Kernel objects are written to the warehouse verbatim, so env vars and token-bearing
    live-view / CDP URLs would otherwise be queryable by any project user. `item` is untyped
    JSON, so non-dict rows pass through untouched.
    """
    if not isinstance(item, dict):
        return item
    redacted = {key: value for key, value in item.items() if key.lower() not in SENSITIVE_FIELDS}
    for parent, keys in (nested_sensitive_fields or {}).items():
        nested = redacted.get(parent)
        if isinstance(nested, dict):
            redacted[parent] = {key: value for key, value in nested.items() if key.lower() not in keys}
    return redacted


def _next_page(headers: Any, current_offset: int, page_len: int) -> tuple[bool, int]:
    """Return (has_more, next_offset) from the response headers, falling back to offset math."""
    has_more_header = str(headers.get("X-Has-More", "")).strip().lower()
    if has_more_header in ("true", "false"):
        has_more = has_more_header == "true"
    else:
        # No header: assume more pages only while a full page came back.
        has_more = page_len >= PAGE_SIZE

    next_offset_header = headers.get("X-Next-Offset")
    if next_offset_header is not None:
        try:
            return has_more, int(next_offset_header)
        except (TypeError, ValueError):
            pass
    return has_more, current_offset + page_len


@retry_with_deadline(
    retry=retry_if_exception_type(
        (
            KernelRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    url: str,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    allow_not_found: bool = False,
    empty_on_error_code: Optional[str] = None,
) -> requests.Response:
    response = session.get(url, headers=headers, timeout=60)

    # Kernel returns 429 with a Retry-After per-organization rate limit; honor it via retry backoff.
    if response.status_code == 429 or response.status_code >= 500:
        raise KernelRetryableError(f"Kernel API error (retryable): status={response.status_code}, url={url}")

    if allow_not_found and response.status_code == 404:
        return response

    if empty_on_error_code is not None and response.status_code == 404 and _error_code(response) == empty_on_error_code:
        raise KernelResourceDisabledError(empty_on_error_code)

    if not response.ok:
        logger.error(f"Kernel API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response


def validate_credentials(api_key: str) -> tuple[bool, int | None]:
    """Probe a cheap list endpoint. Returns (ok, status_code); status is None on transport failure."""
    url = _build_url("/apps", {"limit": 1})
    try:
        # capture=False: Kernel responses carry secret-bearing fields (see SENSITIVE_FIELDS)
        # that the generic HTTP-sample scrubber does not know to redact.
        response = make_tracked_session(capture=False).get(url, headers=_get_headers(api_key), timeout=10)
    except Exception:
        return False, None
    return response.status_code == 200, response.status_code


def _fetch_audit_log_page(
    session: requests.Session,
    headers: dict[str, str],
    start: datetime,
    end: datetime,
    page_token: Optional[str],
    logger: FilteringBoundLogger,
) -> tuple[list[dict[str, Any]], Optional[str]]:
    params: dict[str, Any] = {"start": _format_datetime(start), "end": _format_datetime(end), "limit": PAGE_SIZE}
    if page_token:
        params["page_token"] = page_token
    response = _fetch_page(session, _build_url(KERNEL_ENDPOINTS[AUDIT_LOGS_ENDPOINT].path, params), headers, logger)
    items = _extract_items(response.json())
    has_more = str(response.headers.get("X-Has-More", "")).strip().lower()
    next_token = response.headers.get("X-Next-Page-Token")
    if has_more == "false" or not next_token:
        return items, None
    return items, str(next_token)


def _iter_audit_log_windows(
    session: requests.Session,
    headers: dict[str, str],
    start: datetime,
    end: datetime,
    logger: FilteringBoundLogger,
    manager: ResumableSourceManager[KernelResumeConfig],
) -> Iterator[tuple[datetime, list[dict[str, Any]]]]:
    """Yield the end of each window with its rows, oldest window first. A window with no rows is yielded too."""
    windows: list[tuple[datetime, datetime]] = []
    window_start = start
    while window_start < end:
        windows.append((window_start, min(window_start + AUDIT_LOG_MAX_WINDOW, end)))
        window_start += AUDIT_LOG_MAX_WINDOW
    pending = list(reversed(windows))
    while pending:
        window_start, window_end = pending.pop()
        rows, next_token = _fetch_audit_log_page(session, headers, window_start, window_end, None, logger)
        if next_token is not None and window_end - window_start > AUDIT_LOG_MIN_WINDOW:
            midpoint = window_start + (window_end - window_start) / 2
            pending.append((midpoint, window_end))
            pending.append((window_start, midpoint))
            # The rows of the window are dropped and read again in the halves, so none is held.
            manager.safe_point()
            continue
        while next_token is not None:
            page, next_token = _fetch_audit_log_page(session, headers, window_start, window_end, next_token, logger)
            rows.extend(page)
        rows.sort(key=lambda row: _parse_datetime(row.get("timestamp")) or datetime.min.replace(tzinfo=UTC))
        yield window_end, _add_audit_log_ids(rows)


def get_audit_log_rows(
    api_key: str,
    logger: FilteringBoundLogger,
    manager: ResumableSourceManager[KernelResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> Iterator[Any]:
    headers = _get_headers(api_key)
    session = make_tracked_session(capture=False)
    end = datetime.now(UTC)
    start = end - AUDIT_LOG_RETENTION
    last_value = _parse_datetime(db_incremental_field_last_value)
    if last_value is not None and last_value > start:
        start = last_value
    resume = manager.load_state() if manager.can_resume() else None
    resume_start = _parse_datetime(resume.audit_log_start) if resume is not None else None
    if resume_start is not None and resume_start > start:
        start = resume_start
    for window_end, rows in _iter_audit_log_windows(session, headers, start, end, logger, manager):
        manager.save_state(KernelResumeConfig(audit_log_start=_format_datetime(window_end)))
        if rows:
            # One item per window, so a window and the cursor past it commit together.
            yield rows
        else:
            manager.safe_point()


def _iter_list_pages(
    session: requests.Session,
    headers: dict[str, str],
    config: KernelEndpointConfig,
    logger: FilteringBoundLogger,
    offset: int = 0,
) -> Iterator[tuple[list[Any], int | None]]:
    """Yield each page with the offset of the page after it, or None after the last page."""
    while True:
        params: dict[str, Any] = {"limit": PAGE_SIZE, "offset": offset, **config.extra_params}
        url = _build_url(config.path, params)
        try:
            response = _fetch_page(session, url, headers, logger, empty_on_error_code=config.empty_on_error_code)
        except KernelResourceDisabledError:
            return
        items = _extract_items(response.json())

        has_more, next_offset = _next_page(response.headers, offset, len(items))

        if not items:
            # An empty page doesn't necessarily mean the end - the API may signal more pages
            # via X-Has-More. Keep going, but stop if the offset can't advance (an empty page
            # with no X-Next-Offset would otherwise loop forever on the same request).
            if not has_more or next_offset <= offset:
                return
            yield [], next_offset
            offset = next_offset
            continue

        yield items, next_offset if has_more else None

        if not has_more:
            return

        offset = next_offset


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _telemetry_session_ids(
    session: requests.Session,
    headers: dict[str, str],
    retention_start: datetime,
    logger: FilteringBoundLogger,
    manager: ResumableSourceManager[KernelResumeConfig],
) -> list[str]:
    """Session ids of every browser that can still have retained telemetry events, in id order.

    Ids are collected before fanning out so the offset-paginated /browsers walk isn't stretched
    across thousands of child requests while new sessions shift its pages. The id order is the
    order a resume relies on.
    """
    session_ids: list[str] = []
    for browsers, _next_offset in _iter_list_pages(session, headers, KERNEL_ENDPOINTS["browsers"], logger):
        for browser in browsers:
            if not isinstance(browser, dict):
                continue
            session_id = browser.get("session_id")
            if not isinstance(session_id, str) or not session_id:
                continue
            deleted_at = _parse_timestamp(browser.get("deleted_at"))
            if deleted_at is not None and deleted_at < retention_start:
                continue
            session_ids.append(session_id)
        # No row is handed on while the ids are collected, so the run can stop here.
        manager.safe_point()
    return sorted(set(session_ids))


def _next_telemetry_cursor(headers: Any) -> int | None:
    """The opaque X-Next-Offset cursor, or None when the session has no more events.

    Unlike the list endpoints, this offset is not a row count, so it can't be derived from the
    page length when the header is missing.
    """
    if str(headers.get("X-Has-More", "")).strip().lower() != "true":
        return None
    try:
        cursor = int(headers.get("X-Next-Offset"))
    except (TypeError, ValueError):
        return None
    return cursor if cursor > 0 else None


def _telemetry_row(session_id: str, envelope: dict[str, Any]) -> dict[str, Any]:
    event = envelope.get("event")
    row: dict[str, Any] = {"browser_session_id": session_id, "seq": envelope.get("seq")}
    if isinstance(event, dict):
        row.update(event)
        data = event.get("data")
        if isinstance(data, dict):
            row["data"] = {key: value for key, value in data.items() if key not in TELEMETRY_DROPPED_DATA_FIELDS}
    return row


def _iter_telemetry_pages(
    session: requests.Session,
    headers: dict[str, str],
    session_id: str,
    since: str,
    logger: FilteringBoundLogger,
    cursor: int | None,
) -> Iterator[tuple[list[dict[str, Any]], int | None]]:
    """Yield each page of a session's events with the cursor of the page after it, or None after the last."""
    path = KERNEL_ENDPOINTS[BROWSER_TELEMETRY_EVENTS].path.format(session_id=quote(session_id, safe=""))
    while True:
        # `since` defaults to the last 5 minutes, so it must be set to read the archive.
        # Kernel ignores it once an offset cursor is passed.
        params: dict[str, Any] = {"limit": PAGE_SIZE, "since": since, "order": "asc"}
        if cursor is not None:
            params["offset"] = cursor
        response = _fetch_page(session, _build_url(path, params), headers, logger, allow_not_found=True)
        if response.status_code == 404:
            # The session can be purged between listing browsers and reading its events.
            logger.debug(f"Kernel browser session {session_id} not found, skipping its telemetry events")
            yield [], None
            return

        rows = [
            _telemetry_row(session_id, envelope)
            for envelope in _extract_items(response.json())
            if isinstance(envelope, dict)
        ]
        next_cursor = _next_telemetry_cursor(response.headers)
        if next_cursor is None or next_cursor == cursor:
            yield rows, None
            return
        yield rows, next_cursor
        cursor = next_cursor


def _iter_browser_telemetry_events(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    manager: ResumableSourceManager[KernelResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    retention_start = datetime.now(UTC) - timedelta(days=TELEMETRY_RETENTION_DAYS)
    since = retention_start.strftime("%Y-%m-%dT%H:%M:%SZ")
    resume = manager.load_state() if manager.can_resume() else None
    if resume is not None and resume.completed:
        return
    resume_session_id = resume.telemetry_session_id if resume is not None else None
    session_ids = _telemetry_session_ids(session, headers, retention_start, logger, manager)
    for index, session_id in enumerate(session_ids):
        if resume_session_id is not None and session_id < resume_session_id:
            continue
        cursor = resume.telemetry_cursor if resume is not None and session_id == resume_session_id else None
        following = session_ids[index + 1] if index + 1 < len(session_ids) else None
        for rows, next_cursor in _iter_telemetry_pages(session, headers, session_id, since, logger, cursor):
            if next_cursor is not None:
                manager.save_state(KernelResumeConfig(telemetry_session_id=session_id, telemetry_cursor=next_cursor))
            elif following is not None:
                manager.save_state(KernelResumeConfig(telemetry_session_id=following))
            else:
                manager.save_state(KernelResumeConfig(completed=True))
            if rows:
                yield rows
            else:
                manager.safe_point()


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    manager: ResumableSourceManager[KernelResumeConfig],
) -> Iterator[Any]:
    config = KERNEL_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)
    # One session reused across every page so urllib3 keeps the connection alive.
    # capture=False: Kernel responses carry secret-bearing fields (see SENSITIVE_FIELDS) that the
    # generic HTTP-sample scrubber does not know to redact, and sampling happens before redaction.
    session = make_tracked_session(capture=False)

    # Each page goes out as its own item, so the cursor staged for a page covers every row handed on.
    if endpoint == BROWSER_TELEMETRY_EVENTS:
        yield from _iter_browser_telemetry_events(session, headers, logger, manager)
        return

    resume = manager.load_state() if manager.can_resume() else None
    if resume is not None and resume.completed:
        return
    offset = resume.offset if resume is not None and resume.offset is not None else 0
    for items, next_offset in _iter_list_pages(session, headers, config, logger, offset):
        manager.save_state(
            KernelResumeConfig(offset=next_offset) if next_offset is not None else KernelResumeConfig(completed=True)
        )
        if items:
            yield [_redact_sensitive_fields(item, config.nested_sensitive_fields) for item in items]
        else:
            manager.safe_point()


def kernel_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[KernelResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    endpoint_config: KernelEndpointConfig = KERNEL_ENDPOINTS[endpoint]
    items = (
        partial(
            get_audit_log_rows,
            api_key=api_key,
            logger=logger,
            manager=resumable_source_manager,
            db_incremental_field_last_value=db_incremental_field_last_value,
        )
        if endpoint == AUDIT_LOGS_ENDPOINT
        else partial(get_rows, api_key=api_key, endpoint=endpoint, logger=logger, manager=resumable_source_manager)
    )
    return SourceResponse(
        name=endpoint,
        on_complete=resumable_source_manager.clear_state,
        items=items,
        primary_keys=endpoint_config.primary_keys,
        sort_mode="asc",
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
    )
