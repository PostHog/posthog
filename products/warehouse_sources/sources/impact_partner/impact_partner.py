import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional

import requests
from requests.auth import HTTPBasicAuth
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.sources.impact_partner.settings import (
    IMPACT_PARTNER_ENDPOINTS,
    MAX_LOOKBACK_DAYS,
    MAX_WINDOW_DAYS,
    ImpactPartnerEndpointConfig,
)
from products.warehouse_sources.sources.sdk import ResumableSourceManager, SourceResponse, make_tracked_session

BASE_URL = "https://api.impact.com"

REQUEST_TIMEOUT_SECONDS = 60


@dataclasses.dataclass(frozen=True)
class ImpactPartnerResumeConfig:
    # The last page fetched. Re-fetched on resume (merge dedupes).
    page: Optional[int] = None
    # Actions: ISO bounds of the exact window being processed, narrower than the top-level grid
    # once a 400 has split it. A bookmark missing `window_end` (an older run) restarts instead.
    window_start: Optional[str] = None
    window_end: Optional[str] = None


def _get_session(account_sid: str, auth_token: str, api_version: str) -> requests.Session:
    session = make_tracked_session(redact_values=(auth_token,))
    session.auth = HTTPBasicAuth(account_sid, auth_token)
    # Impact.com returns XML unless explicitly asked for JSON.
    session.headers["Accept"] = "application/json"
    # Pin the vendor API version per request; without it Impact falls back to the account's
    # default version setting and response shapes vary between customers.
    session.headers["IR-Version"] = api_version
    return session


def _fetch(
    session: requests.Session, account_sid: str, path: str, params: dict[str, Any], logger: FilteringBoundLogger
) -> Any:
    url = f"{BASE_URL}/Mediapartners/{account_sid}{path}"
    response = session.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
    if not response.ok:
        logger.error(f"Impact Partner API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()
    return response.json()


def validate_credentials(account_sid: str, auth_token: str, api_version: str) -> bool:
    try:
        session = _get_session(account_sid, auth_token, api_version)
        response = session.get(
            f"{BASE_URL}/Mediapartners/{account_sid}/Campaigns",
            params={"PageSize": 1},
            timeout=10,
        )
        return response.status_code == 200
    except Exception:
        return False


def _safe_int(value: Any) -> Optional[int]:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _rows_from_response(config: ImpactPartnerEndpointConfig, data: Any) -> list[dict[str, Any]]:
    rows = data.get(config.data_key, []) if isinstance(data, dict) else []
    return [row for row in rows if isinstance(row, dict)]


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


def _format_datetime(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def _iter_windows(start: datetime, end: datetime, max_days: int) -> Iterator[tuple[datetime, datetime]]:
    """Yield ascending (start, end) windows no wider than `max_days`, covering [start, end]."""
    cursor = start
    step = timedelta(days=max_days)
    while cursor < end:
        window_end = min(cursor + step, end)
        yield cursor, window_end
        cursor = window_end


# Impact caps a date-windowed query at 10 pages, 400ing every page of a denser window regardless
# of which one is requested. Our 45-day span cap doesn't prevent that, so narrow and retry instead.
MIN_SPLIT_WINDOW = timedelta(days=1)  # floor so an unrelated, persistent 400 still surfaces


@dataclasses.dataclass(frozen=True)
class ActionsWindow:
    start: datetime
    end: datetime


@dataclasses.dataclass(frozen=True)
class FetchedActionsPage:
    window: ActionsWindow
    page: int
    rows: list[dict[str, Any]]


def _split_window(window: ActionsWindow) -> list[ActionsWindow]:
    midpoint = window.start + (window.end - window.start) / 2
    return [ActionsWindow(start=window.start, end=midpoint), ActionsWindow(start=midpoint, end=window.end)]


def _fetch_actions_window(
    session: requests.Session,
    account_sid: str,
    config: ImpactPartnerEndpointConfig,
    window: ActionsWindow,
    logger: FilteringBoundLogger,
    start_param: str,
    end_param: str,
    start_page: int,
) -> Iterator[FetchedActionsPage]:
    """Yield a page at a time for `window`, narrowing it if Impact rejects it as too large."""
    params: dict[str, Any] = {start_param: _format_datetime(window.start), end_param: _format_datetime(window.end)}
    try:
        for page, rows in _paginate_endpoint(session, account_sid, config, params, logger, start_page=start_page):
            yield FetchedActionsPage(window=window, page=page, rows=rows)
    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else None
        if status != 400 or (window.end - window.start) <= MIN_SPLIT_WINDOW:
            raise
        logger.debug(f"Impact Partner: narrowing a {window.end - window.start} Actions window after a 400")
        for half in _split_window(window):
            yield from _fetch_actions_window(session, account_sid, config, half, logger, start_param, end_param, 1)


def _paginate_endpoint(
    session: requests.Session,
    account_sid: str,
    config: ImpactPartnerEndpointConfig,
    params: dict[str, Any],
    logger: FilteringBoundLogger,
    start_page: int = 1,
) -> Iterator[tuple[int, list[dict[str, Any]]]]:
    """Yield (page_number, rows) from `start_page` to the last page (`@numpages`)."""
    page = start_page
    while True:
        page_params = {**params, "Page": page, "PageSize": config.page_size}
        data = _fetch(session, account_sid, config.path, page_params, logger)
        rows = _rows_from_response(config, data)
        yield page, rows

        num_pages = _safe_int(data.get("@numpages")) if isinstance(data, dict) else None
        if not rows or (num_pages is not None and page >= num_pages):
            break
        page += 1


def _windows_for_actions(
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> list[tuple[datetime, datetime]]:
    now = datetime.now(UTC)
    max_lookback_start = now - timedelta(days=MAX_LOOKBACK_DAYS)

    if should_use_incremental_field and db_incremental_field_last_value is not None:
        cursor_start = _to_datetime(db_incremental_field_last_value)
        start = max(cursor_start, max_lookback_start) if cursor_start is not None else max_lookback_start
    else:
        start = max_lookback_start

    if start >= now:
        return []
    return list(_iter_windows(start, now, MAX_WINDOW_DAYS))


def _resume_target(
    windows: list[tuple[datetime, datetime]], resume: Optional[ImpactPartnerResumeConfig]
) -> Optional[tuple[int, ActionsWindow]]:
    """Find the top-level window a saved bookmark falls inside, and the exact slice to resume.

    Matches by containment, since a 400 split can leave the bookmark narrower than the top-level
    window. Returns None when there's no bookmark, no `window_end`, or no window contains it
    (boundaries derive from the current time, so they shift between runs); the caller then starts
    over, which merge dedupes.
    """
    if resume is None or resume.window_start is None or resume.window_end is None:
        return None
    saved_start = _to_datetime(resume.window_start)
    saved_end = _to_datetime(resume.window_end)
    if saved_start is None or saved_end is None:
        return None
    for index, window in enumerate(windows):
        if window[0] <= saved_start and saved_end <= window[1]:
            return index, ActionsWindow(start=saved_start, end=saved_end)
    return None


def _get_rows_simple(
    session: requests.Session,
    account_sid: str,
    config: ImpactPartnerEndpointConfig,
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    resumable_source_manager: ResumableSourceManager[ImpactPartnerResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    params: dict[str, Any] = {}
    if config.incremental_start_param and should_use_incremental_field and db_incremental_field_last_value is not None:
        cursor = _to_datetime(db_incremental_field_last_value)
        if cursor is not None:
            params[config.incremental_start_param] = _format_datetime(cursor)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    start_page = resume.page if resume and resume.page else 1

    for page, rows in _paginate_endpoint(session, account_sid, config, params, logger, start_page=start_page):
        if rows:
            yield rows
        # Save after yielding: a crash re-fetches this same page and merge dedupes it.
        resumable_source_manager.save_state(ImpactPartnerResumeConfig(page=page))


def _get_rows_windowed(
    session: requests.Session,
    account_sid: str,
    config: ImpactPartnerEndpointConfig,
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    resumable_source_manager: ResumableSourceManager[ImpactPartnerResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    # Only the Actions config reaches this path, and it always declares both date params.
    assert config.incremental_start_param is not None
    assert config.incremental_end_param is not None
    start_param = config.incremental_start_param
    end_param = config.incremental_end_param

    # Unlike the brand API, the partner Actions endpoint doesn't require a CampaignId filter,
    # so history is walked in date windows only, with no per-campaign fan-out.
    windows = _windows_for_actions(should_use_incremental_field, db_incremental_field_last_value)

    def _run(window: ActionsWindow, start_page: int) -> Iterator[list[dict[str, Any]]]:
        for fetched in _fetch_actions_window(
            session, account_sid, config, window, logger, start_param, end_param, start_page
        ):
            if fetched.rows:
                yield fetched.rows
            # Save after yielding: a crash re-fetches this same page and merge dedupes it.
            resumable_source_manager.save_state(
                ImpactPartnerResumeConfig(
                    page=fetched.page,
                    window_start=fetched.window.start.isoformat(),
                    window_end=fetched.window.end.isoformat(),
                )
            )

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    target = _resume_target(windows, resume)
    start_index = target[0] if target is not None else 0
    if start_index > 0:
        logger.debug(f"Impact Partner: resuming Actions from window {start_index}/{len(windows)}")

    for index in range(start_index, len(windows)):
        window = windows[index]
        if target is not None and index == target[0]:
            # Resume the exact bookmarked slice, which a 400 may have narrowed below this window.
            resumed_window = target[1]
            yield from _run(resumed_window, resume.page if resume and resume.page else 1)
            if resumed_window.end < window[1]:
                # A split leaves the rest of this window unfetched; get it before moving on.
                yield from _run(ActionsWindow(start=resumed_window.end, end=window[1]), 1)
        else:
            yield from _run(ActionsWindow(start=window[0], end=window[1]), 1)


def get_rows(
    account_sid: str,
    auth_token: str,
    endpoint: str,
    api_version: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ImpactPartnerResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = IMPACT_PARTNER_ENDPOINTS[endpoint]
    session = _get_session(account_sid, auth_token, api_version)

    if config.date_windowed:
        yield from _get_rows_windowed(
            session,
            account_sid,
            config,
            logger,
            should_use_incremental_field,
            db_incremental_field_last_value,
            resumable_source_manager,
        )
        return

    yield from _get_rows_simple(
        session,
        account_sid,
        config,
        logger,
        should_use_incremental_field,
        db_incremental_field_last_value,
        resumable_source_manager,
    )


def impact_partner_source(
    account_sid: str,
    auth_token: str,
    endpoint: str,
    api_version: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ImpactPartnerResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = IMPACT_PARTNER_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            account_sid=account_sid,
            auth_token=auth_token,
            endpoint=endpoint,
            api_version=api_version,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
