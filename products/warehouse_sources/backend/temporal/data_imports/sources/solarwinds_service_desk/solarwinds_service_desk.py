import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from dateutil import parser as dateutil_parser
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.solarwinds_service_desk.settings import (
    PER_PAGE,
    SOLARWINDS_SERVICE_DESK_ENDPOINTS,
)

# SolarWinds Service Desk runs independent regional stacks that do not share data.
SOLARWINDS_SERVICE_DESK_HOSTS: dict[str, str] = {
    "us": "https://api.samanage.com",
    "eu": "https://apieu.samanage.com",
    "au": "https://apiau.samanage.com",
}
DEFAULT_REGION = "us"
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 5
# Cheap list probe used to confirm a token is genuine. The token inherits its creator's role, so a
# 403 here can still mean a valid token — the caller decides how to treat it.
DEFAULT_PROBE_PATH = "/users.json"


class SolarwindsServiceDeskRetryableError(Exception):
    pass


@dataclasses.dataclass
class SolarwindsServiceDeskResumeConfig:
    # Next 1-indexed page to fetch. None means start from page 1.
    next_page: int | None = None
    # `updated_from` filter computed when the run started. Persisted so a resumed run issues the
    # exact same query instead of recomputing a window whose page boundaries would shift mid-crawl.
    updated_from: str | None = None


def base_url(region: Optional[str]) -> str:
    resolved = (region or DEFAULT_REGION).lower()
    return SOLARWINDS_SERVICE_DESK_HOSTS.get(resolved, SOLARWINDS_SERVICE_DESK_HOSTS[DEFAULT_REGION])


def _headers(api_token: str) -> dict[str, str]:
    # Auth rides a vendor-specific header, and the versioned Accept header pins the payload format —
    # without it the API may serve legacy shapes.
    return {
        "X-Samanage-Authorization": f"Bearer {api_token}",
        "Accept": "application/vnd.samanage.v2.1+json",
    }


def _format_updated_from(value: Any) -> Optional[str]:
    """Format an incremental cursor as the ISO 8601 UTC value the `updated_from` filter expects.

    Returns None when the watermark can't be interpreted, which safely degrades that run to a full
    crawl rather than guessing at a window.
    """
    if isinstance(value, str):
        try:
            value = dateutil_parser.parse(value)
        except (ValueError, OverflowError):
            return None
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    elif isinstance(value, date):
        aware = datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    else:
        return None
    # The documented examples use minute precision ('2023-11-29T08:00'); truncating rounds the
    # window start down, so boundary rows are re-fetched and merge dedupes them on `id`.
    return aware.astimezone(UTC).strftime("%Y-%m-%dT%H:%M")


def _build_url(host: str, path: str, page: int, updated_from: Optional[str]) -> str:
    params: dict[str, Any] = {"per_page": PER_PAGE, "page": page}
    if updated_from is not None:
        params["updated_from"] = updated_from
    return f"{host}{path}?{urlencode(params)}"


def _unwrap_rows(items: list[Any], wrapper_key: str) -> list[dict[str, Any]]:
    """Normalize list items to bare record dicts.

    The official response samples are inconsistent: some list endpoints show bare records while
    others wrap each row under its singular resource name (e.g. ``{"problem": {...}}``). A real
    record is never a single-key dict of its own singular name, so unwrapping is unambiguous.
    """
    rows: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, dict) and set(item.keys()) == {wrapper_key} and isinstance(item[wrapper_key], dict):
            rows.append(item[wrapper_key])
        elif isinstance(item, dict):
            rows.append(item)
    return rows


@retry(
    retry=retry_if_exception_type(
        (SolarwindsServiceDeskRetryableError, requests.ReadTimeout, requests.ConnectionError)
    ),
    stop=stop_after_attempt(MAX_RETRIES),
    wait=wait_exponential_jitter(initial=1, max=60),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    url: str,
    logger: FilteringBoundLogger,
) -> tuple[list[Any], Optional[int]]:
    response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)

    # The API allows 1000 requests/min but sends no rate-limit or Retry-After headers, so back off
    # blind on 429 and transient 5xx.
    if response.status_code == 429 or response.status_code >= 500:
        raise SolarwindsServiceDeskRetryableError(
            f"SolarWinds Service Desk API error (retryable): status={response.status_code}, url={url}"
        )

    if not response.ok:
        logger.error(
            f"SolarWinds Service Desk API error: status={response.status_code}, body={response.text}, url={url}"
        )
        response.raise_for_status()

    data = response.json()
    if not isinstance(data, list):
        raise SolarwindsServiceDeskRetryableError(
            f"SolarWinds Service Desk returned an unexpected payload for {url}: {type(data).__name__}"
        )

    total_pages_header = response.headers.get("X-Total-Pages")
    total_pages = int(total_pages_header) if total_pages_header and total_pages_header.isdigit() else None
    return data, total_pages


def get_rows(
    region: Optional[str],
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SolarwindsServiceDeskResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = SOLARWINDS_SERVICE_DESK_ENDPOINTS[endpoint]
    host = base_url(region)
    session = make_tracked_session(headers=_headers(api_token), redact_values=(api_token,))

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.next_page:
        page = resume.next_page
        updated_from = resume.updated_from
        logger.debug(f"SolarWinds Service Desk: resuming {endpoint} from page {page}")
    else:
        page = 1
        updated_from = None
        if config.supports_incremental and should_use_incremental_field and db_incremental_field_last_value is not None:
            updated_from = _format_updated_from(db_incremental_field_last_value)

    while True:
        items, total_pages = _fetch_page(session, _build_url(host, config.path, page, updated_from), logger)
        rows = _unwrap_rows(items, config.wrapper_key)
        if rows:
            yield rows

        # Stop on an empty page, or once the documented X-Total-Pages header says this was the last
        # one. Never infer the end from a short page — the server may clamp `per_page` below what we
        # requested, which would silently truncate the sync.
        if not items or (total_pages is not None and page >= total_pages):
            break

        page += 1
        # Save AFTER yielding so a crash re-fetches the last unpersisted page; merge dedupes on `id`.
        resumable_source_manager.save_state(
            SolarwindsServiceDeskResumeConfig(next_page=page, updated_from=updated_from)
        )


def solarwinds_service_desk_source(
    region: Optional[str],
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SolarwindsServiceDeskResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = SOLARWINDS_SERVICE_DESK_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            region=region,
            api_token=api_token,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        # List ordering is undocumented (no sort params, likely newest-first): "desc" makes the
        # pipeline commit the incremental watermark only after a completed sync instead of
        # checkpointing a possibly-too-high value per batch.
        sort_mode="desc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def check_access(region: Optional[str], api_token: str, path: str = DEFAULT_PROBE_PATH) -> tuple[int, Optional[str]]:
    """Probe a single list endpoint to validate the API token.

    Returns ``(status, message)``: ``200`` reachable, ``401``/``403`` auth failure, ``0`` for a
    connection problem, other HTTP status otherwise.
    """
    session = make_tracked_session(headers=_headers(api_token), redact_values=(api_token,))
    url = f"{base_url(region)}{path}?{urlencode({'per_page': 1, 'page': 1})}"
    try:
        response = session.get(url, timeout=15)
    except Exception as e:
        return 0, f"Could not connect to SolarWinds Service Desk: {e}"

    if response.status_code in (401, 403):
        return response.status_code, None

    if not response.ok:
        return response.status_code, f"SolarWinds Service Desk returned HTTP {response.status_code}"

    return 200, None


def validate_credentials(region: Optional[str], api_token: str, path: str | None = None) -> tuple[bool, str | None]:
    status, message = check_access(region, api_token, path or DEFAULT_PROBE_PATH)
    if status == 200:
        return True, None
    if status == 401:
        return False, "Invalid SolarWinds Service Desk API token"
    if status == 403:
        # The token is genuine but its owner's role can't read this resource. At source-create
        # (no specific schema requested) that must not block connecting the source.
        if path is None:
            return True, None
        return False, "Your SolarWinds Service Desk token does not have permission to read this resource"
    return False, message or "Could not validate SolarWinds Service Desk API token"
