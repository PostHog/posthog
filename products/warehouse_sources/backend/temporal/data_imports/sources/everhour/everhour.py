import re
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.everhour.settings import (
    EVERHOUR_ENDPOINTS,
    EverhourEndpointConfig,
)

EVERHOUR_BASE_URL = "https://api.everhour.com"
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 5
# Defensive cap so a buggy/ignored offset param can't loop forever. 50k pages * 50 rows is far more
# than any real account holds; reaching it is logged as a warning.
MAX_PAGES_PER_URL = 50_000
# First sync lower bound for the /time-records date window. Everhour launched in 2015, so this
# captures effectively all history while still giving the API a concrete `from` (it otherwise
# defaults to returning only today's records).
EARLIEST_FROM_DATE = "2015-01-01"

# Matches the parent project id in a fan-out tasks URL: /projects/{project_id}/tasks
_PROJECT_ID_RE = re.compile(r"/projects/([^/?]+)/tasks")


class EverhourRetryableError(Exception):
    pass


@dataclasses.dataclass
class EverhourResumeConfig:
    # Base request URLs (with limit + from/to baked in, but no offset) not yet started. For fan-out
    # endpoints there's one per project; for top-level endpoints just the single list URL.
    remaining_urls: list[str]
    # The base URL currently being paginated, or None when finished.
    current_url: Optional[str]
    # Offset into ``current_url`` for the next page to fetch.
    current_offset: int = 0


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "X-Api-Key": api_key,
        "Accept": "application/json",
    }


def _make_session(api_key: str) -> requests.Session:
    """Tracked session for Everhour requests.

    `redact_values=(api_key,)` masks the credential everywhere it could surface in logged URLs
    or captured samples. `allow_redirects=False` keeps the static `X-Api-Key` header pinned to the
    validated `https://api.everhour.com` origin so a 30x can't replay it cross-origin.
    """
    return make_tracked_session(redact_values=(api_key,), allow_redirects=False)


def _with_query(path_or_url: str, params: dict[str, Any]) -> str:
    """Append query params to a path/URL that may already carry a query string."""
    clean = {key: value for key, value in params.items() if value is not None}
    base = path_or_url if path_or_url.startswith("http") else f"{EVERHOUR_BASE_URL}{path_or_url}"
    if not clean:
        return base
    separator = "&" if "?" in base else "?"
    return f"{base}{separator}{urlencode(clean)}"


def _format_date(value: Any) -> str:
    """Format an incremental cursor value as the YYYY-MM-DD Everhour expects."""
    if isinstance(value, datetime):
        return value.astimezone(UTC).date().isoformat() if value.tzinfo else value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    # Already a string cursor (e.g. "2026-03-04") — pass through.
    return str(value)


def _time_records_window(
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> dict[str, str]:
    """Build the from/to date window for /time-records.

    On the first sync (or full refresh) we span all history; on an incremental sync we floor `from`
    to the watermark's day. Re-querying the whole watermark day each sync is intentional — the boundary
    rows are re-pulled and deduped by primary key on merge, so no edits on that day are missed.
    """
    if should_use_incremental_field and db_incremental_field_last_value:
        from_date = _format_date(db_incremental_field_last_value)
    else:
        from_date = EARLIEST_FROM_DATE
    return {"from": from_date, "to": datetime.now(UTC).date().isoformat()}


@retry(
    retry=retry_if_exception_type((EverhourRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(MAX_RETRIES),
    wait=wait_exponential_jitter(initial=1, max=60),
    reraise=True,
)
def _fetch_page(
    url: str, headers: dict[str, str], logger: FilteringBoundLogger, session: requests.Session
) -> list[dict[str, Any]]:
    response = session.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

    # Everhour rate-limits at ~20 req / 10s per key and returns 429 with a Retry-After header;
    # exponential backoff is sufficient and avoids parsing the header here. 5xx is also transient.
    if response.status_code == 429 or response.status_code >= 500:
        raise EverhourRetryableError(f"Everhour API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Everhour API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    data = response.json()
    # Everhour list endpoints return a bare JSON array; anything else (an error envelope with a
    # 200, or a future API change) would otherwise be swallowed as an empty page and stop pagination.
    if not isinstance(data, list):
        logger.warning(f"Everhour: expected list response, got {type(data).__name__} for url={url}")
        return []
    return data


def _build_base_url(config: EverhourEndpointConfig, window: dict[str, str] | None) -> str:
    params: dict[str, Any] = {"limit": config.page_size}
    if window:
        params.update(window)
    return _with_query(config.path_template, params)


def _iter_all_items(
    base_url: str, page_size: int, headers: dict[str, str], logger: FilteringBoundLogger, session: requests.Session
) -> Iterator[dict[str, Any]]:
    """Fully paginate one base URL via limit/offset, yielding individual records (used for discovery)."""
    offset = 0
    for _ in range(MAX_PAGES_PER_URL):
        items = _fetch_page(_with_query(base_url, {"offset": offset}), headers, logger, session)
        yield from items
        if len(items) < page_size:
            return
        offset += page_size
    logger.warning(f"Everhour: hit max page cap while paginating {base_url}")


def _build_initial_urls(
    config: EverhourEndpointConfig,
    window: dict[str, str] | None,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    session: requests.Session,
) -> list[str]:
    """Resolve the set of base request URLs for an endpoint, fanning out over projects as needed."""
    if config.fan_out == "none":
        return [_build_base_url(config, window)]

    if config.fan_out == "project":
        projects_config = EVERHOUR_ENDPOINTS["projects"]
        projects_url = _build_base_url(projects_config, None)
        return [
            _with_query(config.path_template.format(project_id=project["id"]), {"limit": config.page_size})
            for project in _iter_all_items(projects_url, projects_config.page_size, headers, logger, session)
        ]

    raise ValueError(f"Unknown fan_out mode: {config.fan_out}")


def _parent_project_id(url: str) -> Optional[str]:
    match = _PROJECT_ID_RE.search(url)
    return match.group(1) if match else None


def validate_credentials(api_key: str) -> bool:
    """Confirm the API key is valid. /users/me needs only a genuine key, no extra permissions."""
    try:
        response = _make_session(api_key).get(
            f"{EVERHOUR_BASE_URL}/users/me",
            headers=_get_headers(api_key),
            timeout=10,
        )
        return response.status_code == 200
    except Exception:
        return False


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[EverhourResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = EVERHOUR_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)
    # One session for the whole run so pagination and fan-out reuse pooled connections.
    session = _make_session(api_key)

    window = (
        _time_records_window(should_use_incremental_field, db_incremental_field_last_value)
        if config.supports_date_window
        else None
    )

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume_config is not None:
        remaining = list(resume_config.remaining_urls)
        current = resume_config.current_url
        offset = resume_config.current_offset
        logger.debug(f"Everhour: resuming {endpoint} from url={current}, offset={offset}")
    else:
        remaining = _build_initial_urls(config, window, headers, logger, session)
        current = remaining.pop(0) if remaining else None
        offset = 0

    # The same id only repeats within a base URL when the API ignores `offset`; tracking ids per
    # URL lets us stop instead of looping forever on the first page.
    seen_ids: set[Any] = set()
    pages_on_current = 0

    while current is not None:
        items = _fetch_page(_with_query(current, {"offset": offset}), headers, logger, session)
        pages_on_current += 1

        new_items = [item for item in items if item["id"] not in seen_ids]
        seen_ids.update(item["id"] for item in new_items)

        if config.include_parent_id_as:
            parent_id = _parent_project_id(current)
            for item in new_items:
                item[config.include_parent_id_as] = parent_id

        # A full page of genuinely new rows means there may be more; a short page (or one that
        # surfaced no new ids, i.e. offset was ignored) ends this URL.
        would_continue = len(items) >= config.page_size and len(new_items) > 0
        if would_continue and pages_on_current >= MAX_PAGES_PER_URL:
            logger.warning(f"Everhour: hit max page cap while paginating {current}")
        has_more = would_continue and pages_on_current < MAX_PAGES_PER_URL

        if has_more:
            new_remaining = remaining
            new_current: Optional[str] = current
            new_offset = offset + config.page_size
        elif remaining:
            new_remaining = remaining[1:]
            new_current = remaining[0]
            new_offset = 0
        else:
            new_remaining = []
            new_current = None
            new_offset = 0

        if new_current != current:
            seen_ids = set()
            pages_on_current = 0

        if new_items:
            yield new_items

        # Save AFTER yielding (and only while there's more to fetch) so a crash re-yields the last
        # batch — merge dedupes on the primary key — rather than skipping it.
        if new_current is not None:
            resumable_source_manager.save_state(
                EverhourResumeConfig(remaining_urls=new_remaining, current_url=new_current, current_offset=new_offset)
            )

        remaining = new_remaining
        current = new_current
        offset = new_offset


def everhour_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[EverhourResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = EVERHOUR_ENDPOINTS[endpoint]

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
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format=config.partition_format if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # /time-records is returned in ascending date order; the reference endpoints are full refresh
        # so ordering is immaterial for them.
        sort_mode="asc",
    )
