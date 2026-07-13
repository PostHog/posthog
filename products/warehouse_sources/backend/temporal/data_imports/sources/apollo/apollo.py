import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from email.utils import parsedate_to_datetime
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import RetryCallState, retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.apollo.settings import APOLLO_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

APOLLO_BASE_URL = "https://api.apollo.io/api/v1"
# Search pages cap at 100 records and 500 pages (50k records per query).
PAGE_SIZE = 100
MAX_PAGES = 500
REQUEST_TIMEOUT_SECONDS = 60
# Rate limits are plan-dependent fixed windows; back off on 429.
MAX_RETRY_ATTEMPTS = 5
# Cap how long a single in-function retry waits so a long fixed-window (hourly/daily)
# Retry-After doesn't pin a worker thread; if the window is longer, the attempts
# exhaust and Temporal retries the whole activity later from saved page state.
MAX_RETRY_AFTER_SECONDS = 120


class ApolloRetryableError(Exception):
    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


@dataclasses.dataclass
class ApolloResumeConfig:
    # Search endpoints paginate with a 1-based page number; static body parts
    # are rebuilt deterministically from job inputs on resume.
    page: int


def _get_session(api_key: str) -> requests.Session:
    return make_tracked_session(headers={"X-Api-Key": api_key}, redact_values=(api_key,))


def _parse_timestamp(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
        except ValueError:
            return None
    return None


def _parse_retry_after(value: str | None) -> Optional[float]:
    # Retry-After is either delta-seconds or an HTTP-date (RFC 7231).
    if not value:
        return None
    value = value.strip()
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        retry_at = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=UTC)
    return max(0.0, (retry_at - datetime.now(UTC)).total_seconds())


_backoff = wait_exponential_jitter(initial=5, max=120)


def _wait_apollo(retry_state: RetryCallState) -> float:
    # Prefer the server's own backoff instruction on rate limits; fall back to
    # exponential jitter when the header is absent (429 without one, or a 5xx).
    exc = retry_state.outcome.exception() if retry_state.outcome is not None else None
    if isinstance(exc, ApolloRetryableError) and exc.retry_after is not None:
        return min(exc.retry_after, MAX_RETRY_AFTER_SECONDS)
    return _backoff(retry_state)


def validate_credentials(api_key: str) -> bool:
    """Confirm the API key is valid with Apollo's auth health endpoint."""
    try:
        response = _get_session(api_key).get(
            f"{APOLLO_BASE_URL}/auth/health",
            timeout=10,
        )
        return response.status_code == 200 and bool(response.json().get("is_logged_in"))
    except Exception:
        return False


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ApolloResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = APOLLO_ENDPOINTS[endpoint]
    session = _get_session(api_key)
    url = f"{APOLLO_BASE_URL}{config.path}"

    watermark = _parse_timestamp(db_incremental_field_last_value) if should_use_incremental_field else None

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page = resume_config.page if resume_config is not None else 1
    if resume_config is not None:
        logger.debug(f"Apollo: resuming {endpoint} from page {page}")

    @retry(
        retry=retry_if_exception_type((ApolloRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=_wait_apollo,
        reraise=True,
    )
    def fetch_page(page_number: int) -> dict[str, Any]:
        body: dict[str, Any] = {"page": page_number, "per_page": PAGE_SIZE}
        if config.sort_by_field is not None:
            # Newest-first lets incremental runs stop at the watermark instead
            # of paging through history (and keeps full scans deterministic).
            body["sort_by_field"] = config.sort_by_field
            body["sort_ascending"] = False
        response = session.post(url, json=body, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code == 429 or response.status_code >= 500:
            retry_after = (
                _parse_retry_after(response.headers.get("Retry-After")) if response.status_code == 429 else None
            )
            raise ApolloRetryableError(
                f"Apollo API error (retryable): status={response.status_code}, url={url}",
                retry_after=retry_after,
            )

        if not response.ok:
            logger.error(f"Apollo API error: status={response.status_code}, body={response.text}, url={url}")
            response.raise_for_status()

        return response.json()

    while True:
        data = fetch_page(page)
        items = data.get(config.data_key, []) or []

        crossed_watermark = False
        if watermark is not None:
            fresh: list[dict[str, Any]] = []
            for item in items:
                item_ts = _parse_timestamp(item.get("updated_at"))
                if item_ts is None:
                    # No parseable updated_at: keep the record (the merge dedupes
                    # on primary key) rather than risk dropping a genuinely new
                    # row. It can't advance past the watermark, so it never
                    # triggers the early-exit on its own.
                    fresh.append(item)
                    continue
                if item_ts <= watermark:
                    crossed_watermark = True
                    break
                fresh.append(item)
            items = fresh

        if items:
            yield items

        if crossed_watermark or not items:
            break

        if page >= MAX_PAGES:
            # Apollo hard-caps search results at 500 pages / 50k records per query.
            # Checked before the total_pages break so the cap is never silent when
            # the last reachable page coincides with the reported total.
            logger.error(
                f"Apollo: hit the 50,000-record search cap on {endpoint}; older records are not retrievable "
                "without filter slicing"
            )
            break

        total_pages = (data.get("pagination") or {}).get("total_pages")
        if isinstance(total_pages, int) and page >= total_pages:
            break

        page += 1
        # Save state AFTER yielding the page so a crash re-yields the last page
        # (merge dedupes on primary key) rather than skipping it.
        resumable_source_manager.save_state(ApolloResumeConfig(page=page))


def apollo_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ApolloResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = APOLLO_ENDPOINTS[endpoint]

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
        primary_keys=[config.primary_key],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # Incremental streams walk newest-first; the pipeline commits desc
        # watermarks only when a run completes.
        sort_mode="desc" if config.sort_by_field else "asc",
    )
