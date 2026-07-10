import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from dateutil import parser as dateutil_parser
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.trigger_dev.settings import (
    TRIGGER_DEV_ENDPOINTS,
    TriggerDevEndpointConfig,
)

TRIGGER_DEV_DEFAULT_BASE_URL = "https://api.trigger.dev"


class TriggerDevRetryableError(Exception):
    pass


@dataclasses.dataclass
class TriggerDevResumeConfig:
    # The page[after] cursor used to FETCH the page we last yielded. `None` means the first page.
    # We checkpoint the current page's cursor (not the next one) so a crash re-fetches and re-yields
    # the last page rather than skipping it; merge dedupes the re-pulled rows on the primary key.
    after: str | None = None


def resolve_base_url(base_url: str | None) -> str:
    """Cloud users leave this blank (api.trigger.dev); self-hosters point it at their instance."""
    resolved = (base_url or "").strip().rstrip("/")
    return resolved or TRIGGER_DEV_DEFAULT_BASE_URL


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }


def _format_incremental_value(value: Any) -> str:
    """Format an incremental cursor value as an ISO 8601 string for the createdAt filter."""
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return aware.isoformat()
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).isoformat()
    return str(value)


def _as_utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def _is_older_than_cutoff(value: Any, cutoff: datetime) -> bool:
    """True when `value` (an ISO 8601 string or datetime) is at/older than `cutoff`."""
    if value is None:
        return False
    if isinstance(value, str):
        try:
            parsed = dateutil_parser.parse(value)
        except (ValueError, TypeError, OverflowError):
            return False
    elif isinstance(value, datetime):
        parsed = value
    else:
        return False
    return _as_utc(parsed) <= _as_utc(cutoff)


def _should_stop_desc(items: list[dict[str, Any]], incremental_field: str | None, cutoff: datetime | None) -> bool:
    """Desc incremental can stop the moment a page contains a row at/older than the cutoff.

    The runs endpoint applies the createdAt filter only on the first (uncursored) request; later
    cursor pages walk back through history unbounded, so the paginator must stop client-side once an
    entire page predates the watermark. Without this, every incremental sync would re-walk all
    history down to the first run.
    """
    if not incremental_field or cutoff is None or not items:
        return False
    return any(_is_older_than_cutoff(item.get(incremental_field), cutoff) for item in items if item)


@retry(
    retry=retry_if_exception_type(
        (
            TriggerDevRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger) -> dict:
    response = session.get(url, headers=headers, timeout=60)

    # Trigger.dev rate-limits per API key with a token bucket and standard x-ratelimit-* headers;
    # back off and retry on 429 and transient 5xx.
    if response.status_code == 429 or response.status_code >= 500:
        raise TriggerDevRetryableError(f"Trigger.dev API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Trigger.dev API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def _build_url(base_url: str, path: str, params: dict[str, Any]) -> str:
    if not params:
        return f"{base_url}{path}"
    return f"{base_url}{path}?{urlencode(params)}"


def validate_credentials(api_key: str, base_url: str) -> tuple[bool, str | None]:
    """Probe the token by listing one page of runs. 200 => valid; 401/403 => bad token."""
    # page[size] minimum is 10; the smallest cheap probe the runs endpoint allows.
    url = _build_url(base_url, TRIGGER_DEV_ENDPOINTS["runs"].path, {"page[size]": 10})
    try:
        response = make_tracked_session().get(url, headers=_get_headers(api_key), timeout=10)
    except requests.exceptions.RequestException as e:
        return False, str(e)

    if response.status_code == 200:
        return True, None
    if response.status_code in (401, 403):
        return False, "Invalid Trigger.dev API key. Copy the secret key for the environment you want to sync."
    return False, f"Trigger.dev returned an unexpected response: {response.status_code}"


def _iter_cursor_pages(
    session: requests.Session,
    base_url: str,
    headers: dict[str, str],
    config: TriggerDevEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[TriggerDevResumeConfig],
    incremental_field: str | None,
    cutoff: datetime | None,
) -> Iterator[list[dict[str, Any]]]:
    """Walk the runs endpoint newest-first via page[after], yielding one list of rows per page."""
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    after: str | None = resume.after if resume else None
    formatted_cutoff = _format_incremental_value(cutoff) if cutoff is not None else None

    while True:
        params: dict[str, Any] = {"page[size]": config.page_size}
        if after is None:
            # The createdAt filter is only sent on the first (uncursored) request. Mixing a time
            # filter with the cursor is unverified against the live API (no credentials at build
            # time), so we scope it to page one and bound the rest client-side via _should_stop_desc.
            if formatted_cutoff is not None:
                params["filter[createdAt][from]"] = formatted_cutoff
        else:
            params["page[after]"] = after

        url = _build_url(base_url, config.path, params)
        data = _fetch_page(session, url, headers, logger)

        items = data.get("data", []) or []
        next_after = (data.get("pagination", {}) or {}).get("next")
        stop = _should_stop_desc(items, incremental_field, cutoff)

        yield items
        # Checkpoint the CURRENT page's cursor after yielding, so a crash re-fetches this page.
        resumable_source_manager.save_state(TriggerDevResumeConfig(after=after))

        if stop or not next_after:
            break
        after = next_after


def _iter_classic_pages(
    session: requests.Session,
    base_url: str,
    headers: dict[str, str],
    config: TriggerDevEndpointConfig,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    """Walk a classic page/perPage endpoint (schedules, queues), yielding one list of rows per page.

    These are small full-refresh tables, so we don't checkpoint resume state: a worker restart
    simply re-reads from page one.
    """
    page = 1
    while True:
        url = _build_url(base_url, config.path, {"page": page, "perPage": config.page_size})
        data = _fetch_page(session, url, headers, logger)

        items = data.get("data", []) or []
        yield items

        pagination = data.get("pagination", {}) or {}
        total_pages = pagination.get("totalPages")
        if not items:
            break
        if total_pages is not None and page >= total_pages:
            break
        page += 1


def get_rows(
    api_key: str,
    base_url: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[TriggerDevResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[list[dict[str, Any]]]:
    config = TRIGGER_DEV_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)
    session = make_tracked_session()

    if config.pagination == "cursor":
        cutoff: datetime | None = None
        if should_use_incremental_field and db_incremental_field_last_value is not None:
            value = db_incremental_field_last_value
            if not isinstance(value, datetime):
                # The framework hands us a datetime for DateTime incremental fields; guard anyway so a
                # stringified watermark still bounds the walk rather than crashing.
                try:
                    value = dateutil_parser.parse(str(value))
                except (ValueError, TypeError, OverflowError):
                    value = None
            if isinstance(value, datetime):
                cutoff = _as_utc(value) - (config.incremental_lookback or timedelta(0))
        yield from _iter_cursor_pages(
            session,
            base_url,
            headers,
            config,
            logger,
            resumable_source_manager,
            incremental_field or config.default_incremental_field,
            cutoff,
        )
        return

    yield from _iter_classic_pages(session, base_url, headers, config, logger)


def trigger_dev_source(
    api_key: str,
    base_url: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[TriggerDevResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    endpoint_config = TRIGGER_DEV_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            base_url=base_url,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        ),
        primary_keys=endpoint_config.primary_keys,
        # Runs arrive newest-first; the pipeline must know so it defers the incremental watermark
        # correctly. Classic full-refresh endpoints keep the default asc.
        sort_mode=endpoint_config.sort_mode,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )
