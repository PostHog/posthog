import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.helicone.settings import (
    HELICONE_ENDPOINTS,
    HELICONE_HOSTS,
    PROMPTS_ENDPOINT,
    PROMPTS_PAGE_SIZE,
    REQUESTS_DEFAULT_LOOKBACK_DAYS,
    REQUESTS_ENDPOINT,
    REQUESTS_PAGE_SIZE,
    SESSIONS_ENDPOINT,
    SESSIONS_PAGE_SIZE,
    USERS_ENDPOINT,
)

REQUEST_TIMEOUT_SECONDS = 120
RETRY_MAX_ATTEMPTS = 5


class HeliconeRetryableError(Exception):
    pass


@dataclasses.dataclass
class HeliconeResumeConfig:
    # Rows already yielded for the endpoint being paged — the next request's `offset` (for the
    # page-based prompts endpoint it's converted to a page number).
    offset: int = 0
    # The window bounds captured when the run started, pinned in the resume state so a resumed
    # attempt pages the exact same result set instead of recomputing "now" and shifting rows
    # across page boundaries. `created_after` is the ISO gte cutoff for the incremental request
    # log; `end_time_unix_ms` bounds the sessions time filter.
    created_after: str | None = None
    end_time_unix_ms: int | None = None


def _host(region: str) -> str:
    return HELICONE_HOSTS.get(region, HELICONE_HOSTS["us"])


def _headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


def _format_timestamp(value: Any) -> str | None:
    """Format an incremental cursor as the ISO 8601 UTC string Helicone's timestamp operators take."""
    if isinstance(value, datetime):
        utc_value = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return utc_value.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    if isinstance(value, date):
        return _format_timestamp(datetime.combine(value, datetime.min.time(), tzinfo=UTC))
    if isinstance(value, str) and value:
        return value
    return None


def _extract_data(body: Any, url: str) -> list[dict[str, Any]]:
    """Unwrap Helicone's `{"data": [...], "error": null}` result union.

    The prompts endpoint documents a bare array response, so lists pass through as-is.
    """
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        error = body.get("error")
        if error:
            raise Exception(f"Helicone API returned an error for {url}: {error}")
        data = body.get("data")
        if isinstance(data, list):
            return data
        return []
    return []


@retry(
    retry=retry_if_exception_type((HeliconeRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(RETRY_MAX_ATTEMPTS),
    wait=wait_exponential_jitter(initial=2, max=60),
    reraise=True,
)
def _post(
    session: requests.Session, url: str, headers: dict[str, str], body: dict[str, Any], logger: FilteringBoundLogger
) -> Any:
    response = session.post(url, headers=headers, json=body, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429 or response.status_code >= 500:
        raise HeliconeRetryableError(f"Helicone API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Helicone API error: status={response.status_code}, body={response.text[:500]}, url={url}")
        response.raise_for_status()

    return response.json()


def validate_credentials(api_key: str, region: str) -> tuple[bool, Optional[str]]:
    # Probe the point-query request endpoint with a single-row lookup: it authenticates with the
    # same key as every other endpoint and is designed for small reads (the bulk clickhouse
    # variant is documented to time out on point queries).
    url = f"{_host(region)}/v1/request/query"
    try:
        response = make_tracked_session().post(
            url,
            headers=_headers(api_key),
            json={"filter": "all", "limit": 1, "offset": 0},
            timeout=30,
        )
    except Exception as e:
        return False, f"Could not reach Helicone ({e}). Please check your network and selected region, then retry."

    if response.status_code == 200:
        return True, None
    if response.status_code in (401, 403):
        return (
            False,
            "Helicone rejected the API key. Check the key in your Helicone dashboard (Settings → API Keys) "
            "and that the selected region matches where your Helicone organization lives.",
        )
    return False, f"Unexpected response from Helicone (status {response.status_code})."


def _requests_rows(
    session: requests.Session,
    host: str,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[HeliconeResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> Iterator[list[dict[str, Any]]]:
    url = f"{host}{HELICONE_ENDPOINTS[REQUESTS_ENDPOINT].path}"

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None:
        offset = resume.offset
        created_after = resume.created_after
        logger.debug(f"Helicone: resuming requests from offset={offset}, created_after={created_after}")
    else:
        offset = 0
        if should_use_incremental_field and not db_incremental_field_last_value:
            # First incremental sync: bound the backfill instead of paging the org's full history.
            db_incremental_field_last_value = datetime.now(UTC) - timedelta(days=REQUESTS_DEFAULT_LOOKBACK_DAYS)
        created_after = (
            _format_timestamp(db_incremental_field_last_value)
            if should_use_incremental_field and db_incremental_field_last_value
            else None
        )

    filter_field = incremental_field or "request_created_at"
    # Each condition must be its own filter leaf in Helicone's AST; a single gte condition needs no
    # branch node. The gte filter rides in the body of every page request, so pagination stays
    # bounded by the watermark on every page (no client-side termination needed).
    filter_node: Any = {"request_response_rmt": {filter_field: {"gte": created_after}}} if created_after else "all"

    while True:
        body = {
            "filter": filter_node,
            "limit": REQUESTS_PAGE_SIZE,
            "offset": offset,
            # Ascending creation-time sort so the pipeline's incremental watermark can checkpoint
            # after every batch (matches SourceResponse.sort_mode="asc"). Appends land after the
            # current offset, so new rows arriving mid-sync can't shift earlier pages.
            "sort": {"created_at": "asc"},
        }
        rows = _extract_data(_post(session, url, headers, body, logger), url)
        if not rows:
            break

        yield rows
        offset += len(rows)
        # Save AFTER yielding so a crash re-yields the last page rather than skipping it — merge
        # dedupes on request_id.
        resumable_source_manager.save_state(HeliconeResumeConfig(offset=offset, created_after=created_after))

        if len(rows) < REQUESTS_PAGE_SIZE:
            break


def _sessions_rows(
    session: requests.Session,
    host: str,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[HeliconeResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    url = f"{host}{HELICONE_ENDPOINTS[SESSIONS_ENDPOINT].path}"

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.end_time_unix_ms is not None:
        offset = resume.offset
        end_time_unix_ms = resume.end_time_unix_ms
        logger.debug(f"Helicone: resuming sessions from offset={offset}")
    else:
        offset = 0
        end_time_unix_ms = int(datetime.now(UTC).timestamp() * 1000)

    while True:
        # search/timeFilter/timezoneDifference/filter are required by the API even when unused.
        body = {
            "search": "",
            "timeFilter": {"startTimeUnixMs": 0, "endTimeUnixMs": end_time_unix_ms},
            "timezoneDifference": 0,
            "filter": "all",
            "offset": offset,
            "limit": SESSIONS_PAGE_SIZE,
        }
        rows = _extract_data(_post(session, url, headers, body, logger), url)
        if not rows:
            break

        yield rows
        offset += len(rows)
        resumable_source_manager.save_state(HeliconeResumeConfig(offset=offset, end_time_unix_ms=end_time_unix_ms))

        if len(rows) < SESSIONS_PAGE_SIZE:
            break


def _users_rows(
    session: requests.Session,
    host: str,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    url = f"{host}{HELICONE_ENDPOINTS[USERS_ENDPOINT].path}"
    # The endpoint takes an optional userIds/timeFilter and has no pagination; an explicit
    # epoch-to-now window makes the full-history intent unambiguous.
    body = {
        "timeFilter": {
            "startTimeUnixSeconds": 0,
            "endTimeUnixSeconds": int(datetime.now(UTC).timestamp()),
        }
    }
    rows = _extract_data(_post(session, url, headers, body, logger), url)
    if rows:
        yield rows


def _prompts_rows(
    session: requests.Session,
    host: str,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[HeliconeResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    url = f"{host}{HELICONE_ENDPOINTS[PROMPTS_ENDPOINT].path}"

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    offset = resume.offset if resume is not None else 0

    while True:
        # search/tagsFilter are required by the API; empty values match every prompt.
        body = {
            "search": "",
            "tagsFilter": [],
            "page": offset // PROMPTS_PAGE_SIZE,
            "pageSize": PROMPTS_PAGE_SIZE,
        }
        rows = _extract_data(_post(session, url, headers, body, logger), url)
        if not rows:
            break

        yield rows
        offset += len(rows)
        resumable_source_manager.save_state(HeliconeResumeConfig(offset=offset))

        if len(rows) < PROMPTS_PAGE_SIZE:
            break


def _get_rows(
    api_key: str,
    region: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[HeliconeResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> Iterator[list[dict[str, Any]]]:
    host = _host(region)
    headers = _headers(api_key)
    # One session reused across every page so urllib3 keeps the connection alive instead of
    # re-handshaking per request.
    session = make_tracked_session()

    if endpoint == REQUESTS_ENDPOINT:
        yield from _requests_rows(
            session,
            host,
            headers,
            logger,
            resumable_source_manager,
            should_use_incremental_field,
            db_incremental_field_last_value,
            incremental_field,
        )
    elif endpoint == SESSIONS_ENDPOINT:
        yield from _sessions_rows(session, host, headers, logger, resumable_source_manager)
    elif endpoint == USERS_ENDPOINT:
        yield from _users_rows(session, host, headers, logger)
    elif endpoint == PROMPTS_ENDPOINT:
        yield from _prompts_rows(session, host, headers, logger, resumable_source_manager)
    else:
        raise ValueError(f"Unknown Helicone endpoint: {endpoint}")


def helicone_source(
    api_key: str,
    region: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[HeliconeResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = HELICONE_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: _get_rows(
            api_key=api_key,
            region=region,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode="asc",
    )
