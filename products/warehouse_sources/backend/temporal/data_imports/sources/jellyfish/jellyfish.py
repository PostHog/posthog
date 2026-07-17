import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter
from urllib3.util.retry import Retry

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.jellyfish.settings import (
    DEFAULT_LOOKBACK_MONTHS,
    JELLYFISH_ENDPOINTS,
    JellyfishEndpointConfig,
)

JELLYFISH_BASE_URL = "https://app.jellyfish.co/endpoints/export/v0"
# The export API has no pagination, so a whole window/list comes back in one response — allow it
# time to build.
REQUEST_TIMEOUT = 120
MAX_RETRIES = 5
# Cap the honored `Retry-After` so a pathological header can't pin an import worker for its whole
# duration; the pipeline retries the activity above us if the window is genuinely longer.
MAX_RETRY_AFTER_SECONDS = 60
# The tenacity loop below is the single retry authority — it translates 429/5xx into typed
# exceptions and backs off (honoring `Retry-After`). Adapter-level retries would nest beneath it and
# multiply the waits, so opt out of them.
_NO_ADAPTER_RETRIES = Retry(total=0)


class JellyfishRetryableError(Exception):
    """Transient 5xx — safe to retry with backoff."""


class JellyfishRateLimitError(Exception):
    """429 Too Many Requests. Carries the server's Retry-After (seconds) so we can honor it."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


@dataclasses.dataclass
class JellyfishResumeConfig:
    # Month-windowed endpoints: the ISO date of the next window to fetch. None = start from the
    # beginning of the lookback range.
    next_window_start: str | None = None
    # Fan-out endpoint (deliverables): work category slugs already fully fetched this job.
    completed_slugs: list[str] = dataclasses.field(default_factory=list)


def _get_headers(api_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Token {api_token}",
        "Accept": "application/json",
    }


def _build_url(path: str, params: dict[str, Any]) -> str:
    base = f"{JELLYFISH_BASE_URL}/{path}"
    if not params:
        return base
    return f"{base}?{urlencode(params)}"


def _month_windows(today: date, lookback_months: int = DEFAULT_LOOKBACK_MONTHS) -> list[tuple[date, date]]:
    """Calendar-month `[first day, last day]` windows from `lookback_months` ago through today.

    The current month's window is clipped to today. `end_date` is assumed inclusive (the API is
    not publicly documented either way); with whole-month windows an off-by-one would at most drop
    or double a single boundary day, and full-refresh syncs restate every window each run.
    """
    start = date(today.year, today.month, 1)
    months: list[date] = []
    for _ in range(lookback_months):
        months.append(start)
        start = (start - timedelta(days=1)).replace(day=1)
    months.reverse()

    windows: list[tuple[date, date]] = []
    for first_day in months:
        next_month = (first_day + timedelta(days=32)).replace(day=1)
        last_day = next_month - timedelta(days=1)
        windows.append((first_day, min(last_day, today)))
    return windows


def _extract_rows(payload: Any, data_key: str | None = None) -> list[dict[str, Any]]:
    """Pull the row list out of a response whose exact wrapping isn't publicly documented.

    Known shapes are handled first (`data_key`, bare list); otherwise a dict with exactly one
    list-of-dicts value unwraps to that list, and anything else is kept whole as a single row
    rather than guessed at.
    """
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]

    if isinstance(payload, dict):
        if data_key is not None:
            wrapped = payload.get(data_key)
            if isinstance(wrapped, list):
                return [row for row in wrapped if isinstance(row, dict)]

        list_values = [
            value
            for value in payload.values()
            if isinstance(value, list) and value and all(isinstance(item, dict) for item in value)
        ]
        if len(list_values) == 1:
            return list_values[0]

        return [payload]

    return []


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        seconds = float(value)
    except ValueError:
        return None
    # A negative (or non-numeric) value is meaningless as a wait, so fall back to exponential backoff.
    return seconds if seconds >= 0 else None


def _retry_wait(retry_state: Any) -> float:
    """Honor a 429's Retry-After header when present (capped), else fall back to exponential backoff."""
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    if isinstance(exc, JellyfishRateLimitError) and exc.retry_after is not None:
        return min(exc.retry_after, MAX_RETRY_AFTER_SECONDS)
    return wait_exponential_jitter(initial=1, max=30)(retry_state)


@retry(
    retry=retry_if_exception_type(
        (JellyfishRetryableError, JellyfishRateLimitError, requests.ReadTimeout, requests.ConnectionError)
    ),
    stop=stop_after_attempt(MAX_RETRIES),
    wait=_retry_wait,
    reraise=True,
)
def _fetch(session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger) -> Any:
    response = session.get(url, headers=headers, timeout=REQUEST_TIMEOUT)

    if response.status_code == 429:
        raise JellyfishRateLimitError(
            f"Jellyfish API rate limited: url={url}",
            retry_after=_parse_retry_after(response.headers.get("Retry-After")),
        )

    if response.status_code >= 500:
        raise JellyfishRetryableError(f"Jellyfish API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Jellyfish API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def validate_credentials(api_token: str) -> bool:
    # `delivery/work_categories` is the cheapest export endpoint (a short reference list, no
    # required params). Jellyfish returns 403 for both missing and invalid tokens (verified live),
    # so any non-200 means the token isn't usable.
    url = _build_url("delivery/work_categories", {"format": "json"})
    try:
        session = make_tracked_session(retry=_NO_ADAPTER_RETRIES)
        response = session.get(url, headers=_get_headers(api_token), timeout=30)
        return response.status_code == 200
    except Exception:
        return False


def _list_work_category_slugs(
    session: requests.Session, headers: dict[str, str], logger: FilteringBoundLogger
) -> list[str]:
    payload = _fetch(session, _build_url("delivery/work_categories", {"format": "json"}), headers, logger)
    rows = _extract_rows(payload)
    slugs: list[str] = []
    for row in rows:
        # Work category rows carry a slug/id (the field name isn't publicly documented; `slug` is
        # what `work_category_slug` params take, so prefer it).
        slug = row.get("slug") or row.get("work_category_slug") or row.get("id")
        if slug is not None:
            slugs.append(str(slug))
    if not slugs and rows:
        logger.error(f"Jellyfish: could not find a slug field in work_categories rows: keys={sorted(rows[0])}")
    return slugs


def get_rows(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[JellyfishResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = JELLYFISH_ENDPOINTS[endpoint]
    headers = _get_headers(api_token)
    session = make_tracked_session(retry=_NO_ADAPTER_RETRIES)

    # The export API returns CSV unless asked otherwise, so `format=json` goes on every request.
    base_params: dict[str, Any] = {"format": "json", **config.params}

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    today = datetime.now(UTC).date()

    if config.window_mode == "month":
        yield from _get_month_windowed_rows(
            session, headers, logger, config, base_params, resumable_source_manager, resume, today
        )
    elif config.fan_out_slug_param is not None:
        yield from _get_fan_out_rows(
            session, headers, logger, config, base_params, resumable_source_manager, resume, today
        )
    else:
        payload = _fetch(session, _build_url(config.path, base_params), headers, logger)
        rows = _extract_rows(payload, config.data_key)
        if rows:
            yield rows


def _get_month_windowed_rows(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    config: JellyfishEndpointConfig,
    base_params: dict[str, Any],
    resumable_source_manager: ResumableSourceManager[JellyfishResumeConfig],
    resume: JellyfishResumeConfig | None,
    today: date,
) -> Iterator[list[dict[str, Any]]]:
    windows = _month_windows(today)
    if resume is not None and resume.next_window_start:
        windows = [w for w in windows if w[0].isoformat() >= resume.next_window_start]
        logger.debug(f"Jellyfish: resuming {config.name} from window {resume.next_window_start}")

    for index, (window_start, window_end) in enumerate(windows):
        params = {
            **base_params,
            "start_date": window_start.isoformat(),
            "end_date": window_end.isoformat(),
            "unit": "month",
        }
        payload = _fetch(session, _build_url(config.path, params), headers, logger)
        rows = _extract_rows(payload, config.data_key)
        for row in rows:
            # Stamp the requested window so per-period aggregates keep their period (and give the
            # table its stable partition key).
            row.setdefault("window_start_date", window_start.isoformat())
            row.setdefault("window_end_date", window_end.isoformat())
        if rows:
            yield rows

        # Save AFTER yielding so a crash re-fetches this window instead of skipping it.
        if index + 1 < len(windows):
            resumable_source_manager.save_state(
                JellyfishResumeConfig(next_window_start=windows[index + 1][0].isoformat())
            )


def _get_fan_out_rows(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    config: JellyfishEndpointConfig,
    base_params: dict[str, Any],
    resumable_source_manager: ResumableSourceManager[JellyfishResumeConfig],
    resume: JellyfishResumeConfig | None,
    today: date,
) -> Iterator[list[dict[str, Any]]]:
    slugs = _list_work_category_slugs(session, headers, logger)
    completed = set(resume.completed_slugs) if resume is not None else set()
    if completed:
        logger.debug(f"Jellyfish: resuming {config.name}, skipping {len(completed)} completed work categories")

    # Deliverables are discrete records, so one wide window over the whole lookback range per work
    # category (rather than per-month slices) fetches each deliverable once.
    window_start = _month_windows(today)[0][0]

    for slug in slugs:
        if slug in completed:
            continue
        assert config.fan_out_slug_param is not None
        params = {
            **base_params,
            config.fan_out_slug_param: slug,
            "start_date": window_start.isoformat(),
            "end_date": today.isoformat(),
        }
        payload = _fetch(session, _build_url(config.path, params), headers, logger)
        rows = _extract_rows(payload, config.data_key)
        for row in rows:
            row.setdefault("work_category_slug", slug)
        if rows:
            yield rows

        completed.add(slug)
        resumable_source_manager.save_state(JellyfishResumeConfig(completed_slugs=sorted(completed)))


def jellyfish_source(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[JellyfishResumeConfig],
) -> SourceResponse:
    config = JELLYFISH_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_token=api_token,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=config.primary_keys,
        partition_count=1 if config.partition_key else None,
        partition_size=1 if config.partition_key else None,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode="asc",
    )
