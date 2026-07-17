import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.appfigures.settings import (
    APPFIGURES_ENDPOINTS,
    AppfiguresEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

APPFIGURES_BASE_URL = "https://api.appfigures.com/v2"

# Report endpoints (group_by=dates) have no "fetch everything" mode that's safe to stream — omitting
# the window returns the entire account history in one un-paginated response, and daily granularity is
# capped at 30 days per request. So the first sync backfills this many days, then incremental syncs
# advance from the stored date watermark.
REPORT_BACKFILL_DAYS = 365


class AppfiguresRetryableError(Exception):
    pass


@dataclasses.dataclass
class AppfiguresResumeConfig:
    # "paged" endpoints (reviews): the next page number to fetch (1-based).
    next_page: int | None = None
    # "report" endpoints: the next date window's start (yyyy-mm-dd) to fetch.
    window_start: str | None = None


def _headers(token: str) -> dict[str, str]:
    # Personal Access Tokens and OAuth 2.0 tokens both ride the standard bearer header; the PAT also
    # carries the API client identity, so no separate client-key header is needed.
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}


def _to_date_str(value: Any) -> str | None:
    """Format a datetime/date/ISO-string incremental value as the yyyy-mm-dd Appfigures expects."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(UTC).date().isoformat() if value.tzinfo else value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    # Already a string — take the date portion (handles "2024-01-02T03:04:05" and "2024-01-02").
    text = str(value)[:10]
    try:
        date.fromisoformat(text)
    except ValueError as e:
        # Surface a descriptive error here rather than letting the partial fragment blow up deep in
        # _iter_report's date.fromisoformat call.
        raise ValueError(f"Could not derive a yyyy-mm-dd date from incremental value {value!r}") from e
    return text


@retry(
    retry=retry_if_exception_type((AppfiguresRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch(
    session: requests.Session,
    url: str,
    params: dict[str, Any],
    logger: FilteringBoundLogger,
) -> dict[str, Any]:
    response = session.get(url, params=params, timeout=60)

    # Quota is a monthly credit model rather than per-second, so 429 is rare, but treat it and
    # transient 5xx as retryable. Everything else (including 401/403) raises for the caller.
    if response.status_code == 429 or response.status_code >= 500:
        raise AppfiguresRetryableError(f"Appfigures API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Appfigures API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def check_credentials(token: str, path: str = "/products/mine") -> int | None:
    """Probe an endpoint and return its HTTP status, or None on a network failure.

    The source layer maps the status: 200 = valid, 401 = bad token, 403 = valid token missing the
    scope for that endpoint.
    """
    try:
        response = make_tracked_session(headers=_headers(token), redact_values=(token,)).get(
            f"{APPFIGURES_BASE_URL}{path}", params={"count": 1}, timeout=10
        )
        return response.status_code
    except Exception:
        return None


def _iter_object(
    session: requests.Session,
    config: AppfiguresEndpointConfig,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    """Single-request endpoints whose body is a JSON object keyed by id (e.g. /products/mine)."""
    data = _fetch(session, f"{APPFIGURES_BASE_URL}{config.path}", {}, logger)
    rows = list(data.values()) if isinstance(data, dict) else data
    if rows:
        yield rows


def _iter_paged(
    session: requests.Session,
    config: AppfiguresEndpointConfig,
    logger: FilteringBoundLogger,
    manager: ResumableSourceManager[AppfiguresResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    """Page/count paginated endpoints with a flat list under `data_key` (e.g. /reviews)."""
    resume = manager.load_state() if manager.can_resume() else None
    page = resume.next_page if resume and resume.next_page else 1

    params: dict[str, Any] = {"count": config.page_size, "page": page}
    if config.sort:
        params["sort"] = config.sort
    if should_use_incremental_field and config.start_param:
        start = _to_date_str(db_incremental_field_last_value)
        if start:
            params[config.start_param] = start

    url = f"{APPFIGURES_BASE_URL}{config.path}"
    while True:
        data = _fetch(session, url, params, logger)
        rows = data.get(config.data_key, []) if config.data_key else []
        total_pages = data.get("pages", 1) or 1
        this_page = data.get("this_page", page) or page

        if rows:
            yield rows

        if not rows or this_page >= total_pages:
            break

        page += 1
        params["page"] = page
        # Save AFTER yielding so a crash re-fetches the page we were on rather than skipping it;
        # merge dedupes the re-pulled rows on the primary key.
        manager.save_state(AppfiguresResumeConfig(next_page=page))


def _flatten_report(data: Any) -> list[dict[str, Any]]:
    """Turn a group_by=dates report body ({"2024-01-01": {..metrics..}, ...}) into dated rows.

    Only dict-valued entries are kept (defensive against any non-date envelope keys), and `date` is
    injected so the row is uniquely keyed and partitionable. Sorted ascending so the watermark advances.
    """
    if not isinstance(data, dict):
        return []
    rows: list[dict[str, Any]] = []
    for day in sorted(data.keys()):
        metrics = data[day]
        if isinstance(metrics, dict):
            rows.append({"date": day, **metrics})
    return rows


def _iter_report(
    session: requests.Session,
    config: AppfiguresEndpointConfig,
    logger: FilteringBoundLogger,
    manager: ResumableSourceManager[AppfiguresResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    """Reports/* endpoints walked in fixed date windows (daily granularity caps at 30 days/request)."""
    today = datetime.now(UTC).date()
    window_days = config.window_days or 30

    resume = manager.load_state() if manager.can_resume() else None
    if resume and resume.window_start:
        window_start = date.fromisoformat(resume.window_start)
    elif should_use_incremental_field and db_incremental_field_last_value:
        last = _to_date_str(db_incremental_field_last_value)
        window_start = date.fromisoformat(last) if last else today - timedelta(days=REPORT_BACKFILL_DAYS)
    else:
        window_start = today - timedelta(days=REPORT_BACKFILL_DAYS)

    url = f"{APPFIGURES_BASE_URL}{config.path}"
    while window_start <= today:
        window_end = min(window_start + timedelta(days=window_days - 1), today)
        params: dict[str, Any] = {
            "group_by": config.group_by,
            "granularity": config.granularity,
            "start_date": window_start.isoformat(),
            "end_date": window_end.isoformat(),
        }
        rows = _flatten_report(_fetch(session, url, params, logger))
        if rows:
            yield rows

        if window_end >= today:
            break

        window_start = window_end + timedelta(days=1)
        # Save AFTER yielding the window so a crash re-fetches it rather than skipping; merge dedupes
        # the re-pulled dates on the `date` primary key.
        manager.save_state(AppfiguresResumeConfig(window_start=window_start.isoformat()))


def get_rows(
    token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[AppfiguresResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = APPFIGURES_ENDPOINTS[endpoint]
    session = make_tracked_session(headers=_headers(token), redact_values=(token,))

    if config.kind == "object":
        yield from _iter_object(session, config, logger)
    elif config.kind == "paged":
        yield from _iter_paged(
            session,
            config,
            logger,
            resumable_source_manager,
            should_use_incremental_field,
            db_incremental_field_last_value,
        )
    else:  # "report"
        yield from _iter_report(
            session,
            config,
            logger,
            resumable_source_manager,
            should_use_incremental_field,
            db_incremental_field_last_value,
        )


def appfigures_source(
    token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[AppfiguresResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = APPFIGURES_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            token=token,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # Reviews are paged ascending by `date`; reports are emitted oldest-window-first. Both arrive
        # in ascending order so the incremental watermark checkpoints correctly.
        sort_mode="asc",
    )
