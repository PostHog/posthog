import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.openrouter.settings import (
    ACTIVITY_RETENTION_DAYS,
    OPENROUTER_ENDPOINTS,
    OpenRouterEndpointConfig,
)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
REQUEST_TIMEOUT = 60
MAX_OFFSET_PAGES = 10_000


class OpenRouterRetryableError(Exception):
    pass


@dataclasses.dataclass
class OpenRouterResumeConfig:
    # Offset already fetched for offset-paginated endpoints (api_keys/organization_members/workspaces).
    offset: int | None = None
    # Last fully-synced UTC day (YYYY-MM-DD) for the /activity day-by-day pull.
    date: str | None = None


def _headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}


def _build_url(path: str, params: Optional[dict[str, Any]] = None) -> str:
    url = f"{OPENROUTER_BASE_URL}{path}"
    if params:
        url = f"{url}?{urlencode(params)}"
    return url


@retry(
    retry=retry_if_exception_type(
        (
            OpenRouterRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch(session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger) -> dict:
    response = session.get(url, headers=headers, timeout=REQUEST_TIMEOUT)

    if response.status_code == 429 or response.status_code >= 500:
        raise OpenRouterRetryableError(f"OpenRouter API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        # Don't log the raw response body: several endpoints (api_keys/organization_members/workspaces)
        # return sensitive management data and upstream error bodies can echo request context.
        logger.error(f"OpenRouter API error: status={response.status_code}, url={url}")
        response.raise_for_status()

    return response.json()


def get_key_info(api_key: str) -> dict[str, Any] | None:
    """Return the current key's metadata from GET /key, or None if the key is invalid.

    The response carries `is_management_key`, which tells us whether the management endpoints
    (activity/api_keys/credits/organization_members/workspaces) will be reachable — a regular
    inference key can only read the public models/providers catalogs.
    """
    try:
        response = make_tracked_session(redact_values=(api_key,)).get(
            _build_url("/key"), headers=_headers(api_key), timeout=10
        )
        if response.status_code == 200:
            data = response.json().get("data")
            return data if isinstance(data, dict) else {}
        return None
    except Exception:
        return None


def validate_credentials(api_key: str) -> bool:
    return get_key_info(api_key) is not None


def _to_date(value: Any) -> date | None:
    """Coerce an incremental cursor / resume bookmark into a UTC date."""
    if isinstance(value, datetime):
        return value.astimezone(UTC).date() if value.tzinfo else value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except ValueError:
            try:
                return date.fromisoformat(value[:10])
            except ValueError:
                return None
    return None


def _activity_days(should_use_incremental_field: bool, db_incremental_field_last_value: Any) -> Iterator[date]:
    """Yield each completed UTC day to pull from /activity, oldest first.

    OpenRouter only retains the last 30 completed UTC days, so the window is clamped to that regardless
    of the watermark. On an incremental sync we re-fetch the watermark day itself (it may have been
    partial when first synced); merge dedupes the re-pulled rows on the primary key.
    """
    yesterday = datetime.now(UTC).date() - timedelta(days=1)
    start = yesterday - timedelta(days=ACTIVITY_RETENTION_DAYS - 1)

    if should_use_incremental_field and db_incremental_field_last_value is not None:
        watermark = _to_date(db_incremental_field_last_value)
        if watermark is not None and watermark > start:
            start = watermark

    day = start
    while day <= yesterday:
        yield day
        day += timedelta(days=1)


def _get_activity_rows(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[OpenRouterResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    resume_from = _to_date(resume.date) if resume is not None and resume.date else None

    for day in _activity_days(should_use_incremental_field, db_incremental_field_last_value):
        # Skip days a crashed prior attempt already completed. The window is regenerated from the
        # watermark on resume, so this is what advances us past the point of the crash.
        if resume_from is not None and day <= resume_from:
            continue

        data = _fetch(session, _build_url("/activity", {"date": day.isoformat()}), headers, logger)
        rows = data.get("data") or []
        if rows:
            yield rows

        # Save AFTER yielding so a crash re-yields the last day rather than skipping it.
        resumable_source_manager.save_state(OpenRouterResumeConfig(date=day.isoformat()))


def _get_offset_rows(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[OpenRouterResumeConfig],
    config: OpenRouterEndpointConfig,
) -> Iterator[list[dict[str, Any]]]:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    offset = resume.offset if resume is not None and resume.offset else 0

    # Hard cap as a runaway guard in case an endpoint ignores `offset` and re-serves the same page.
    for _ in range(MAX_OFFSET_PAGES):
        params: dict[str, Any] = {"offset": offset}
        if config.pagination == "offset_limit":
            params["limit"] = config.page_size

        data = _fetch(session, _build_url(config.path, params), headers, logger)
        rows = data.get("data") or []
        if not rows:
            break

        yield rows

        # When we set the page size ourselves (`limit`), a short page is the last page. For the
        # offset-only endpoints we don't know the server's page size, so we keep going until an
        # empty page instead of guessing it.
        if config.pagination == "offset_limit" and len(rows) < config.page_size:
            break

        offset += len(rows)
        # Save AFTER yielding so a crash re-yields the last page (merge dedupes on the primary key).
        resumable_source_manager.save_state(OpenRouterResumeConfig(offset=offset))
    else:
        logger.warning(f"OpenRouter: hit the {MAX_OFFSET_PAGES}-page cap for {config.name}; stopping pagination")


def _get_single_rows(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    config: OpenRouterEndpointConfig,
) -> Iterator[list[dict[str, Any]]]:
    data = _fetch(session, _build_url(config.path), headers, logger)

    if config.is_singleton:
        obj = data.get("data")
        if isinstance(obj, dict) and obj:
            yield [obj]
        return

    rows = data.get("data") or []
    if rows:
        yield rows


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[OpenRouterResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = OPENROUTER_ENDPOINTS[endpoint]
    headers = _headers(api_key)
    session = make_tracked_session(redact_values=(api_key,))

    if config.daily_activity:
        yield from _get_activity_rows(
            session,
            headers,
            logger,
            resumable_source_manager,
            should_use_incremental_field,
            db_incremental_field_last_value,
        )
    elif config.pagination is not None:
        yield from _get_offset_rows(session, headers, logger, resumable_source_manager, config)
    else:
        yield from _get_single_rows(session, headers, logger, config)


def openrouter_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[OpenRouterResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = OPENROUTER_ENDPOINTS[endpoint]

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
        # /activity yields days oldest-first and offset pages advance forward, so the watermark
        # checkpoints safely after each batch.
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
