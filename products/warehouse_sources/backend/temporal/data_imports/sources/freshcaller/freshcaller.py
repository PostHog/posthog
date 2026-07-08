import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, time
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import RetryCallState, retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.freshcaller.settings import (
    DEFAULT_START_DATETIME,
    FRESHCALLER_ENDPOINTS,
    PER_PAGE,
    FreshcallerEndpointConfig,
)

REQUEST_TIMEOUT = 60
VALIDATE_TIMEOUT = 10
MAX_RETRIES = 5
MAX_RETRY_WAIT = 60.0

_EXPONENTIAL_WAIT = wait_exponential_jitter(initial=1, max=MAX_RETRY_WAIT)


class FreshcallerRetryableError(Exception):
    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


def _parse_retry_after(value: str | None) -> float | None:
    """Parse a Retry-After header. Freshworks APIs send an integer number of seconds."""
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _retry_wait(retry_state: RetryCallState) -> float:
    """Honor a server-provided Retry-After (capped); otherwise fall back to exponential jitter."""
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    if isinstance(exc, FreshcallerRetryableError) and exc.retry_after is not None:
        return min(exc.retry_after, MAX_RETRY_WAIT)
    return _EXPONENTIAL_WAIT(retry_state)


@dataclasses.dataclass
class FreshcallerResumeConfig:
    # The next page number to fetch. Freshcaller uses page/per_page pagination, so a single
    # integer is enough to pick back up. The time window (by_time[from]/by_time[to]) is rebuilt
    # from the incremental watermark on resume — `from` is the stable DB watermark and `to` is
    # "now", so re-entering the same window and deduping on `id` is safe.
    page: int


def normalize_subdomain(domain: str) -> str:
    """Accept either a bare account name ("acme") or a full host ("acme.freshcaller.com")."""
    domain = domain.strip().removeprefix("https://").removeprefix("http://")
    domain = domain.split("/")[0]
    return domain.removesuffix(".freshcaller.com")


def _base_url(subdomain: str) -> str:
    return f"https://{normalize_subdomain(subdomain)}.freshcaller.com"


def _get_headers(api_key: str) -> dict[str, str]:
    # Freshcaller authenticates with a single API key in the X-Api-Auth header. The Accept header
    # is required — the API 404s the route when it's `*/*`.
    return {"X-Api-Auth": api_key, "Accept": "application/json"}


def _format_datetime(value: Any) -> str:
    """Format an incremental cursor value as the ISO 8601 UTC (Z-suffixed) string Freshcaller expects."""
    if isinstance(value, datetime):
        utc = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return datetime.combine(value, time(), tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


def build_base_params(
    config: FreshcallerEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> dict[str, str]:
    """Query params shared across every page of one sync (everything except `page`)."""
    params: dict[str, str] = {"per_page": str(PER_PAGE)}
    params.update(config.extra_params)

    if should_use_incremental_field and config.supports_incremental:
        # `by_time` requires both bounds together; window is [watermark, now]. Without a watermark
        # (first sync) fall back to the configured backfill floor instead of scanning all history.
        start = _format_datetime(db_incremental_field_last_value) if db_incremental_field_last_value else None
        params["by_time[from]"] = start or DEFAULT_START_DATETIME
        params["by_time[to]"] = _format_datetime(datetime.now(UTC))

    return params


def extract_items(data: Any, config: FreshcallerEndpointConfig) -> list[dict]:
    """Freshcaller wraps each list under its plural resource key (e.g. {"users": [...]})."""
    if isinstance(data, dict):
        value = data.get(config.data_key)
        if isinstance(value, list):
            return value
    if isinstance(data, list):
        return data
    return []


def extract_meta(data: Any) -> dict:
    if isinstance(data, dict) and isinstance(data.get("meta"), dict):
        return data["meta"]
    return {}


def _has_next_page(meta: dict, items: list[dict], page: int) -> bool:
    if not items:
        return False
    total_pages = meta.get("total_pages")
    if isinstance(total_pages, int):
        current = meta.get("current")
        current_page = current if isinstance(current, int) else page
        return current_page < total_pages
    # No usable meta -> a full page implies there may be more.
    return len(items) >= PER_PAGE


def get_rows(
    api_key: str,
    subdomain: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[FreshcallerResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict]]:
    config = FRESHCALLER_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)
    base = _base_url(subdomain)
    base_params = build_base_params(config, should_use_incremental_field, db_incremental_field_last_value)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page = resume.page if resume is not None else 1
    if resume is not None:
        logger.debug(f"Freshcaller: resuming {endpoint} from page {page}")

    # One session reused across pages so urllib3 keeps the connection alive. `redact_values` masks
    # the API key from captured HTTP samples: it rides in the `X-Api-Auth` header, which the
    # name-based sample scrubbers don't recognise.
    session = make_tracked_session(redact_values=(api_key,))

    @retry(
        retry=retry_if_exception_type((FreshcallerRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRIES),
        wait=_retry_wait,
        reraise=True,
    )
    def fetch_page(page_url: str) -> Any:
        response = session.get(page_url, headers=headers, timeout=REQUEST_TIMEOUT)

        # Freshcaller throttles per plan tier with 429; honor Retry-After when present.
        if response.status_code == 429:
            raise FreshcallerRetryableError(
                f"Freshcaller API rate limited: url={page_url}",
                retry_after=_parse_retry_after(response.headers.get("Retry-After")),
            )

        if response.status_code >= 500:
            raise FreshcallerRetryableError(
                f"Freshcaller API error (retryable): status={response.status_code}, url={page_url}"
            )

        if not response.ok:
            logger.error(f"Freshcaller API error: status={response.status_code}, body={response.text}, url={page_url}")
            response.raise_for_status()

        return response.json()

    while True:
        params = {**base_params, "page": str(page)}
        url = f"{base}{config.path}?{urlencode(params)}"

        data = fetch_page(url)
        items = extract_items(data, config)
        if items:
            yield items

        if not _has_next_page(extract_meta(data), items, page):
            break

        # Advance and save AFTER yielding so the just-written page is durable before we bookmark
        # the next one; a crash re-fetches from `page` and merge dedupes on the primary key.
        page += 1
        resumable_source_manager.save_state(FreshcallerResumeConfig(page=page))


def freshcaller_source(
    api_key: str,
    subdomain: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[FreshcallerResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> SourceResponse:
    config = FRESHCALLER_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            subdomain=subdomain,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=["id"],
        partition_count=1 if config.partition_key else None,
        partition_size=1 if config.partition_key else None,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # Freshcaller list endpoints expose no sort param and don't document their default order.
        # For incremental endpoints we page the full [watermark, now] window each sync and dedupe
        # on `id`, so declaring "desc" defers the watermark commit to end-of-sync — keeping the
        # cursor correct regardless of the API's actual intra-window ordering. Full-refresh
        # endpoints carry no watermark, so the mode is irrelevant there.
        sort_mode="desc" if config.supports_incremental else "asc",
    )


def validate_credentials(subdomain: str, api_key: str) -> Optional[int]:
    """Probe the Freshcaller API. Returns the HTTP status code, or ``None`` on a connection error."""
    url = f"{_base_url(subdomain)}/api/v1/users?per_page=1"
    try:
        response = make_tracked_session(redact_values=(api_key,)).get(
            url, headers=_get_headers(api_key), timeout=VALIDATE_TIMEOUT
        )
    except Exception:
        return None

    return response.status_code
