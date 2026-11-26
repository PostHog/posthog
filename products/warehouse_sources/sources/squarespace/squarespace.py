import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.sources.sdk import (
    ResumableSourceManager,
    SourceResponse,
    make_tracked_session,
    retry_with_deadline,
)
from products.warehouse_sources.sources.squarespace.settings import SQUARESPACE_ENDPOINTS, SquarespaceEndpointConfig

SQUARESPACE_BASE_URL = "https://api.squarespace.com"

# Squarespace rate-limits requests with a blank/default User-Agent more aggressively,
# so a descriptive one is required.
USER_AGENT = "PostHog-DataWarehouse/1.0 (+https://posthog.com)"

REQUEST_TIMEOUT_SECONDS = 60

# A Squarespace pagination cursor is opaque and dynamic; a resumed or slowly-paginated
# cursor can be rejected mid-stream. Allow a few restarts so a transient rejection during
# the re-scan doesn't fail the sync, while still bounding the work.
MAX_CURSOR_RESTARTS = 3

OFFSET_PAGE_SIZE = 1000


class SquarespaceRetryableError(Exception):
    pass


class SquarespaceInvalidCursorError(Exception):
    pass


@dataclasses.dataclass(frozen=False)
class SquarespaceResumeConfig:
    # The next-page cursor returned by Squarespace. For incremental syncs the cursor
    # preserves the `modifiedAfter`/`modifiedBefore` window of the original request, so
    # resuming from it continues the same window. An empty string means "start over"
    # (merge dedupes the re-pulled rows on the primary key).
    cursor: str
    # Offset-paginated endpoints: the next offset. Fan-out endpoints: how many parents on the
    # parent page at `cursor` are already done.
    offset: int = 0


def _is_invalid_cursor_error(response: requests.Response) -> bool:
    """A 400 whose error payload points at the pagination cursor. Squarespace rejects a
    cursor that is malformed, expired, or sent alongside other query params."""
    if response.status_code != 400:
        return False
    try:
        body = response.json()
    except ValueError:
        return False
    subtype = body.get("subtype") or ""
    message = body.get("message") or ""
    return "cursor" in subtype.lower() or "cursor" in message.lower()


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    }


def _format_datetime_z(value: Any) -> str:
    """Format an incremental value as the ISO 8601 UTC string Squarespace expects
    (YYYY-MM-DDThh:mm:ss.sssZ). Squarespace rejects the +00:00 offset isoformat() emits."""
    if isinstance(value, datetime):
        dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    return str(value)


def _clamp_future_value_to_now(value: Any, now: datetime) -> Any:
    """Cap a future incremental cursor at `now`.

    `modifiedAfter` must be <= `modifiedBefore` (which we set to now), so a future-dated
    cursor would make Squarespace 400 on an inverted window. Asking for rows newer than now
    is a no-op anyway, so clamping keeps the request valid and lets the sync self-heal.
    """
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return now if aware > now else value
    if isinstance(value, date):
        return now.date() if value > now.date() else value
    return value


def _build_initial_params(
    config: SquarespaceEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    modified_before: datetime,
) -> dict[str, str]:
    """Query params for the first page. Cursor-based pages drop these — Squarespace
    rejects a cursor sent alongside any other param."""
    params: dict[str, str] = dict(config.extra_params)

    if config.supports_time_filter and should_use_incremental_field and db_incremental_field_last_value is not None:
        last_value = _clamp_future_value_to_now(db_incremental_field_last_value, modified_before)
        # Squarespace requires modifiedAfter and modifiedBefore together; sending one
        # without the other is a 400.
        params["modifiedAfter"] = _format_datetime_z(last_value)
        params["modifiedBefore"] = _format_datetime_z(modified_before)

    return params


def validate_credentials(
    api_key: str, schema_name: Optional[str] = None
) -> tuple[bool, bool]:  # nosemgrep: tuple-return-prefer-dataclass -- pre-existing, file moved
    """Probe Squarespace to confirm the token works.

    Returns ``(is_valid, is_forbidden)``. ``is_forbidden`` distinguishes a 403 (genuine
    token, but the merchant's plan/scope doesn't grant this resource) from a 401 (bad
    token) so the caller can accept scope gaps at source-create time but reject them for a
    specific schema.
    """
    config = SQUARESPACE_ENDPOINTS.get(schema_name) if schema_name else None
    if config is not None and config.parent is not None:
        # A fan-out path needs a parent id. The parent list needs the same API key permission.
        config = SQUARESPACE_ENDPOINTS[config.parent]
    if config is not None:
        url = _endpoint_url(config)
    else:
        url = f"{SQUARESPACE_BASE_URL}/1.0/commerce/orders"

    try:
        response = make_tracked_session().get(url, headers=_get_headers(api_key), timeout=REQUEST_TIMEOUT_SECONDS)
    except Exception:
        return False, False

    if response.status_code == 403:
        return False, True

    return response.status_code == 200, False


@retry_with_deadline(
    retry=retry_if_exception_type((SquarespaceRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    url: str,
    params: dict[str, str],
    headers: dict[str, str],
    endpoint: str,
    logger: FilteringBoundLogger,
) -> dict[str, Any]:
    response = session.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429 or response.status_code >= 500:
        raise SquarespaceRetryableError(f"Squarespace API error (retryable): status={response.status_code}, url={url}")

    if _is_invalid_cursor_error(response):
        raise SquarespaceInvalidCursorError(f"Squarespace rejected the pagination cursor for {endpoint}")

    if not response.ok:
        logger.error(f"Squarespace API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def _extract_rows(data: dict[str, Any], data_key: str) -> list[dict[str, Any]]:
    """Read the row list at a dotted key, e.g. `addressBook.addressBookEntries`."""
    value: Any = data
    for part in data_key.split("."):
        value = value.get(part) if isinstance(value, dict) else None
    return value or []


def _next_cursor(data: dict[str, Any]) -> Optional[str]:
    pagination = data.get("pagination") or {}
    raw_next_cursor = pagination.get("nextPageCursor")
    if not pagination.get("hasNextPage") or not raw_next_cursor:
        return None
    return str(raw_next_cursor)


def _endpoint_url(config: SquarespaceEndpointConfig) -> str:
    return f"{SQUARESPACE_BASE_URL}/{config.api_version}{config.path}"


def get_offset_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SquarespaceResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = SQUARESPACE_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)
    url = _endpoint_url(config)
    session = make_tracked_session()

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    offset = resume_config.offset if resume_config else 0

    while True:
        params = {**config.extra_params, "offset": str(offset), "limit": str(OFFSET_PAGE_SIZE)}
        data = _fetch_page(session, url, params, headers, endpoint, logger)
        items = _extract_rows(data, config.data_key)
        has_next = bool(data.get("hasNextPage")) and bool(items)

        if items:
            if has_next:
                resumable_source_manager.save_state(SquarespaceResumeConfig(cursor="", offset=offset + len(items)))
            yield items

        if not has_next:
            break

        offset += len(items)


def get_fan_out_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SquarespaceResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = SQUARESPACE_ENDPOINTS[endpoint]
    assert config.parent is not None and config.parent_id_field is not None
    parent_id_field = config.parent_id_field
    parent_config = SQUARESPACE_ENDPOINTS[config.parent]
    headers = _get_headers(api_key)
    parent_url = _endpoint_url(parent_config)
    session = make_tracked_session()

    # The resume state names the parent page in progress (`cursor`, empty for the first page)
    # and how many parents on it are done (`offset`), so a resumed run skips only finished parents.
    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    parent_cursor: Optional[str] = resume_config.cursor if resume_config and resume_config.cursor else None
    parents_done = resume_config.offset if resume_config else 0

    restarts_remaining = MAX_CURSOR_RESTARTS
    while True:
        params = {"cursor": parent_cursor} if parent_cursor else dict(parent_config.extra_params)
        try:
            parent_data = _fetch_page(session, parent_url, params, headers, config.parent, logger)
        except SquarespaceInvalidCursorError:
            if parent_cursor is None or restarts_remaining <= 0:
                raise
            restarts_remaining -= 1
            logger.warning(f"Squarespace: cursor for {endpoint} was rejected, restarting from the first parent")
            parent_cursor, parents_done = None, 0
            continue

        for index, parent in enumerate(_extract_rows(parent_data, parent_config.data_key)):
            parent_id = parent.get("id")
            if index < parents_done or not parent_id:
                continue

            child_url = _endpoint_url(config).replace("{parent_id}", str(parent_id))
            child_rows: list[dict[str, Any]] = []
            child_cursor: Optional[str] = None
            while True:
                child_params = {"cursor": child_cursor} if child_cursor else {}
                try:
                    child_data = _fetch_page(session, child_url, child_params, headers, endpoint, logger)
                except requests.HTTPError as e:
                    # The parent was deleted after the parent page was read.
                    if e.response is not None and e.response.status_code == 404:
                        break
                    raise
                child_rows.extend(
                    {**row, parent_id_field: parent_id} for row in _extract_rows(child_data, config.data_key)
                )
                child_cursor = _next_cursor(child_data)
                if child_cursor is None:
                    break

            resumable_source_manager.save_state(SquarespaceResumeConfig(cursor=parent_cursor or "", offset=index + 1))
            if child_rows:
                yield child_rows
            else:
                resumable_source_manager.safe_point()

        next_parent_cursor = _next_cursor(parent_data)
        if next_parent_cursor is None:
            break
        parent_cursor, parents_done = next_parent_cursor, 0


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SquarespaceResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = SQUARESPACE_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)
    url = _endpoint_url(config)
    session = make_tracked_session()

    # Captured once so the window stays stable across pages and restarts. Rows modified
    # after this point are picked up by the next sync (its window starts at this run's max).
    modified_before = datetime.now(UTC)
    initial_params = _build_initial_params(
        config, should_use_incremental_field, db_incremental_field_last_value, modified_before
    )

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    cursor: Optional[str] = resume_config.cursor if resume_config and resume_config.cursor else None
    if cursor:
        logger.debug(f"Squarespace: resuming {endpoint} from saved cursor")

    def fetch_page(params: dict[str, str]) -> dict[str, Any]:
        return _fetch_page(session, url, params, headers, endpoint, logger)

    restarts_remaining = MAX_CURSOR_RESTARTS
    while True:
        # The cursor encodes the original query (including any window), so cursor pages
        # are requested with the cursor alone — re-sending filters errors.
        params = {"cursor": cursor} if cursor else initial_params
        try:
            data = fetch_page(params)
        except SquarespaceInvalidCursorError:
            # A cursor-less initial request can't trigger this, so a rejection there means a
            # malformed query — surface it. Otherwise restart the stream from the beginning
            # (merge dedupes on the primary key); the restart budget bounds the work.
            if cursor is None or restarts_remaining <= 0:
                raise
            restarts_remaining -= 1
            logger.warning(f"Squarespace: cursor for {endpoint} was rejected, restarting stream from the beginning")
            # Overwrite the stale cursor now so a restart that finishes within a single page
            # (no fresh cursor to save) doesn't leave the bad value to force a re-scan next sync.
            resumable_source_manager.save_state(SquarespaceResumeConfig(cursor=""))
            cursor = None
            continue

        items = data.get(config.data_key, [])
        pagination = data.get("pagination") or {}
        raw_next_cursor = pagination.get("nextPageCursor")
        next_cursor = str(raw_next_cursor) if raw_next_cursor else None
        has_next = bool(pagination.get("hasNextPage")) and next_cursor is not None

        if items:
            yield items
            # Save state only after yielding, so a crash re-yields the last batch rather
            # than skipping it (merge dedupes on the primary key).
            if has_next and next_cursor is not None:
                resumable_source_manager.save_state(SquarespaceResumeConfig(cursor=next_cursor))

        if not has_next:
            break

        cursor = next_cursor


def squarespace_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SquarespaceResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = SQUARESPACE_ENDPOINTS[endpoint]

    def items() -> Iterator[list[dict[str, Any]]]:
        if config.parent is not None:
            return get_fan_out_rows(api_key, endpoint, logger, resumable_source_manager)
        if config.pagination == "offset":
            return get_offset_rows(api_key, endpoint, logger, resumable_source_manager)
        return get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        )

    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=config.primary_keys,
        sort_mode=config.sort_mode,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
