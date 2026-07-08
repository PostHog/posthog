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
from products.warehouse_sources.backend.temporal.data_imports.sources.tremendous.settings import TREMENDOUS_ENDPOINTS

# Sandbox and production are separate hosts with separate API keys.
TREMENDOUS_BASE_URLS: dict[str, str] = {
    "production": "https://www.tremendous.com/api/v2",
    "sandbox": "https://testflight.tremendous.com/api/v2",
}
REQUEST_TIMEOUT_SECONDS = 60
# Cheap authenticated probe used to confirm an API key is genuine. The key is organization-wide, so
# one probe validates access to every list endpoint.
DEFAULT_PROBE_PATH = "/organizations"


class TremendousRetryableError(Exception):
    pass


@dataclasses.dataclass
class TremendousResumeConfig:
    # Number of rows already yielded for the current offset/limit page chain. Tremendous paginates
    # by creation date DESC, so rows created mid-sync shift the window and can re-appear on a later
    # page — merge dedupes them on `id`; rows are never skipped.
    offset: int = 0


def _headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}


def base_url_for_environment(environment: str) -> str:
    return TREMENDOUS_BASE_URLS.get(environment, TREMENDOUS_BASE_URLS["production"])


def _to_iso_datetime(value: Any) -> Optional[str]:
    """Coerce an incremental cursor value to the ISO 8601 string `created_at[gte]` expects."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return dt.isoformat()
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).isoformat()
    if isinstance(value, str) and value:
        return value
    return None


@retry(
    retry=retry_if_exception_type((TremendousRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    url: str,
    data_key: str,
    params: dict[str, Any],
    logger: FilteringBoundLogger,
) -> list[dict[str, Any]]:
    response = session.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)

    # Tremendous rate-limits per organization; 429 and transient 5xx back off exponentially.
    if response.status_code == 429 or response.status_code >= 500:
        raise TremendousRetryableError(f"Tremendous API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Tremendous API error: status={response.status_code}, body={response.text[:200]!r}, url={url}")
        response.raise_for_status()

    data = response.json()
    # List responses wrap records under the plural resource name, e.g. {"orders": [...], "total_count": N}.
    if not isinstance(data, dict) or not isinstance(data.get(data_key), list):
        raise TremendousRetryableError(f"Tremendous returned an unexpected payload for {url}: {type(data).__name__}")

    return data[data_key]


def get_rows(
    api_key: str,
    environment: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[TremendousResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = TREMENDOUS_ENDPOINTS[endpoint]
    session = make_tracked_session(headers=_headers(api_key), redact_values=(api_key,))
    url = f"{base_url_for_environment(environment)}{config.path}"

    if not config.paginated:
        # Members, campaigns, products, and funding sources return the whole collection in one
        # response — no offset/limit params, so there is no resume state to track.
        items = _fetch_page(session, url, config.data_key, {}, logger)
        if items:
            yield items
        return

    base_params: dict[str, Any] = {"limit": config.page_size}
    # `created_at[gte]` is inclusive, so the watermark row itself is re-fetched — merge dedupes it
    # on the primary key. The filter applies on every page, so pagination stays bounded to the window.
    incremental_cursor = _to_iso_datetime(db_incremental_field_last_value) if should_use_incremental_field else None
    if incremental_cursor is not None:
        base_params["created_at[gte]"] = incremental_cursor

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    offset = resume.offset if resume else 0
    if resume and resume.offset:
        logger.debug(f"Tremendous: resuming {endpoint} from offset {offset}")

    while True:
        items = _fetch_page(session, url, config.data_key, {**base_params, "offset": offset}, logger)
        if items:
            yield items

        # A page shorter than the limit (or empty) marks the end of the collection.
        if len(items) < config.page_size:
            break

        offset += len(items)
        # Save AFTER yielding so a crash re-fetches from the next page (already-yielded pages are
        # persisted); merge dedupes any re-pulled rows on the primary key.
        resumable_source_manager.save_state(TremendousResumeConfig(offset=offset))


def tremendous_source(
    api_key: str,
    environment: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[TremendousResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> SourceResponse:
    config = TREMENDOUS_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            environment=environment,
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
        # Tremendous lists are ordered by creation date DESC and expose no sort param, so the
        # incremental watermark is finalized at the end of a completed sync.
        sort_mode="desc",
    )


def check_access(api_key: str, environment: str, path: str = DEFAULT_PROBE_PATH) -> tuple[int, Optional[str]]:
    """Probe a single endpoint to validate the API key.

    Returns ``(status, message)``: ``200`` reachable, ``401``/``403`` auth failure, ``0`` for a
    connection problem, other HTTP status otherwise.
    """
    session = make_tracked_session(headers=_headers(api_key), redact_values=(api_key,))
    try:
        response = session.get(f"{base_url_for_environment(environment)}{path}", timeout=15)
    except Exception as e:
        return 0, f"Could not connect to Tremendous: {e}"

    if response.status_code in (401, 403):
        return response.status_code, None

    if not response.ok:
        return response.status_code, f"Tremendous returned HTTP {response.status_code}"

    return 200, None


def validate_credentials(api_key: str, environment: str) -> tuple[bool, str | None]:
    status, message = check_access(api_key, environment)
    if status == 200:
        return True, None
    if status in (401, 403):
        return False, "Invalid Tremendous API key (check that it matches the selected environment)"
    return False, message or "Could not validate Tremendous API key"
