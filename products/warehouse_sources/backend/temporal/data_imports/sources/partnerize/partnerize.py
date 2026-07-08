import base64
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional

import requests
from dateutil import parser as dateutil_parser
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.partnerize.settings import (
    PARTNERIZE_ENDPOINTS,
    PartnerizeEndpointConfig,
)

PARTNERIZE_BASE_URL = "https://api.partnerize.com"
# The report endpoints page at a fixed server-side size of 300 rows (echoed in the response's
# `limit` field) with no documented way to override it; we read the echoed value defensively.
REPORT_PAGE_LIMIT = 300
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 5
# start_date is a required parameter on the report endpoints, so full-refresh syncs use a fixed
# floor that predates the platform (Performance Horizon, now Partnerize, launched in 2010).
DEFAULT_START_DATE = "2010-01-01T00:00:00Z"


class PartnerizeRetryableError(Exception):
    pass


@dataclasses.dataclass
class PartnerizeResumeConfig:
    # Report endpoints resume from the row offset within the current date window; the window
    # itself is recomputed deterministically from the job's incremental inputs.
    offset: int | None = None
    # List endpoints resume from the hypermedia next-page URL.
    next_url: str | None = None


def _headers(application_key: str, user_api_key: str) -> dict[str, str]:
    # Partnerize uses HTTP Basic auth with the user application key as the username and the user
    # API key as the password.
    token = base64.b64encode(f"{application_key}:{user_api_key}".encode("ascii")).decode("ascii")
    return {"Authorization": f"Basic {token}", "Accept": "application/json"}


def _format_start_date(value: Any) -> str:
    """Coerce an incremental watermark to the ISO-8601 format the report endpoints document."""
    if isinstance(value, datetime):
        dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return f"{value.isoformat()}T00:00:00Z"
    if isinstance(value, str) and value:
        # Watermarks read back from the warehouse arrive as "YYYY-MM-DD HH:MM:SS" strings.
        try:
            return _format_start_date(dateutil_parser.parse(value))
        except (ValueError, OverflowError):
            return DEFAULT_START_DATE
    return DEFAULT_START_DATE


@retry(
    retry=retry_if_exception_type((PartnerizeRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(MAX_RETRIES),
    wait=wait_exponential_jitter(initial=1, max=60),
    reraise=True,
)
def _get_json(
    session: requests.Session,
    url: str,
    params: dict[str, Any] | None,
    logger: FilteringBoundLogger,
) -> dict[str, Any]:
    response = session.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)

    # Partnerize rate-limits with 429s and publishes no numeric limit or reset header, so
    # exponential backoff is the only strategy available.
    if response.status_code == 429 or response.status_code >= 500:
        raise PartnerizeRetryableError(f"Partnerize API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Partnerize API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    data = response.json()
    if not isinstance(data, dict):
        raise PartnerizeRetryableError(f"Partnerize returned an unexpected payload for {url}: {type(data).__name__}")

    return data


def _unwrap_rows(data: dict[str, Any], config: PartnerizeEndpointConfig) -> list[dict[str, Any]]:
    """Extract the row list and strip Partnerize's single-key item wrapper (e.g. {"campaign": {...}})."""
    items = data.get(config.data_key)
    if not isinstance(items, list):
        raise PartnerizeRetryableError(
            f"Partnerize returned an unexpected '{config.data_key}' field: {type(items).__name__}"
        )

    rows: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        inner = item.get(config.item_key) if config.item_key else None
        rows.append(inner if isinstance(inner, dict) else item)
    return rows


def _endpoint_url(config: PartnerizeEndpointConfig, publisher_id: str) -> str:
    return f"{PARTNERIZE_BASE_URL}{config.path.format(publisher_id=publisher_id)}"


def _get_report_rows(
    session: requests.Session,
    config: PartnerizeEndpointConfig,
    publisher_id: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PartnerizeResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> Iterator[list[dict[str, Any]]]:
    params: dict[str, Any] = {}
    if should_use_incremental_field and db_incremental_field_last_value is not None:
        params["start_date"] = _format_start_date(db_incremental_field_last_value)
        # Rows at exactly the boundary timestamp are re-fetched; merge dedupes them on the
        # primary key.
        if incremental_field is not None:
            params.update(config.incremental_field_params.get(incremental_field, {}))
    else:
        params["start_date"] = DEFAULT_START_DATE

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    offset = resume.offset if (resume and resume.offset is not None) else 0
    if offset:
        logger.debug(f"Partnerize: resuming {config.name} from offset {offset}")

    url = _endpoint_url(config, publisher_id)

    while True:
        data = _get_json(session, url, {**params, "offset": offset}, logger)
        rows = _unwrap_rows(data, config)
        if rows:
            yield rows

        page_limit = data.get("limit")
        if not isinstance(page_limit, int) or page_limit <= 0:
            page_limit = REPORT_PAGE_LIMIT

        # A short (or empty) page marks the end of the window.
        if len(rows) < page_limit:
            break

        offset += len(rows)
        # Save AFTER yielding so a crash re-fetches from the next page (already-yielded pages are
        # persisted); merge dedupes the re-pulled page on the primary key.
        resumable_source_manager.save_state(PartnerizeResumeConfig(offset=offset))


def _get_list_rows(
    session: requests.Session,
    config: PartnerizeEndpointConfig,
    publisher_id: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PartnerizeResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume and resume.next_url:
        url = resume.next_url
        logger.debug(f"Partnerize: resuming {config.name} from {url}")
    else:
        url = _endpoint_url(config, publisher_id)

    while True:
        data = _get_json(session, url, None, logger)
        rows = _unwrap_rows(data, config)
        if rows:
            yield rows

        next_page = ((data.get("hypermedia") or {}).get("pagination") or {}).get("next_page")
        # A missing next_page marks the end of the list. An empty page also terminates
        # defensively so a lingering cursor can never produce an infinite loop.
        if not isinstance(next_page, str) or not next_page or not rows:
            break

        url = next_page if next_page.startswith("http") else f"{PARTNERIZE_BASE_URL}{next_page}"
        resumable_source_manager.save_state(PartnerizeResumeConfig(next_url=url))


def get_rows(
    application_key: str,
    user_api_key: str,
    publisher_id: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PartnerizeResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[list[dict[str, Any]]]:
    config = PARTNERIZE_ENDPOINTS[endpoint]
    session = make_tracked_session(
        headers=_headers(application_key, user_api_key), redact_values=(application_key, user_api_key)
    )

    if config.kind == "report":
        yield from _get_report_rows(
            session,
            config,
            publisher_id,
            logger,
            resumable_source_manager,
            should_use_incremental_field,
            db_incremental_field_last_value,
            incremental_field,
        )
    else:
        yield from _get_list_rows(session, config, publisher_id, logger, resumable_source_manager)


def partnerize_source(
    application_key: str,
    user_api_key: str,
    publisher_id: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PartnerizeResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = PARTNERIZE_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            application_key=application_key,
            user_api_key=user_api_key,
            publisher_id=publisher_id,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        ),
        primary_keys=config.primary_keys,
        # The report endpoints document no ordering guarantee and accept no sort parameter, so the
        # incremental watermark only commits once a sync completes ("desc" semantics) instead of
        # checkpointing after every batch, which would risk skipping rows on an interrupted sync.
        sort_mode="desc" if config.kind == "report" else "asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def check_access(application_key: str, user_api_key: str, publisher_id: str) -> tuple[int, Optional[str]]:
    """Probe the partner account to validate the credential pair and publisher ID in one call.

    Returns ``(status, message)``: ``200`` reachable, ``401``/``403``/``404`` auth or access
    failure, ``0`` for a connection problem, other HTTP status otherwise.
    """
    session = make_tracked_session(
        headers=_headers(application_key, user_api_key), redact_values=(application_key, user_api_key)
    )
    try:
        response = session.get(
            f"{PARTNERIZE_BASE_URL}/user/publisher/{publisher_id}",
            timeout=15,
        )
    except Exception as e:
        return 0, f"Could not connect to Partnerize: {e}"

    if response.status_code in (401, 403, 404):
        return response.status_code, None

    if not response.ok:
        return response.status_code, f"Partnerize returned HTTP {response.status_code}"

    return 200, None


def validate_credentials(application_key: str, user_api_key: str, publisher_id: str) -> tuple[bool, str | None]:
    status, message = check_access(application_key, user_api_key, publisher_id)
    if status == 200:
        return True, None
    if status == 401:
        return False, "Invalid Partnerize API credentials. Check your user application key and user API key."
    if status in (403, 404):
        return False, f"Your Partnerize credentials do not have access to publisher '{publisher_id}'."
    return False, message or "Could not validate Partnerize credentials"
