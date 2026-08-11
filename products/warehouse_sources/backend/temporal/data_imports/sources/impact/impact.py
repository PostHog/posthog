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
from products.warehouse_sources.backend.temporal.data_imports.sources.impact.settings import (
    IMPACT_API_VERSION_LEGACY,
    IMPACT_ENDPOINTS,
    IMPACT_VERSION_HEADER,
    MAX_LOOKBACK_DAYS,
    MAX_WINDOW_DAYS,
    ImpactEndpointConfig,
)

BASE_URL = "https://api.impact.com"

REQUEST_TIMEOUT_SECONDS = 60


@dataclasses.dataclass
class ImpactResumeConfig:
    # Simple (non-fan-out) endpoints: the last page fetched. Re-fetched on resume (merge dedupes).
    page: Optional[int] = None
    # Actions: the campaign currently being processed.
    campaign_id: Optional[int] = None
    # Actions: ISO start of the date window currently being processed.
    window_start: Optional[str] = None


def _get_session(account_sid: str, auth_token: str, api_version: str = IMPACT_API_VERSION_LEGACY) -> requests.Session:
    session = make_tracked_session(redact_values=(auth_token,))
    session.auth = HTTPBasicAuth(account_sid, auth_token)
    # Impact.com returns XML unless explicitly asked for JSON.
    session.headers["Accept"] = "application/json"
    # The legacy label sends no version header, so it keeps tracking the account's configured
    # default; a dated label pins the response shape via the header.
    if api_version != IMPACT_API_VERSION_LEGACY:
        session.headers[IMPACT_VERSION_HEADER] = api_version
    return session


def _fetch(
    session: requests.Session, account_sid: str, path: str, params: dict[str, Any], logger: FilteringBoundLogger
) -> Any:
    url = f"{BASE_URL}/Advertisers/{account_sid}{path}"
    response = session.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
    if not response.ok:
        logger.error(f"Impact API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()
    return response.json()


def validate_credentials(account_sid: str, auth_token: str, api_version: str = IMPACT_API_VERSION_LEGACY) -> bool:
    try:
        session = _get_session(account_sid, auth_token, api_version)
        response = session.get(
            f"{BASE_URL}/Advertisers/{account_sid}/Campaigns",
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


def _rows_from_response(config: ImpactEndpointConfig, data: Any) -> list[dict[str, Any]]:
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


def _discover_campaign_ids(session: requests.Session, account_sid: str, logger: FilteringBoundLogger) -> list[int]:
    """Return every campaign id on the account, sorted for deterministic fan-out order."""
    config = IMPACT_ENDPOINTS["Campaigns"]
    campaign_ids: set[int] = set()
    for _page, rows in _paginate_endpoint(session, account_sid, config, {}, logger):
        for row in rows:
            campaign_id = _safe_int(row.get("Id"))
            if campaign_id is not None:
                campaign_ids.add(campaign_id)
    return sorted(campaign_ids)


def _paginate_endpoint(
    session: requests.Session,
    account_sid: str,
    config: ImpactEndpointConfig,
    params: dict[str, Any],
    logger: FilteringBoundLogger,
    start_page: int = 1,
    path: Optional[str] = None,
) -> Iterator[tuple[int, list[dict[str, Any]]]]:
    """Yield (page_number, rows) from `start_page` to the last page (`@numpages`).

    `path` overrides `config.path` for endpoints whose campaign id lives in the URL (Contracts)."""
    request_path = path if path is not None else config.path
    page = start_page
    while True:
        page_params = {**params, "Page": page, "PageSize": config.page_size}
        data = _fetch(session, account_sid, request_path, page_params, logger)
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


def _resume_index(work_items: list[tuple[Any, int]], resume: Optional[ImpactResumeConfig]) -> int:
    """Find where to restart a (window, campaign_id) work list from a saved bookmark.

    Returns the index of the last-yielded item so it's re-processed (merge dedupes) and
    everything after it runs. Falls back to the start when there's no bookmark or it no longer
    matches (e.g. the campaign list changed between runs).
    """
    if resume is None or resume.campaign_id is None:
        return 0
    for index, (window, campaign_id) in enumerate(work_items):
        window_start = window[0].isoformat() if window is not None else None
        if campaign_id == resume.campaign_id and window_start == resume.window_start:
            return index
    return 0


def _get_rows_simple(
    session: requests.Session,
    account_sid: str,
    config: ImpactEndpointConfig,
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    resumable_source_manager: ResumableSourceManager[ImpactResumeConfig],
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
        resumable_source_manager.save_state(ImpactResumeConfig(page=page))


def _get_rows_fanout(
    session: requests.Session,
    account_sid: str,
    config: ImpactEndpointConfig,
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    resumable_source_manager: ResumableSourceManager[ImpactResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    """Fetch a campaign-scoped endpoint once per campaign (Actions, ActionUpdates, Contracts).

    Date-windowed endpoints (the action endpoints) are additionally walked in 44-day windows;
    Contracts has no such cap and runs a single pass per campaign."""
    campaign_ids = _discover_campaign_ids(session, account_sid, logger)
    if not campaign_ids:
        logger.warning(f"Impact: no campaigns found for account; nothing to sync for {config.name}")
        return

    windows: list[Optional[tuple[datetime, datetime]]]
    if config.date_windowed:
        windows = list(_windows_for_actions(should_use_incremental_field, db_incremental_field_last_value))
    else:
        windows = [None]

    # Windows OUTER, campaigns INNER so rows arrive in globally ascending date order across every
    # campaign — required for the `sort_mode="asc"` watermark to advance monotonically.
    work_items: list[tuple[Optional[tuple[datetime, datetime]], int]] = [
        (window, campaign_id) for window in windows for campaign_id in campaign_ids
    ]

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    start_index = _resume_index(work_items, resume)
    if start_index > 0:
        logger.debug(f"Impact: resuming {config.name} from item {start_index}/{len(work_items)}")

    for window, campaign_id in work_items[start_index:]:
        params: dict[str, Any] = {}
        if config.campaign_id_in_path:
            path: Optional[str] = config.path.format(campaign_id=campaign_id)
        else:
            path = None
            params["CampaignId"] = campaign_id
        if window is not None:
            assert config.incremental_start_param is not None
            assert config.incremental_end_param is not None
            params[config.incremental_start_param] = _format_datetime(window[0])
            params[config.incremental_end_param] = _format_datetime(window[1])

        for _page, rows in _paginate_endpoint(session, account_sid, config, params, logger, path=path):
            if rows:
                if config.campaign_id_in_path:
                    # Path-based fan-out doesn't echo the campaign id on each row; inject it so the
                    # composite primary key stays unique across campaigns.
                    for row in rows:
                        row.setdefault("CampaignId", campaign_id)
                yield rows
        # Save once the whole (window, campaign) item is drained. A crash re-fetches it from page
        # 1 on resume; merge dedupes the re-yielded rows.
        window_start = window[0].isoformat() if window is not None else None
        resumable_source_manager.save_state(ImpactResumeConfig(campaign_id=campaign_id, window_start=window_start))


def _get_rows_nested(
    session: requests.Session,
    account_sid: str,
    config: ImpactEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ImpactResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    """Flatten a nested array carried on a parent endpoint's rows into its own table.

    Reuses the parent endpoint's fetch (e.g. Invoices) and splits each nested array (LineItems,
    DetailedLineItems) into child rows tagged with a foreign key back to the parent."""
    nested = config.nested
    assert nested is not None
    parent_config = IMPACT_ENDPOINTS[nested.parent_endpoint]

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    start_page = resume.page if resume and resume.page else 1

    for page, parent_rows in _paginate_endpoint(session, account_sid, parent_config, {}, logger, start_page=start_page):
        child_rows: list[dict[str, Any]] = []
        for parent_row in parent_rows:
            items = parent_row.get(nested.array_key)
            if not isinstance(items, list):
                continue
            parent_id = parent_row.get(nested.parent_id_field)
            for line_number, item in enumerate(items, start=1):
                if not isinstance(item, dict):
                    continue
                child = dict(item)
                child[nested.fk_name] = parent_id
                child[nested.line_number_field] = line_number
                child_rows.append(child)
        if child_rows:
            yield child_rows
        # Save after yielding: a crash re-fetches this same page and merge dedupes it.
        resumable_source_manager.save_state(ImpactResumeConfig(page=page))


def get_rows(
    account_sid: str,
    auth_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ImpactResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    api_version: str = IMPACT_API_VERSION_LEGACY,
) -> Iterator[list[dict[str, Any]]]:
    config = IMPACT_ENDPOINTS[endpoint]
    session = _get_session(account_sid, auth_token, api_version)

    if config.nested is not None:
        yield from _get_rows_nested(session, account_sid, config, logger, resumable_source_manager)
        return

    if config.requires_campaign_fanout:
        yield from _get_rows_fanout(
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


def impact_source(
    account_sid: str,
    auth_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ImpactResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    api_version: str = IMPACT_API_VERSION_LEGACY,
) -> SourceResponse:
    config = IMPACT_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            account_sid=account_sid,
            auth_token=auth_token,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            api_version=api_version,
        ),
        primary_keys=config.primary_keys,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
