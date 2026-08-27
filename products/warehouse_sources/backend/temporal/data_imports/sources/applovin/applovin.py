import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.sources.applovin.settings import (
    APPLOVIN_API_BASE_URL,
    APPLOVIN_ENDPOINTS,
    MAX_REQUEST_WINDOW_DAYS,
    REPORT_LOOKBACK_DAYS,
    REPORT_PAGE_SIZE,
    REPORT_WINDOW_DAYS,
    AppLovinEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http.url_utils import redact_literal_values
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

REQUEST_TIMEOUT_SECONDS = 120
VALIDATION_TIMEOUT_SECONDS = 30

# Matched by `AppLovinSource.get_non_retryable_errors`, so keep these stable.
AUTH_ERROR_PREFIX = "AppLovin denied the request"
BAD_REQUEST_ERROR_PREFIX = "AppLovin rejected the report request"
# Deliberately NOT registered as non-retryable: the tracked session already retried the request,
# and an upstream outage must not permanently disable the source.
TRANSIENT_ERROR_PREFIX = "AppLovin API error (retryable)"

_AUTH_STATUS_CODES = (401, 403)


class AppLovinAPIError(Exception):
    pass


def _utc_today() -> date:
    return datetime.now(tz=UTC).date()


def _redacted(message: str, api_key: str) -> str:
    """Strip the Report Key out of a message before it can reach a user-visible error.

    A transport error quotes the request URL, where the key is URL-encoded, so redact the
    raw, percent-encoded, and plus-encoded forms via the shared value-based masker.
    """
    return redact_literal_values(message, (api_key,)) if api_key else message


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


def _body_code(body: Any) -> Optional[int]:
    """AppLovin echoes its own status in the JSON body's `code` key; 200 means success."""
    if not isinstance(body, dict):
        return None
    try:
        return int(body["code"])
    except (KeyError, TypeError, ValueError):
        return None


def _is_transient_status(status_code: int) -> bool:
    """Throttling and upstream failures, which the source must keep retrying."""
    return status_code == 429 or status_code >= 500


def _prefix_for_code(code: int) -> str:
    if code in _AUTH_STATUS_CODES:
        return AUTH_ERROR_PREFIX
    if _is_transient_status(code):
        return TRANSIENT_ERROR_PREFIX
    return BAD_REQUEST_ERROR_PREFIX


def _build_url(config: AppLovinEndpointConfig, api_key: str, start: date, end: date, offset: int) -> str:
    params: dict[str, Any] = {
        "api_key": api_key,
        "columns": ",".join(config.columns),
        "start": start.isoformat(),
        "end": end.isoformat(),
        "format": "json",
        "limit": REPORT_PAGE_SIZE,
        "offset": offset,
        # Pin the order so limit/offset paging can't reshuffle rows between pages, and so rows
        # arrive oldest-first (`sort_mode="asc"` on the response).
        "sort_day": "ASC",
        **config.extra_params,
    }
    return f"{APPLOVIN_API_BASE_URL}{config.path}?{urlencode(params)}"


def _fetch_page(
    session: requests.Session,
    config: AppLovinEndpointConfig,
    api_key: str,
    start: date,
    end: date,
    offset: int,
    logger: FilteringBoundLogger,
) -> list[dict[str, Any]]:
    url = _build_url(config, api_key, start, end, offset)

    try:
        response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
    except requests.RequestException as e:
        # `requests`/`urllib3` transport errors quote the full request URL, which carries the
        # Report Key as a query param. Re-raise redacted, and drop the cause so the original
        # (unredacted) message can't be surfaced through the exception chain.
        raise AppLovinAPIError(f"AppLovin request failed: {_redacted(str(e), api_key)}") from None

    if response.status_code in _AUTH_STATUS_CODES:
        raise AppLovinAPIError(f"{AUTH_ERROR_PREFIX}: status={response.status_code}, endpoint={config.path}")

    if _is_transient_status(response.status_code):
        raise AppLovinAPIError(f"{TRANSIENT_ERROR_PREFIX}: status={response.status_code}, endpoint={config.path}")

    if not response.ok:
        raise AppLovinAPIError(
            f"{BAD_REQUEST_ERROR_PREFIX}: status={response.status_code}, endpoint={config.path}, "
            f"body={_redacted(response.text, api_key)[:500]}"
        )

    try:
        body = response.json()
    except ValueError:
        raise AppLovinAPIError(
            f"{BAD_REQUEST_ERROR_PREFIX}: endpoint={config.path} returned a non-JSON body: "
            f"{_redacted(response.text, api_key)[:500]}"
        ) from None

    code = _body_code(body)
    if code is not None and code != 200:
        raise AppLovinAPIError(f"{_prefix_for_code(code)}: body code={code}, endpoint={config.path}")

    results = body.get("results") if isinstance(body, dict) else None
    if not isinstance(results, list):
        logger.debug(f"AppLovin: {config.name} returned no results list for {start.isoformat()}..{end.isoformat()}")
        return []

    return [row for row in results if isinstance(row, dict)]


@dataclasses.dataclass
class AppLovinResumeConfig:
    # First day (YYYY-MM-DD) of the report window still being fetched.
    next_window_start: Optional[str] = None
    # `offset` of the next unfetched page within that window.
    next_offset: int = 0


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: "ResumableSourceManager[AppLovinResumeConfig]",
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = APPLOVIN_ENDPOINTS[endpoint]
    session = make_tracked_session(redact_values=(api_key,))

    today = _utc_today()
    # The API refuses dates older than the request window, so clamp every start to it rather
    # than letting a stale watermark produce a guaranteed error.
    earliest = today - timedelta(days=MAX_REQUEST_WINDOW_DAYS - 1)

    start = earliest
    if should_use_incremental_field:
        watermark = _to_date(db_incremental_field_last_value)
        if watermark is not None:
            start = max(earliest, watermark - timedelta(days=REPORT_LOOKBACK_DAYS))

    offset = 0
    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume_config is not None and resume_config.next_window_start:
        resumed = _to_date(resume_config.next_window_start)
        if resumed is not None and earliest <= resumed <= today and resumed >= start:
            start = resumed
            offset = resume_config.next_offset
            logger.debug(f"AppLovin: resuming {endpoint} from {start.isoformat()} offset {offset}")

    while start <= today:
        window_end = min(start + timedelta(days=REPORT_WINDOW_DAYS - 1), today)

        while True:
            rows = _fetch_page(session, config, api_key, start, window_end, offset, logger)
            if rows:
                yield rows

            # A short page means the window is exhausted: AppLovin returns an empty set once
            # `offset` passes the total row count.
            if len(rows) < REPORT_PAGE_SIZE:
                break

            offset += REPORT_PAGE_SIZE
            # Saved after yielding so a crash re-yields the in-flight page instead of skipping
            # it (the merge dedupes on the dimension primary key).
            resumable_source_manager.save_state(
                AppLovinResumeConfig(next_window_start=start.isoformat(), next_offset=offset)
            )

        start = window_end + timedelta(days=1)
        offset = 0
        if start <= today:
            resumable_source_manager.save_state(
                AppLovinResumeConfig(next_window_start=start.isoformat(), next_offset=0)
            )

    # The whole window is walked, so drop the checkpoint rather than leaving a later attempt to
    # resume from the final report window.
    resumable_source_manager.clear_state()


def validate_credentials(api_key: str) -> bool:
    """Confirm the Report Key is accepted by at least one reporting endpoint.

    A key belonging to a publisher-only account and one belonging to an advertiser-only account
    both authenticate against `/maxReport` and `/report`, so a single probe would reject a valid
    key for the other account shape. Probe both and accept the first success.
    """
    session = make_tracked_session(redact_values=(api_key,))
    today = _utc_today()

    for path, extra_params in (("/maxReport", {}), ("/report", {"report_type": "publisher"})):
        params: dict[str, Any] = {
            "api_key": api_key,
            "columns": "day,impressions",
            "start": today.isoformat(),
            "end": today.isoformat(),
            "format": "json",
            "limit": 1,
            **extra_params,
        }
        try:
            response = session.get(
                f"{APPLOVIN_API_BASE_URL}{path}?{urlencode(params)}", timeout=VALIDATION_TIMEOUT_SECONDS
            )
            if not response.ok:
                continue
            code = _body_code(response.json())
        except Exception:  # noqa: BLE001 — a credential probe must never raise out of source create
            continue

        if code is None or code == 200:
            return True

    return False


def applovin_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: "ResumableSourceManager[AppLovinResumeConfig]",
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = APPLOVIN_ENDPOINTS[endpoint]

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
        primary_keys=list(config.primary_keys),
        partition_count=1,
        partition_size=1,
        # Windows are walked oldest-first and each request pins `sort_day=ASC`, so `day` only
        # ever moves forward; the restatement re-pull happens below the saved watermark and
        # merges on the dimension primary key.
        sort_mode="asc",
    )
