import re
import dataclasses
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.linearb.settings import (
    LINEARB_ENDPOINTS,
    MEASUREMENT_METRICS,
    MEASUREMENTS_DEFAULT_WINDOW_DAYS,
    LinearbEndpointConfig,
)

LINEARB_BASE_URL = "https://public-api.linearb.io"

# LinearB caps every endpoint at 60 calls/minute. We stay well under it with a single sequential
# paginator per sync, but bound retries so a sustained 429 fails cleanly rather than looping.
PAGE_TIMEOUT_SECONDS = 60

_NON_COLUMN_SAFE = re.compile(r"[^0-9a-zA-Z_]+")


class LinearbRetryableError(Exception):
    pass


@dataclasses.dataclass
class LinearbResumeConfig:
    # Offset of the next page to fetch for list endpoints. Measurements is a single windowed query
    # and does not resume.
    offset: int = 0


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "x-api-key": api_key,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _sanitize_metric_key(key: str) -> str:
    """Normalize a LinearB metric key (e.g. "branch.computed.cycle_time:p75") into a column-safe name."""
    return _NON_COLUMN_SAFE.sub("_", key).strip("_")


@retry(
    retry=retry_if_exception_type(
        (
            LinearbRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _request(
    session: requests.Session,
    method: str,
    url: str,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
) -> requests.Response:
    response = session.request(
        method, url, headers=headers, params=params, json=json_body, timeout=PAGE_TIMEOUT_SECONDS
    )

    # Honor the per-endpoint 60/min rate limit and transient server errors by retrying.
    if response.status_code == 429 or response.status_code >= 500:
        raise LinearbRetryableError(f"LinearB API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"LinearB API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response


def validate_credentials(api_key: str) -> bool:
    # The teams endpoint is available on every plan, so it is the cheapest genuine token probe. A
    # bad or missing key returns 403 from LinearB's API gateway; a valid key returns 200.
    url = f"{LINEARB_BASE_URL}/api/v2/teams"
    try:
        response = make_tracked_session().get(url, headers=_get_headers(api_key), params={"page_size": 1}, timeout=10)
        return response.status_code == 200
    except Exception:
        return False


def _iter_list_rows(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    config: LinearbEndpointConfig,
    resumable_source_manager: ResumableSourceManager[LinearbResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    """Page through a wrapped `{total, items}` list endpoint using offset pagination.

    Termination is driven by the response's `total` count first (some endpoints ignore paging params
    and return everything in one page), then by an empty or short page, so an endpoint that silently
    ignores `offset` can't loop forever.
    """
    url = f"{LINEARB_BASE_URL}{config.path}"
    page_size = config.page_size

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    offset = resume.offset if resume else 0
    fetched = offset

    while True:
        params: dict[str, Any] = {}
        if config.page_size_param and page_size:
            params[config.page_size_param] = page_size
            params["offset"] = offset

        response = _request(session, "GET", url, headers, logger, params=params)
        payload = response.json()
        items = payload.get(config.data_selector, []) if config.data_selector else payload
        if not items:
            break

        yield items
        fetched += len(items)

        # Save offset AFTER yielding so a crash re-yields the last page (merge dedupes on the primary
        # key) rather than skipping it.
        if config.page_size_param and page_size:
            resumable_source_manager.save_state(LinearbResumeConfig(offset=fetched))

        total = payload.get("total") if isinstance(payload, dict) else None
        if not config.page_size_param or not page_size:
            break
        if total is not None and fetched >= total:
            break
        if len(items) < page_size:
            break

        offset = fetched


def _measurements_body() -> dict[str, Any]:
    """Build the Measurements V2 request body for an organization-level daily rollup.

    Grouping by organization needs no team/repository IDs, so it works for any account without extra
    configuration. The window is the trailing `MEASUREMENTS_DEFAULT_WINDOW_DAYS` days.
    """
    before = datetime.now(UTC).date()
    after = before - timedelta(days=MEASUREMENTS_DEFAULT_WINDOW_DAYS)
    requested_metrics = [{"name": name, "agg": agg} if agg else {"name": name} for name, agg in MEASUREMENT_METRICS]
    return {
        "requested_metrics": requested_metrics,
        "group_by": "organization",
        "roll_up": "1d",
        "time_ranges": [{"after": after.isoformat(), "before": before.isoformat()}],
    }


def _iter_measurements_rows(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    """Fetch the daily measurements windows and flatten each metric object into a row.

    The response is an array of `{after, before, metrics: [...]}` windows; each metrics object carries
    the group id (`organization_id`) plus one key per requested metric. We stamp the window's
    `after`/`before` onto every flattened row so they can be partitioned and deduped by day.
    """
    url = f"{LINEARB_BASE_URL}/api/v2/measurements"
    response = _request(session, "POST", url, headers, logger, json_body=_measurements_body())

    # No data for the window returns 204; treat it as an empty sync.
    if response.status_code == 204 or not response.content:
        return

    windows = response.json()
    rows: list[dict[str, Any]] = []
    for window in windows:
        after = window.get("after")
        before = window.get("before")
        for metric in window.get("metrics", []):
            row = {"after": after, "before": before}
            for key, value in metric.items():
                row[_sanitize_metric_key(key)] = value
            rows.append(row)

    if rows:
        yield rows


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[LinearbResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = LINEARB_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)
    session = make_tracked_session()

    if config.method == "POST":
        yield from _iter_measurements_rows(session, headers, logger)
        return

    yield from _iter_list_rows(session, headers, logger, config, resumable_source_manager)


def linearb_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[LinearbResumeConfig],
) -> SourceResponse:
    config = LINEARB_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=config.primary_keys,
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format=config.partition_format if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
