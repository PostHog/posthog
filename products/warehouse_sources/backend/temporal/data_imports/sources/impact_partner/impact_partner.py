import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional

import requests
from requests.auth import HTTPBasicAuth
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.impact_partner.settings import (
    IMPACT_PARTNER_ENDPOINTS,
    MAX_LOOKBACK_DAYS,
    MAX_WINDOW_DAYS,
    ImpactPartnerEndpointConfig,
)

BASE_URL = "https://api.impact.com"

REQUEST_TIMEOUT_SECONDS = 60


@dataclasses.dataclass(frozen=True)
class ImpactPartnerResumeConfig:
    # The last page fetched. Re-fetched on resume (merge dedupes).
    page: Optional[int] = None
    # Actions: ISO start of the date window currently being processed.
    window_start: Optional[str] = None


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


def _resume_window_index(
    windows: list[tuple[datetime, datetime]], resume: Optional[ImpactPartnerResumeConfig]
) -> Optional[int]:
    """Find which date window a saved bookmark points at.

    Returns None when there's no bookmark or it no longer matches (window boundaries derive
    from the current time, so they shift between runs), in which case the caller starts over
    (merge dedupes the re-yielded rows).
    """
    if resume is None or resume.window_start is None:
        return None
    for index, window in enumerate(windows):
        if window[0].isoformat() == resume.window_start:
            return index
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

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    resume_index = _resume_window_index(windows, resume)
    start_index = resume_index if resume_index is not None else 0
    if start_index > 0:
        logger.debug(f"Impact Partner: resuming Actions from window {start_index}/{len(windows)}")

    for index in range(start_index, len(windows)):
        window = windows[index]
        # Resume the bookmarked window at its saved page; every other window starts at page 1.
        start_page = 1
        if resume is not None and index == resume_index and resume.page:
            start_page = resume.page
        params: dict[str, Any] = {
            start_param: _format_datetime(window[0]),
            end_param: _format_datetime(window[1]),
        }
        for page, rows in _paginate_endpoint(session, account_sid, config, params, logger, start_page=start_page):
            if rows:
                yield rows
            # Save after yielding: a crash re-fetches this same page and merge dedupes it.
            resumable_source_manager.save_state(
                ImpactPartnerResumeConfig(page=page, window_start=window[0].isoformat())
            )


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
