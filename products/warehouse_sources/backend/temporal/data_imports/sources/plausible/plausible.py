import time
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlparse

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.plausible.settings import (
    DEFAULT_BACKFILL_DAYS,
    PLAUSIBLE_ENDPOINTS,
    REPORT_LOOKBACK_DAYS,
    PlausibleEndpointConfig,
)

# Plausible Cloud; self-hosted instances override this via the source's host field.
PLAUSIBLE_DEFAULT_HOST = "https://plausible.io"
QUERY_PATH = "/api/v2/query"

# Stats API v2 caps pagination.limit at 10000 rows per page.
DEFAULT_PAGE_LIMIT = 10000
REQUEST_TIMEOUT_SECONDS = 120
# Default rate limit is 600 requests/hour per API key. We can't enforce a global budget here, so we
# add a light per-request throttle and lean on retry/backoff to absorb 429s.
REQUEST_THROTTLE_SECONDS = 0.25
MAX_RETRY_ATTEMPTS = 5


class PlausibleRetryableError(Exception):
    pass


@dataclasses.dataclass
class PlausibleResumeConfig:
    # Offset of the next page to fetch within the current query.
    offset: int = 0
    # The date window the in-flight query was issued for, pinned so resuming mid-pagination keeps a
    # consistent total_rows/ordering instead of shifting when "today" moves.
    date_range_start: Optional[str] = None
    date_range_end: Optional[str] = None


def normalize_host(host: str) -> str:
    """Normalize the instance URL and reject anything that isn't plain http(s)."""
    host = host.strip()
    if not host:
        raise ValueError("Plausible host is required")
    if "://" not in host:
        host = f"https://{host}"
    host = host.rstrip("/")
    parsed = urlparse(host)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError(f"Invalid Plausible host: {host}")
    return host


def resolve_host(host: Optional[str]) -> str:
    """Default an empty host to Plausible Cloud, then normalize it."""
    return normalize_host(host or PLAUSIBLE_DEFAULT_HOST)


def hostname_of(host: Optional[str]) -> str:
    return urlparse(resolve_host(host)).hostname or ""


def _get_session(api_key: str) -> requests.Session:
    # `host` is user-supplied, so pin redirects off: validation and the outbound request must stay
    # on the same target (SSRF defense-in-depth). The key is redacted from logged URLs/samples.
    return make_tracked_session(
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        redact_values=(api_key,),
        allow_redirects=False,
    )


def _to_date(value: Any) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except ValueError:
            return None
    return None


def _build_query(config: PlausibleEndpointConfig, site_id: str, start: date, end: date, offset: int) -> dict[str, Any]:
    return {
        "site_id": site_id,
        "metrics": config.metrics,
        "date_range": [start.isoformat(), end.isoformat()],
        "dimensions": config.dimensions,
        # Ascending by day so the pipeline's incremental watermark only ever advances forward.
        "order_by": [["time:day", "asc"]],
        "pagination": {"limit": DEFAULT_PAGE_LIMIT, "offset": offset},
        "include": {"total_rows": True},
    }


def _normalize_row(config: PlausibleEndpointConfig, result: dict[str, Any]) -> dict[str, Any]:
    """Flatten a Stats API result ({dimensions: [...], metrics: [...]}) into a named-column dict."""
    row: dict[str, Any] = {}
    # Direct access (not .get) so a malformed response missing dimensions — and therefore the `date`
    # primary key — fails fast instead of ingesting unkeyed rows.
    for name, value in zip(config.column_names, result["dimensions"]):
        row[name] = value
    for name, value in zip(config.metrics, result["metrics"]):
        row[name] = value
    return row


@retry(
    retry=retry_if_exception_type((PlausibleRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
    wait=wait_exponential_jitter(initial=2, max=90),
    reraise=True,
)
def _query(
    session: requests.Session, url: str, payload: dict[str, Any], logger: FilteringBoundLogger
) -> dict[str, Any]:
    # Throttle every call, including tenacity retries, so a retry storm can't blow past the rate
    # limit on top of the backoff.
    time.sleep(REQUEST_THROTTLE_SECONDS)
    response = session.post(url, json=payload, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429 or response.status_code >= 500:
        raise PlausibleRetryableError(f"Plausible API error (retryable): status={response.status_code}")

    if not response.ok:
        logger.error(f"Plausible API error: status={response.status_code}, body={response.text[:500]}")
        response.raise_for_status()

    return response.json()


def validate_credentials(host: Optional[str], site_id: str, api_key: str) -> tuple[bool, str | None]:
    """Confirm the instance is reachable and the key can read the site's stats."""
    try:
        response = _get_session(api_key).post(
            f"{resolve_host(host)}{QUERY_PATH}",
            # Cheapest possible probe: one metric over a short relative range, no dimensions.
            json={"site_id": site_id, "metrics": ["visitors"], "date_range": "7d"},
            timeout=15,
        )
    except Exception:
        return False, "Could not reach Plausible. Check the host URL."

    if response.status_code == 200:
        return True, None
    if response.status_code in (401, 403):
        return False, "Plausible rejected the API key. Check the key and that it has the stats read scope."
    if response.status_code == 404:
        return False, "Plausible could not find that site. Check the site domain (site ID)."

    try:
        message = response.json().get("error")
    except Exception:
        message = None
    return False, message or f"Plausible returned status {response.status_code}."


def get_rows(
    host: Optional[str],
    site_id: str,
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PlausibleResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = PLAUSIBLE_ENDPOINTS[endpoint]
    session = _get_session(api_key)
    url = f"{resolve_host(host)}{QUERY_PATH}"

    today = datetime.now(tz=UTC).date()
    start = today - timedelta(days=DEFAULT_BACKFILL_DAYS)
    if should_use_incremental_field:
        watermark = _to_date(db_incremental_field_last_value)
        if watermark is not None:
            # Recent days re-aggregate as visits arrive, so re-pull a trailing window and let merge
            # on the (date, ...) primary key overwrite the changed rows.
            start = watermark - timedelta(days=REPORT_LOOKBACK_DAYS)
    end = today
    offset = 0

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume_config is not None:
        resumed_start = _to_date(resume_config.date_range_start)
        resumed_end = _to_date(resume_config.date_range_end)
        if resumed_start is not None:
            start = resumed_start
        if resumed_end is not None:
            end = resumed_end
        offset = resume_config.offset or 0
        logger.debug(f"Plausible: resuming {endpoint} from offset={offset}, range={start}..{end}")

    if start > end:
        start = end

    while True:
        body = _query(session, url, _build_query(config, site_id, start, end, offset), logger)
        results = body.get("results", []) or []

        rows = [_normalize_row(config, result) for result in results]
        if rows:
            yield rows

        total_rows = body.get("meta", {}).get("total_rows")
        next_offset = offset + DEFAULT_PAGE_LIMIT
        reached_end = len(results) < DEFAULT_PAGE_LIMIT or (total_rows is not None and next_offset >= total_rows)
        if reached_end:
            break

        offset = next_offset
        # Save AFTER yielding so a crash resumes on the next unfetched page (already-yielded rows
        # are deduped by the primary key on merge).
        resumable_source_manager.save_state(
            PlausibleResumeConfig(offset=offset, date_range_start=start.isoformat(), date_range_end=end.isoformat())
        )


def plausible_source(
    host: Optional[str],
    site_id: str,
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PlausibleResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = PLAUSIBLE_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            host=host,
            site_id=site_id,
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=list(config.primary_keys),
        # Reports are pulled oldest-day-first (order_by time:day asc), so the cursor only moves forward.
        sort_mode="asc",
        partition_mode="datetime",
        partition_format="month",
        partition_keys=["date"],
    )
