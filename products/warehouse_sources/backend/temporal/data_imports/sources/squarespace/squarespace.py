import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.squarespace.settings import (
    SQUARESPACE_ENDPOINTS,
    SquarespaceEndpointConfig,
)

SQUARESPACE_BASE_URL = "https://api.squarespace.com"

# Squarespace rate-limits requests with a blank/default User-Agent more aggressively,
# so a descriptive one is required.
USER_AGENT = "PostHog-DataWarehouse/1.0 (+https://posthog.com)"

REQUEST_TIMEOUT_SECONDS = 60

# A Squarespace pagination cursor is opaque and dynamic; a resumed or slowly-paginated
# cursor can be rejected mid-stream. Allow a few restarts so a transient rejection during
# the re-scan doesn't fail the sync, while still bounding the work.
MAX_CURSOR_RESTARTS = 3


class SquarespaceRetryableError(Exception):
    pass


class SquarespaceInvalidCursorError(Exception):
    pass


@dataclasses.dataclass
class SquarespaceResumeConfig:
    # The next-page cursor returned by Squarespace. For incremental syncs the cursor
    # preserves the `modifiedAfter`/`modifiedBefore` window of the original request, so
    # resuming from it continues the same window. An empty string means "start over"
    # (merge dedupes the re-pulled rows on the primary key).
    cursor: str


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


def validate_credentials(api_key: str, schema_name: Optional[str] = None) -> tuple[bool, bool]:
    """Probe Squarespace to confirm the token works.

    Returns ``(is_valid, is_forbidden)``. ``is_forbidden`` distinguishes a 403 (genuine
    token, but the merchant's plan/scope doesn't grant this resource) from a 401 (bad
    token) so the caller can accept scope gaps at source-create time but reject them for a
    specific schema.
    """
    config = SQUARESPACE_ENDPOINTS.get(schema_name) if schema_name else None
    if config is not None:
        url = f"{SQUARESPACE_BASE_URL}/{config.api_version}{config.path}"
    else:
        url = f"{SQUARESPACE_BASE_URL}/1.0/commerce/orders"

    try:
        response = make_tracked_session().get(url, headers=_get_headers(api_key), timeout=REQUEST_TIMEOUT_SECONDS)
    except Exception:
        return False, False

    if response.status_code == 403:
        return False, True

    return response.status_code == 200, False


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
    url = f"{SQUARESPACE_BASE_URL}/{config.api_version}{config.path}"
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

    @retry(
        retry=retry_if_exception_type((SquarespaceRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(5),
        wait=wait_exponential_jitter(initial=1, max=30),
        reraise=True,
    )
    def fetch_page(params: dict[str, str]) -> dict[str, Any]:
        response = session.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code == 429 or response.status_code >= 500:
            raise SquarespaceRetryableError(
                f"Squarespace API error (retryable): status={response.status_code}, url={url}"
            )

        if _is_invalid_cursor_error(response):
            raise SquarespaceInvalidCursorError(f"Squarespace rejected the pagination cursor for {endpoint}")

        if not response.ok:
            logger.error(f"Squarespace API error: status={response.status_code}, body={response.text}, url={url}")
            response.raise_for_status()

        return response.json()

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

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        sort_mode=config.sort_mode,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
