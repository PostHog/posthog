from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter
from urllib3.util.retry import Retry

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.imagga.settings import IMAGGA_ENDPOINTS

BASE_URL = "https://api.imagga.com/v2"
REQUEST_TIMEOUT_SECONDS = 30
MAX_RETRY_ATTEMPTS = 5

# The /usage result carries two histogram objects keyed by period -> count (`daily`, `monthly`).
# Their key set changes every period, so folding them into the flat snapshot row would drift the
# column width sync to sync. They're kept out of the `usage` snapshot; the per-day series is exposed
# through the dedicated `daily_usage` table instead.
_HISTOGRAM_KEYS = frozenset({"daily", "monthly"})


class ImaggaRetryableError(Exception):
    pass


def _headers() -> dict[str, str]:
    return {"Accept": "application/json"}


def _fetch_usage(
    session: requests.Session, api_key: str, api_secret: str, logger: FilteringBoundLogger
) -> dict[str, Any]:
    """Fetch GET /usage and return its ``result`` object.

    ``concurrency=1`` asks Imagga to include the concurrency block (current vs max) alongside the
    usage counters. Credentials travel in the Basic-auth header, not the URL, so a non-2xx error's
    URL is safe to surface unredacted.
    """
    url = f"{BASE_URL}/usage?concurrency=1"
    response = session.get(url, auth=(api_key, api_secret), headers=_headers(), timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429 or response.status_code >= 500:
        raise ImaggaRetryableError(f"Imagga API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Imagga API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    body = response.json()
    result = body.get("result") if isinstance(body, dict) else None
    return result if isinstance(result, dict) else {}


def validate_credentials(api_key: str, api_secret: str) -> bool:
    """Confirm the key/secret pair is genuine with a single GET /usage. 200 = valid; 401/403 = not."""
    try:
        session = make_tracked_session(redact_values=(api_secret,) if api_secret else ())
        response = session.get(f"{BASE_URL}/usage", auth=(api_key, api_secret), headers=_headers(), timeout=10)
        return response.status_code == 200
    except Exception:
        return False


def _usage_snapshot_row(result: dict[str, Any]) -> dict[str, Any]:
    """Flatten the /usage result into one row of stable, flat-width scalar fields.

    The histogram objects (`daily`, `monthly`) are excluded — their keys change every period. Nested
    scalar objects such as ``concurrency`` are flattened with a ``<key>_`` prefix (e.g.
    ``concurrency_max``); anything still nested is dropped so the snapshot stays a flat row.
    """
    row: dict[str, Any] = {}
    for key, value in result.items():
        if key in _HISTOGRAM_KEYS:
            continue
        if isinstance(value, dict):
            for sub_key, sub_value in value.items():
                if not isinstance(sub_value, dict | list):
                    row[f"{key}_{sub_key}"] = sub_value
        elif not isinstance(value, list):
            row[key] = value
    return row


def _daily_usage_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Explode the `daily` usage histogram into one row per day.

    Imagga keys the histogram by unix-second timestamp (as a string) mapped to the day's usage count.
    Rows are sorted ascending by day to match ``sort_mode="asc"``. Unparseable keys are skipped
    rather than failing the sync.
    """
    daily = result.get("daily")
    if not isinstance(daily, dict):
        return []

    rows: list[dict[str, Any]] = []
    for ts_key, count in daily.items():
        try:
            timestamp = int(ts_key)
        except (TypeError, ValueError):
            continue
        day = datetime.fromtimestamp(timestamp, tz=UTC).date().isoformat()
        rows.append({"date": day, "timestamp": timestamp, "count": count})

    rows.sort(key=lambda r: r["date"])
    return rows


def get_rows(
    api_key: str,
    api_secret: str,
    endpoint: str,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    # The tenacity wrapper below is the single retry authority for this session, so disable the
    # transport-level status retries (`make_tracked_session`'s DEFAULT_RETRY already retries 429/5xx).
    # Otherwise both layers retry a rate-limit response and one 429 fans out into far more requests.
    session = make_tracked_session(retry=Retry(total=0), redact_values=(api_secret,) if api_secret else ())

    @retry(
        retry=retry_if_exception_type((ImaggaRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=1, max=30),
        reraise=True,
    )
    def fetch() -> dict[str, Any]:
        return _fetch_usage(session, api_key, api_secret, logger)

    result = fetch()

    if endpoint == "usage":
        row = _usage_snapshot_row(result)
        if not row:
            return
        # The `usage` table merges on `billing_period_start`. If Imagga returns a result without it,
        # yielding the row anyway makes the warehouse merge fail permanently on a missing key column;
        # skip and log instead so a malformed response degrades to an empty sync, not a hard failure.
        missing_keys = [key for key in IMAGGA_ENDPOINTS["usage"].primary_keys if key not in row]
        if missing_keys:
            logger.warning(f"Imagga /usage response missing primary key(s) {missing_keys}; skipping snapshot row")
            return
        yield [row]
        return

    if endpoint == "daily_usage":
        rows = _daily_usage_rows(result)
        if rows:
            yield rows
        return

    raise ValueError(f"Unknown Imagga endpoint: {endpoint}")


def imagga_source(
    api_key: str,
    api_secret: str,
    endpoint: str,
    logger: FilteringBoundLogger,
) -> SourceResponse:
    config = IMAGGA_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(api_key=api_key, api_secret=api_secret, endpoint=endpoint, logger=logger),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_keys=config.partition_keys,
        partition_mode=config.partition_mode,
        partition_format=config.partition_format,
        sort_mode="asc",
    )
