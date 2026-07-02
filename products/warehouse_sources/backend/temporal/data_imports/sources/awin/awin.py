import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.awin.settings import (
    AWIN_ENDPOINTS,
    DEFAULT_BACKFILL_DAYS,
    MAX_WINDOW_DAYS,
    AwinEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

AWIN_BASE_URL = "https://api.awin.com"

# Awin windows are always expressed against a named timezone param rather than an offset baked into
# the timestamp string. We pin everything to UTC so cursors and windows stay consistent.
AWIN_TIMEZONE = "UTC"

REQUEST_TIMEOUT_SECONDS = 60


class AwinRetryableError(Exception):
    """Transient Awin API failure (429 throttling or 5xx) worth retrying."""


@dataclasses.dataclass
class AwinResumeConfig:
    # The publisher account currently being processed. A stable account-ID bookmark (not a positional
    # index) so accounts added/removed between a crash and the retry can't resume us into the wrong one.
    account_id: Optional[int] = None
    # ISO start of the date window last yielded for `account_id`. `None` for non-windowed endpoints.
    window_start: Optional[str] = None


def _get_headers(api_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_token}",
        "Accept": "application/json",
    }


@retry(
    retry=retry_if_exception_type(
        (
            AwinRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(6),
    # Awin throttles at 20 calls/minute/user, so back off generously (up to a minute) on a 429.
    wait=wait_exponential_jitter(initial=2, max=60),
    reraise=True,
)
def _fetch(
    session: requests.Session,
    path: str,
    headers: dict[str, str],
    params: dict[str, Any],
    logger: FilteringBoundLogger,
) -> Any:
    url = f"{AWIN_BASE_URL}{path}"
    if params:
        url = f"{url}?{urlencode(params)}"

    response = session.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429 or response.status_code >= 500:
        raise AwinRetryableError(f"Awin API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Awin API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def validate_credentials(api_token: str) -> bool:
    try:
        session = make_tracked_session(redact_values=(api_token,))
        response = session.get(f"{AWIN_BASE_URL}/accounts", headers=_get_headers(api_token), timeout=10)
        return response.status_code == 200
    except Exception:
        return False


def _discover_publisher_ids(
    session: requests.Session, headers: dict[str, str], logger: FilteringBoundLogger
) -> list[int]:
    """Return the publisher account ids the token can access, sorted for deterministic fan-out order.

    Awin exposes both publisher and advertiser accounts through /accounts; every endpoint this source
    implements is publisher-scoped, so we keep only the publisher accounts.
    """
    data = _fetch(session, "/accounts", headers, {}, logger)
    accounts = data.get("accounts", []) if isinstance(data, dict) else []
    publisher_ids = [
        account["accountId"]
        for account in accounts
        if account.get("accountType") == "publisher" and account.get("accountId") is not None
    ]
    return sorted(set(publisher_ids))


def _to_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
        except ValueError:
            return None
    return None


def _iter_windows(start: datetime, end: datetime, max_days: int) -> Iterator[tuple[datetime, datetime]]:
    """Yield ascending (start, end) windows no wider than `max_days`, covering [start, end]."""
    cursor = start
    step = timedelta(days=max_days)
    while cursor < end:
        window_end = min(cursor + step, end)
        yield cursor, window_end
        cursor = window_end


def _build_window_params(
    config: AwinEndpointConfig, window_start: datetime, window_end: datetime, incremental_field: Optional[str]
) -> dict[str, str]:
    params: dict[str, str] = {
        "startDate": window_start.strftime(config.date_format),
        "endDate": window_end.strftime(config.date_format),
        "timezone": AWIN_TIMEZONE,
    }
    if config.date_type_by_field:
        default_date_type = next(iter(config.date_type_by_field.values()))
        params["dateType"] = config.date_type_by_field.get(incremental_field or "", default_date_type)
    params.update(config.extra_params)
    return params


def _windows_for_account(
    config: AwinEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> list[Optional[tuple[datetime, datetime]]]:
    """Build the ordered list of date windows to fetch for one account.

    Non-windowed endpoints (programmes) collapse to a single `None` window (one plain request).
    """
    if not config.date_windowed:
        return [None]

    now = datetime.now(UTC)
    if config.report_lookback_days is not None:
        # Reports are a rolling full-refresh snapshot, not an incremental scroll.
        start = now - timedelta(days=config.report_lookback_days)
    elif should_use_incremental_field and db_incremental_field_last_value is not None:
        start = _to_datetime(db_incremental_field_last_value) or (now - timedelta(days=DEFAULT_BACKFILL_DAYS))
    else:
        start = now - timedelta(days=DEFAULT_BACKFILL_DAYS)

    if start >= now:
        return []
    return list(_iter_windows(start, now, MAX_WINDOW_DAYS))


def _rows_from_response(config: AwinEndpointConfig, data: Any, publisher_id: Optional[int]) -> list[dict[str, Any]]:
    if config.data_key is not None:
        rows = data.get(config.data_key, []) if isinstance(data, dict) else []
    else:
        rows = data if isinstance(data, list) else []

    rows = [row for row in rows if isinstance(row, dict)]
    if config.inject_publisher_id and publisher_id is not None:
        for row in rows:
            row.setdefault("publisherId", publisher_id)
    return rows


def _resume_index(
    work_items: list[tuple[Optional[tuple[datetime, datetime]], int]], resume: Optional[AwinResumeConfig]
) -> int:
    """Find where to restart the (window, account) work list from a saved bookmark.

    Returns the index of the last-yielded item so it's re-processed (merge dedupes) and everything
    after it runs. Falls back to the start when there's no bookmark or it no longer matches (e.g. the
    account list changed between runs).
    """
    if resume is None:
        return 0
    for index, (window, publisher_id) in enumerate(work_items):
        window_start = window[0].isoformat() if window is not None else None
        if publisher_id == resume.account_id and window_start == resume.window_start:
            return index
    return 0


def get_rows(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[AwinResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: Optional[str] = None,
) -> Iterator[list[dict[str, Any]]]:
    config = AWIN_ENDPOINTS[endpoint]
    headers = _get_headers(api_token)
    # Register the token so the tracked transport masks it in logged URLs and captured samples.
    session = make_tracked_session(redact_values=(api_token,))

    if config.kind == "accounts":
        data = _fetch(session, config.path, headers, config.extra_params, logger)
        rows = _rows_from_response(config, data, publisher_id=None)
        if rows:
            yield rows
        return

    publisher_ids = _discover_publisher_ids(session, headers, logger)
    if not publisher_ids:
        logger.warning("Awin: no publisher accounts found for token; nothing to sync")
        return

    # Every account shares the same window list (it depends only on the cursor, not the account). We
    # iterate windows OUTER and accounts INNER so rows arrive in globally ascending date order across
    # all accounts — required for the `sort_mode="asc"` watermark to advance monotonically.
    windows = _windows_for_account(config, should_use_incremental_field, db_incremental_field_last_value)
    work_items = [(window, publisher_id) for window in windows for publisher_id in publisher_ids]

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    start_index = _resume_index(work_items, resume)
    if start_index > 0:
        logger.debug(f"Awin: resuming {endpoint} from item {start_index}/{len(work_items)}")

    for window, publisher_id in work_items[start_index:]:
        params = config.extra_params if window is None else _build_window_params(config, *window, incremental_field)
        data = _fetch(session, config.path.format(publisher_id=publisher_id), headers, params, logger)
        rows = _rows_from_response(config, data, publisher_id)
        if rows:
            yield rows
        # Save after processing each work item. A crash before this line re-fetches the same item on
        # resume: if it yielded rows they're re-yielded and merge dedupes on the primary key; an empty
        # window is simply re-fetched (a no-op).
        resumable_source_manager.save_state(
            AwinResumeConfig(
                account_id=publisher_id,
                window_start=window[0].isoformat() if window is not None else None,
            )
        )


def awin_source(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[AwinResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: Optional[str] = None,
) -> SourceResponse:
    config = AWIN_ENDPOINTS[endpoint]

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
        primary_keys=config.primary_keys,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
