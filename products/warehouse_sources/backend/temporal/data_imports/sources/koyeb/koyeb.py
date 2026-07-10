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
from products.warehouse_sources.backend.temporal.data_imports.sources.koyeb.settings import (
    KOYEB_ENDPOINTS,
    KoyebEndpointConfig,
)

# The Swagger host is app.koyeb.com; the api.prod.koyeb.com alias does not route the /v1 paths.
KOYEB_BASE_URL = "https://app.koyeb.com"

# Koyeb documents no published rate limit and caps list pages at a generous size; 100 keeps each
# request cheap while bounding the number of round trips.
DEFAULT_PAGE_SIZE = 100


class KoyebRetryableError(Exception):
    pass


@dataclasses.dataclass
class KoyebResumeConfig:
    # Offset of the next page to fetch. Every Koyeb list endpoint paginates on limit + offset, so a
    # single integer offset is enough to resume any endpoint after a heartbeat timeout.
    offset: int = 0


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }


def _format_incremental_value(value: Any) -> str:
    """Format an incremental cursor value as an RFC 3339 datetime for Koyeb's time-window params."""
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return aware.astimezone(UTC).isoformat()
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).isoformat()
    return str(value)


def _clamp_future_value_to_now(value: Any) -> Any:
    """Cap a future datetime/date cursor at now.

    The watermark tracks the max value seen for the endpoint's cursor field. A future-dated record
    would advance it past now, and every later sync would ask for rows newer than the future value —
    a no-op that risks wedging the sync if the API rejects a future bound. Capping keeps the request
    meaningful and lets the sync self-heal.
    """
    now = datetime.now(UTC)
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return now if aware > now else value
    if isinstance(value, date):
        return now.date() if value > now.date() else value
    return value


def _build_params(
    config: KoyebEndpointConfig,
    offset: int,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> dict[str, Any]:
    params: dict[str, Any] = {"limit": DEFAULT_PAGE_SIZE, "offset": offset}

    if config.supports_incremental and config.time_window_param and should_use_incremental_field:
        # Ascending order so the pipeline's watermark advances monotonically (SourceResponse.sort_mode
        # is "asc" for these endpoints). The server-side lower bound applies to the whole result set,
        # so offset pagination walks within the filtered window and terminates naturally.
        params["order"] = "asc"
        if db_incremental_field_last_value:
            clamped = _clamp_future_value_to_now(db_incremental_field_last_value)
            params[config.time_window_param] = _format_incremental_value(clamped)

    return params


def _build_url(path: str, params: dict[str, Any]) -> str:
    return f"{KOYEB_BASE_URL}{path}?{urlencode(params)}"


@retry(
    retry=retry_if_exception_type(
        (
            KoyebRetryableError,
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

    if response.status_code == 429 or response.status_code >= 500:
        raise KoyebRetryableError(f"Koyeb API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Koyeb API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def _has_more(page: dict, data_key: str, items: list[dict]) -> bool:
    """Whether another page exists.

    Some Koyeb replies carry an explicit ``has_next`` flag; others only carry ``count``. When neither
    is authoritative we fall back to the page-size heuristic (a short page is the last one), which is
    correct for every offset-paginated endpoint regardless of which envelope fields it returns.
    """
    if "has_next" in page:
        return bool(page["has_next"])
    return len(items) >= DEFAULT_PAGE_SIZE


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[KoyebResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict]]:
    config = KOYEB_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)
    # One session reused across pages so urllib3 keeps the connection alive instead of re-handshaking.
    session = make_tracked_session()

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    offset = resume.offset if resume is not None else 0

    while True:
        params = _build_params(config, offset, should_use_incremental_field, db_incremental_field_last_value)
        url = _build_url(config.path, params)
        page = _fetch_page(session, url, headers, logger)

        items = page.get(config.data_key) or []
        if not isinstance(items, list):
            logger.warning(f"Koyeb: unexpected response shape for {endpoint}, expected list under '{config.data_key}'")
            break

        if items:
            yield items

        if not _has_more(page, config.data_key, items):
            break

        offset += DEFAULT_PAGE_SIZE
        # Save AFTER yielding so a crash resumes at the next page. The just-yielded page's rows are
        # already handed to the pipeline; merge dedupes on the primary key if any are re-read.
        resumable_source_manager.save_state(KoyebResumeConfig(offset=offset))


def koyeb_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[KoyebResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = KOYEB_ENDPOINTS[endpoint]

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
        # Incremental endpoints are requested with order=asc; full-refresh endpoints are read in the
        # API's natural offset order. Either way rows arrive oldest-first for the incremental ones,
        # which is what the pipeline's watermark checkpointing assumes.
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    """Probe a cheap authenticated endpoint. 401 => bad token; 403 => valid token, missing scope."""
    url = _build_url("/v1/apps", {"limit": 1})
    try:
        response = make_tracked_session().get(url, headers=_get_headers(api_key), timeout=10)
    except requests.exceptions.RequestException as e:
        return False, str(e)

    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return False, "Invalid Koyeb API token"
    if response.status_code == 403:
        return False, "Your Koyeb API token does not have permission to access this data"

    try:
        message = response.json().get("message", response.text)
    except (ValueError, AttributeError):
        message = response.text
    return False, message or f"Koyeb API returned status {response.status_code}"
