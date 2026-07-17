import json
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
from products.warehouse_sources.backend.temporal.data_imports.sources.logz_io.settings import (
    DEFAULT_REGION,
    LOGZIO_ENDPOINTS,
    REGION_BASE_URLS,
    LogzIOEndpointConfig,
)

REQUEST_TIMEOUT_SECONDS = 60
# Elasticsearch scroll page size. Logz.io caps a single search response and the scroll cursor walks
# the rest; 1000 balances round-trips against per-response memory.
SCROLL_PAGE_SIZE = 1000
# Body-paginated list endpoints (triggered alerts, drop filters).
PAGE_SIZE = 100
# Hard cap on body-paginated pages per sync so a mis-terminating cursor can't scan unbounded.
MAX_PAGES = 10_000
# First incremental sync of logs backfills this many days. Logz.io retention is account-bounded, so
# only data still within the retention window is actually returned regardless.
INITIAL_LOOKBACK_DAYS = 3


class LogzIORetryableError(Exception):
    pass


@dataclasses.dataclass
class LogzIOResumeConfig:
    # Elasticsearch scroll cursor for `search_logs`. Valid for ~20 minutes, so it only enables
    # within-run heartbeat resume; across runs the incremental `@timestamp` watermark is the durable
    # cursor. None for the non-scroll endpoints.
    scroll_id: str | None = None


def base_url_for_region(region: str | None) -> str:
    return REGION_BASE_URLS.get((region or DEFAULT_REGION).lower(), REGION_BASE_URLS[DEFAULT_REGION])


def _get_headers(api_token: str) -> dict[str, str]:
    return {
        "X-API-TOKEN": api_token,
        "Content-Type": "application/json",
        "Accept": "application/json",
        # Logz.io recommends compression for large search/scroll responses.
        "Accept-Encoding": "gzip, deflate",
    }


def _format_timestamp(value: Any) -> str:
    """Format an incremental watermark value as an ISO 8601 UTC string for an Elasticsearch range query."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    elif isinstance(value, date):
        dt = datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    else:
        return str(value)
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


@retry(
    retry=retry_if_exception_type(
        (LogzIORetryableError, requests.ReadTimeout, requests.ConnectionError, requests.exceptions.ChunkedEncodingError)
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch(
    session: requests.Session,
    method: str,
    url: str,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    json_body: dict[str, Any] | None = None,
) -> Any:
    # Returns the decoded JSON body — a dict for search/paged endpoints, a bare array for the
    # list endpoints (e.g. /v2/alerts).
    response = session.request(method, url, headers=headers, json=json_body, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429 or response.status_code >= 500:
        raise LogzIORetryableError(f"Logz.io API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Logz.io API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def validate_credentials(api_token: str, region: str | None, schema_name: str | None = None) -> tuple[bool, str | None]:
    """Probe the token against the account's region.

    At source-create (`schema_name is None`) a 403 is accepted: the token may simply lack scope for
    the alerts endpoint while still being valid for logs. A 401 is always a bad token.
    """
    base_url = base_url_for_region(region)
    url = f"{base_url}/v2/alerts"
    try:
        # X-API-TOKEN isn't in the tracked transport's auth-header denylist, so the raw token must be
        # registered for redaction or sample capture would persist it. Redirects stay disabled so a
        # 3xx to another host can't replay the token in this custom header.
        response = make_tracked_session(redact_values=(api_token,), allow_redirects=False).get(
            url, headers=_get_headers(api_token), timeout=10
        )
    except Exception:
        return False, "Could not reach Logz.io. Check the selected region and try again."

    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return False, "Your Logz.io API token is invalid. Create a new token in your Logz.io account settings."
    if response.status_code == 403:
        if schema_name is None:
            return True, None
        return False, "Your Logz.io API token does not have access to this data."
    return False, f"Logz.io returned an unexpected response (status {response.status_code})."


def _select(data: dict[str, Any] | list[dict[str, Any]], selector: str) -> list[dict[str, Any]]:
    """Pull the row array out of a response body, tolerating a bare-array or wrapped shape."""
    if isinstance(data, list):
        return data
    if not selector:
        return data.get("results", []) or []
    value = data.get(selector)
    return value if isinstance(value, list) else []


def _parse_scroll_hits(response: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract and flatten the log documents from a scroll response.

    Logz.io returns `hits` as a JSON-encoded string wrapping the standard Elasticsearch
    `{"total": ..., "hits": [...]}` structure. Each hit is flattened so `_source` fields sit at the
    top level alongside the document metadata (`_id`, `_index`).
    """
    raw_hits = response.get("hits")
    if isinstance(raw_hits, str):
        try:
            raw_hits = json.loads(raw_hits)
        except (ValueError, TypeError):
            return []
    if not isinstance(raw_hits, dict):
        return []

    rows: list[dict[str, Any]] = []
    for hit in raw_hits.get("hits", []):
        source = hit.get("_source", {})
        row = {**source} if isinstance(source, dict) else {"_source": source}
        row["_id"] = hit.get("_id")
        row["_index"] = hit.get("_index")
        rows.append(row)
    return rows


def _build_log_query(
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> dict[str, Any]:
    """Build the Elasticsearch DSL body for a windowed log search.

    Incremental syncs bound the lower edge with the stored watermark; first syncs fall back to a
    fixed lookback. Results are sorted ascending on the timestamp field so the pipeline can advance
    the watermark safely after each batch (SourceResponse.sort_mode == "asc").
    """
    timestamp_field = incremental_field or "@timestamp"

    if should_use_incremental_field and db_incremental_field_last_value:
        start = db_incremental_field_last_value
    else:
        start = datetime.now(UTC) - timedelta(days=INITIAL_LOOKBACK_DAYS)

    range_filter = {
        "range": {timestamp_field: {"gte": _format_timestamp(start), "format": "strict_date_optional_time"}}
    }

    return {
        "query": {"bool": {"filter": [range_filter]}},
        "sort": [{timestamp_field: {"order": "asc"}}],
        "size": SCROLL_PAGE_SIZE,
    }


def _iter_scroll_rows(
    session: requests.Session,
    base_url: str,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[LogzIOResumeConfig],
    query_body: dict[str, Any],
) -> Iterator[list[dict[str, Any]]]:
    url = f"{base_url}/v1/scroll"

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.scroll_id:
        try:
            data = _fetch(session, "POST", url, headers, logger, json_body={"scroll_id": resume.scroll_id})
            logger.debug("Logz.io: resuming scroll from saved cursor")
        except requests.HTTPError:
            # A scroll cursor expires after ~20 minutes, so a stale resume can't continue. Restart
            # the windowed search from the watermark instead — merge dedupes the re-pulled rows.
            logger.warning("Logz.io: saved scroll cursor expired, restarting search from watermark")
            data = _fetch(session, "POST", url, headers, logger, json_body=query_body)
    else:
        data = _fetch(session, "POST", url, headers, logger, json_body=query_body)

    while True:
        rows = _parse_scroll_hits(data)
        if not rows:
            break

        yield rows

        scroll_id = data.get("scrollId")
        if not scroll_id:
            break
        # Save AFTER yielding so a crash re-yields the last batch rather than skipping it.
        resumable_source_manager.save_state(LogzIOResumeConfig(scroll_id=scroll_id))
        data = _fetch(session, "POST", url, headers, logger, json_body={"scroll_id": scroll_id})


def _iter_paged_rows(
    session: requests.Session,
    base_url: str,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    config: LogzIOEndpointConfig,
) -> Iterator[list[dict[str, Any]]]:
    url = f"{base_url}{config.path}"
    page_number = 1
    while page_number <= MAX_PAGES:
        body = {"pagination": {"pageNumber": page_number, "pageSize": PAGE_SIZE}}
        data = _fetch(session, config.method, url, headers, logger, json_body=body)
        rows = _select(data, config.data_selector)
        if not rows:
            break

        yield rows

        if len(rows) < PAGE_SIZE:
            break
        page_number += 1
    else:
        logger.warning(f"Logz.io: hit page cap ({MAX_PAGES}) for {config.name}; stopping pagination")


def _iter_list_rows(
    session: requests.Session,
    base_url: str,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    config: LogzIOEndpointConfig,
) -> Iterator[list[dict[str, Any]]]:
    url = f"{base_url}{config.path}"
    data = _fetch(session, config.method, url, headers, logger)
    rows = _select(data, config.data_selector)
    if rows:
        yield rows


def get_rows(
    api_token: str,
    region: str | None,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[LogzIOResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[list[dict[str, Any]]]:
    config = LOGZIO_ENDPOINTS[endpoint]
    base_url = base_url_for_region(region)
    headers = _get_headers(api_token)
    # X-API-TOKEN isn't in the tracked transport's auth-header denylist, so the raw token must be
    # registered for redaction or sample capture would persist it. Redirects stay disabled so a
    # 3xx to another host can't replay the token in this custom header.
    session = make_tracked_session(redact_values=(api_token,), allow_redirects=False)

    if config.transport == "scroll":
        query_body = _build_log_query(should_use_incremental_field, db_incremental_field_last_value, incremental_field)
        yield from _iter_scroll_rows(session, base_url, headers, logger, resumable_source_manager, query_body)
    elif config.transport == "page":
        yield from _iter_paged_rows(session, base_url, headers, logger, config)
    else:
        yield from _iter_list_rows(session, base_url, headers, logger, config)


def logz_io_source(
    api_token: str,
    region: str | None,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[LogzIOResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    endpoint_config = LOGZIO_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_token=api_token,
            region=region,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        ),
        primary_keys=endpoint_config.primary_keys,
        # Logs are searched ascending on `@timestamp`; the definition/config endpoints aren't
        # incremental, so asc is a safe default there too.
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )
