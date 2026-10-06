import base64
import hashlib
import dataclasses
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any

import orjson
import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter
from urllib3.util.retry import Retry

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.cursor.settings import (
    CURSOR_ENDPOINTS,
    MAX_WINDOW_DAYS,
    CursorEndpointConfig,
)

CURSOR_BASE_URL = "https://api.cursor.com"

# First sync fetches this much history instead of walking back to the team's creation.
DEFAULT_LOOKBACK_DAYS = 365
REQUEST_TIMEOUT_SECONDS = 60


class CursorRetryableError(Exception):
    pass


@dataclasses.dataclass
class CursorResumeConfig:
    # Start (epoch ms) of the window being processed when the sync was interrupted.
    # None for the non-windowed endpoints (members, spend).
    window_start: int | None = None
    # 1-based page to resume from within that window (or within the spend listing).
    page: int = 1


def _to_epoch_ms(value: Any) -> int:
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return int(aware.timestamp() * 1000)
    if isinstance(value, date):
        return int(datetime.combine(value, datetime.min.time(), tzinfo=UTC).timestamp() * 1000)
    if isinstance(value, int | float):
        return int(value)
    return int(str(value))


def _from_epoch_ms(value: Any) -> datetime:
    return datetime.fromtimestamp(int(value) / 1000, tz=UTC)


def _parse_iso(value: str) -> datetime:
    """Parse a Cursor Analytics date (`2025-01-15`) or timestamp (`2025-01-15T14:12:03.000Z`)."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _to_iso_date(value: int) -> str:
    return _from_epoch_ms(value).strftime("%Y-%m-%d")


def _now_ms() -> int:
    return int(datetime.now(UTC).timestamp() * 1000)


def _basic_token(api_key: str) -> str:
    # Cursor's Admin API uses HTTP Basic auth with the API key as the username and an empty password.
    return base64.b64encode(f"{api_key}:".encode("ascii")).decode("ascii")


def _redact_values(api_key: str) -> tuple[str, ...]:
    # Mask both the raw key and the derived Basic token so neither leaks into logged URLs/samples.
    return (api_key, _basic_token(api_key))


def _make_session(api_key: str) -> requests.Session:
    # Redirects are pinned off so the credential can't be replayed to a cross-host redirect target;
    # urllib3 retries are disabled so tenacity (on `_fetch`) is the single retry layer.
    return make_tracked_session(
        headers={"Authorization": f"Basic {_basic_token(api_key)}", "Accept": "application/json"},
        redact_values=_redact_values(api_key),
        allow_redirects=False,
        retry=Retry(total=0),
    )


@retry(
    retry=retry_if_exception_type(
        (
            CursorRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(6),
    # The main read endpoints are limited to ~20 requests/minute per team, so back off far enough
    # for the rate-limit window to reset before giving up.
    wait=wait_exponential_jitter(initial=3, max=70),
    reraise=True,
)
def _fetch(
    session: requests.Session,
    method: str,
    url: str,
    logger: FilteringBoundLogger,
    json_body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response = session.request(
        method,
        url,
        json=json_body,
        params=params,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    if response.status_code == 429 or response.status_code >= 500:
        raise CursorRetryableError(f"Cursor API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Cursor API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


# Shared with `CursorSource.get_non_retryable_errors` so the same rejection reads the same way
# whether it surfaces while connecting the source or mid-sync.
KEY_REJECTED_MESSAGE = (
    "Your Cursor Admin API key is invalid or has been revoked. Create a new key in your Cursor "
    "dashboard settings, then reconnect."
)
KEY_FORBIDDEN_MESSAGE = (
    "Your Cursor Admin API key does not have access to this data. Admin API keys must be created "
    "by a team admin, and some endpoints require an Enterprise plan."
)
# `validate_via_probe` reports a transport failure as a `None` status, so anything Cursor did not
# answer itself leaves the key unjudged. Calling it invalid sends someone off to mint a replacement
# that fails the same way.
PROBE_FAILED_MESSAGE = "PostHog couldn't check your Admin API key with Cursor. Wait a few minutes and try again."


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    # Redirects stay off for the same reason `_make_session` pins them off: `requests` keeps custom
    # headers on a cross-host redirect.
    ok, status = validate_via_probe(
        lambda: _make_session(api_key),
        f"{CURSOR_BASE_URL}/teams/members",
        allow_redirects=False,
    )
    if ok:
        return True, None
    if status == 401:
        return False, KEY_REJECTED_MESSAGE
    if status == 403:
        return False, KEY_FORBIDDEN_MESSAGE
    return False, PROBE_FAILED_MESSAGE


def _usage_event_id(item: dict[str, Any]) -> str:
    """Deterministic id for a usage event, hashed from the raw payload.

    The filtered-usage-events endpoint returns no event identifier, so this synthesizes one:
    identical payloads (the same event re-fetched across overlapping incremental windows)
    collapse to one row on merge, while any field difference yields a distinct key. Two
    genuinely identical events in the same millisecond would collapse too — an accepted
    tradeoff versus unbounded duplication.
    """
    return hashlib.sha256(orjson.dumps(item, option=orjson.OPT_SORT_KEYS)).hexdigest()


def _normalize_daily_usage(item: dict[str, Any]) -> dict[str, Any]:
    if "date" in item and item["date"] is not None:
        item["date"] = _from_epoch_ms(item["date"])
    return item


def _normalize_usage_event(item: dict[str, Any]) -> dict[str, Any]:
    item["id"] = _usage_event_id(item)
    # `timestamp` arrives as an epoch-ms string; convert so the column is a real datetime.
    if "timestamp" in item and item["timestamp"] is not None:
        item["timestamp"] = _from_epoch_ms(item["timestamp"])
    return item


def _make_iso_normalizer(*field_names: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Build a normalizer that turns the named Analytics API date strings into datetimes."""

    def normalize(item: dict[str, Any]) -> dict[str, Any]:
        for field_name in field_names:
            value = item.get(field_name)
            if isinstance(value, str):
                item[field_name] = _parse_iso(value)
        return item

    return normalize


@frozen
class Window:
    start_ms: int
    end_ms: int


def _build_windows(start_ms: int, end_ms: int, window_days: int = MAX_WINDOW_DAYS) -> Iterator[Window]:
    """Chunk [start_ms, end_ms] into inclusive windows of at most `window_days`."""
    window_ms = int(timedelta(days=window_days).total_seconds() * 1000)
    window_start = start_ms
    while window_start <= end_ms:
        window_end = min(window_start + window_ms - 1, end_ms)
        yield Window(start_ms=window_start, end_ms=window_end)
        window_start = window_end + 1


def _has_next_page(data: dict[str, Any], page: int, items_count: int, page_size: int) -> bool:
    """Read the has-more signal from whichever pagination shape the endpoint returns.

    filtered-usage-events, daily-usage-data and the by-user analytics endpoints nest `hasNextPage`
    (plus `numPages`/`totalPages`) under `pagination`; /teams/spend returns `totalPages` at the top
    level, and /analytics/ai-code/commits returns `totalCount`. Fall back to a
    full-page heuristic when none is present (the API silently ignoring pagination params
    would otherwise loop forever on the same rows).
    """
    pagination = data.get("pagination")
    if isinstance(pagination, dict):
        has_next = pagination.get("hasNextPage")
        if has_next is not None:
            return bool(has_next)
        total_pages = pagination.get("numPages") or pagination.get("totalPages")
        if total_pages is not None:
            return page < int(total_pages)
    total_pages = data.get("totalPages")
    if total_pages is not None:
        return page < int(total_pages)
    total_count = data.get("totalCount")
    if total_count is not None:
        return page * page_size < int(total_count)
    return items_count >= page_size


def _get_members_rows(
    session: requests.Session,
    config: CursorEndpointConfig,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    data = _fetch(session, config.method, f"{CURSOR_BASE_URL}{config.path}", logger)
    rows = data.get(config.data_key) or []
    if rows:
        yield rows


def _get_spend_rows(
    session: requests.Session,
    config: CursorEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CursorResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page = resume.page if resume is not None else 1

    while True:
        body = {
            "page": page,
            "pageSize": config.page_size,
            # Spend amounts change while we paginate; sorting by user keeps page boundaries stable.
            "sortBy": "user",
            "sortDirection": "asc",
        }
        data = _fetch(session, config.method, f"{CURSOR_BASE_URL}{config.path}", logger, json_body=body)

        rows = data.get(config.data_key) or []
        cycle_start = data.get("subscriptionCycleStart")
        for row in rows:
            row["subscriptionCycleStart"] = cycle_start

        has_next = _has_next_page(data, page, len(rows), config.page_size)

        if rows:
            yield rows
            # Save AFTER yielding so a crash re-yields the last page rather than skipping it —
            # merge dedupes on the primary key.
            if has_next:
                resumable_source_manager.save_state(CursorResumeConfig(page=page + 1))

        if not rows or not has_next:
            break
        page += 1


_WINDOWED_NORMALIZERS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "usage_events": _normalize_usage_event,
    "daily_usage": _normalize_daily_usage,
    "agent_edits": _make_iso_normalizer("event_date"),
    "tabs": _make_iso_normalizer("event_date"),
    "by_user_agent_edits": _make_iso_normalizer("event_date"),
    "by_user_tabs": _make_iso_normalizer("event_date"),
    "by_user_top_file_extensions": _make_iso_normalizer("event_date"),
    "by_user_models": _make_iso_normalizer("date"),
    "ai_code_commits": _make_iso_normalizer("commitTs", "createdAt"),
}


def _expand_model_breakdown(row: dict[str, Any]) -> list[dict[str, Any]]:
    """Turn the per-model map into one row per model.

    The map is keyed by model name, so leaving it nested would change the table's column types
    every time the team picks up a model it has not used before.
    """
    breakdown = row.pop("model_breakdown", None)
    if not isinstance(breakdown, dict):
        return []
    return [
        {**row, "model": model, **(metrics if isinstance(metrics, dict) else {})}
        for model, metrics in breakdown.items()
    ]


_ROW_EXPANDERS: dict[str, Callable[[dict[str, Any]], list[dict[str, Any]]]] = {
    "by_user_models": _expand_model_breakdown,
}


def _extract_rows(config: CursorEndpointConfig, data: dict[str, Any]) -> list[dict[str, Any]]:
    payload = data.get(config.data_key)
    if not config.by_user:
        return payload or []
    if not isinstance(payload, dict):
        return []

    # By-user responses key rows by email and carry the public user ids alongside, so stamp both
    # onto every row — otherwise the identity a row belongs to is lost in the flattening.
    ids_by_email = {
        mapping["email"]: mapping.get("id")
        for mapping in ((data.get("params") or {}).get("userMappings") or [])
        if isinstance(mapping, dict) and mapping.get("email")
    }
    expand = _ROW_EXPANDERS.get(config.name)
    rows = [
        {**row, "userEmail": email, "userId": ids_by_email.get(email)}
        for email, user_rows in payload.items()
        for row in user_rows or []
    ]
    return [expanded for row in rows for expanded in expand(row)] if expand else rows


def _page_item_count(config: CursorEndpointConfig, data: dict[str, Any], rows: list[dict[str, Any]]) -> int:
    # A by-user page holds `pageSize` users, not `pageSize` rows, so the full-page fallback in
    # `_has_next_page` has to count users.
    if config.by_user:
        payload = data.get(config.data_key)
        return len(payload) if isinstance(payload, dict) else 0
    return len(rows)


def _window_request_params(
    config: CursorEndpointConfig, window_start: int, window_end: int, page: int
) -> dict[str, Any]:
    if config.date_param_format == "iso_date":
        params: dict[str, Any] = {"startDate": _to_iso_date(window_start), "endDate": _to_iso_date(window_end)}
    else:
        params = {"startDate": window_start, "endDate": window_end}
    if config.paginated:
        params |= {"page": page, "pageSize": config.page_size}
    return params


@frozen
class WindowStart:
    start_ms: int
    first_page: int


def _resolve_window_start(
    config: CursorEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CursorResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    end_ms: int,
) -> WindowStart:
    """Return the first window start and page for a windowed sync.

    Prefer a saved resume point; otherwise start at the incremental watermark, and fall back to
    the default lookback for a first sync.
    """
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.window_start is not None:
        logger.debug(f"Cursor: resuming {config.name} from window_start={resume.window_start}, page={resume.page}")
        return WindowStart(start_ms=resume.window_start, first_page=resume.page)

    if should_use_incremental_field and db_incremental_field_last_value is not None:
        # startDate/endDate bounds are inclusive, so starting at the watermark re-fetches the
        # rows at exactly the watermark value — merge dedupes them, and for daily_usage it also
        # refreshes the partial day the previous sync ended on.
        return WindowStart(start_ms=min(_to_epoch_ms(db_incremental_field_last_value), end_ms), first_page=1)

    return WindowStart(
        start_ms=end_ms - int(timedelta(days=DEFAULT_LOOKBACK_DAYS).total_seconds() * 1000), first_page=1
    )


def _paginate_window(
    session: requests.Session,
    config: CursorEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CursorResumeConfig],
    normalize: Callable[[dict[str, Any]], dict[str, Any]],
    window_start: int,
    window_end: int,
    end_ms: int,
    first_page: int,
) -> Iterator[list[dict[str, Any]]]:
    page = first_page
    while True:
        request_params = _window_request_params(config, window_start, window_end, page)
        url = f"{CURSOR_BASE_URL}{config.path}"
        if config.query_params:
            data = _fetch(session, config.method, url, logger, params=request_params)
        else:
            data = _fetch(session, config.method, url, logger, json_body=request_params)

        items = _extract_rows(config, data)
        rows = [normalize(item) for item in items]
        # A by-user page is sized in users, and a user with no activity in the window contributes
        # no rows — so termination has to read the page's own size, not the row count.
        page_items = _page_item_count(config, data, items)
        has_next = config.paginated and _has_next_page(data, page, page_items, config.page_size)

        if rows:
            yield rows
            # Save AFTER yielding so a crash re-yields the last batch rather than skipping it.
            if has_next:
                resumable_source_manager.save_state(CursorResumeConfig(window_start=window_start, page=page + 1))
            elif window_end + 1 <= end_ms:
                resumable_source_manager.save_state(CursorResumeConfig(window_start=window_end + 1, page=1))

        if not page_items or not has_next:
            break
        page += 1


def _get_windowed_rows(
    session: requests.Session,
    config: CursorEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CursorResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    end_ms = _now_ms()

    window_start = _resolve_window_start(
        config,
        logger,
        resumable_source_manager,
        should_use_incremental_field,
        db_incremental_field_last_value,
        end_ms,
    )

    normalize = _WINDOWED_NORMALIZERS.get(config.name)
    if normalize is None:
        raise ValueError(f"No normalizer defined for windowed endpoint: {config.name}")

    first_page = window_start.first_page
    for window in _build_windows(window_start.start_ms, end_ms, config.window_days):
        yield from _paginate_window(
            session,
            config,
            logger,
            resumable_source_manager,
            normalize,
            window.start_ms,
            window.end_ms,
            end_ms,
            first_page,
        )
        first_page = 1  # only the resumed-into window starts mid-pagination


def cursor_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CursorResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> SourceResponse:
    config = CURSOR_ENDPOINTS.get(endpoint)
    if config is None:
        raise ValueError(f"Unknown Cursor endpoint: {endpoint}")

    def get_rows() -> Iterator[list[dict[str, Any]]]:
        session = _make_session(api_key)

        if endpoint == "members":
            yield from _get_members_rows(session, config, logger)
        elif endpoint == "spend":
            yield from _get_spend_rows(session, config, logger, resumable_source_manager)
        else:
            yield from _get_windowed_rows(
                session,
                config,
                logger,
                resumable_source_manager,
                should_use_incremental_field,
                db_incremental_field_last_value,
            )

    return SourceResponse(
        name=endpoint,
        items=get_rows,
        primary_keys=config.primary_keys,
        partition_keys=[config.partition_key] if config.partition_key else None,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        sort_mode="asc",
    )
