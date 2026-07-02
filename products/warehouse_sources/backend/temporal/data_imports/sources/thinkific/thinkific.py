import re
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.thinkific.settings import THINKIFIC_ENDPOINTS

THINKIFIC_BASE_URL = "https://api.thinkific.com/api/public/v1"

# Thinkific subdomains are the `<subdomain>.thinkific.com` slug, sent as the X-Auth-Subdomain header.
_SUBDOMAIN_RE = re.compile(r"^[a-zA-Z0-9-]+$")


class ThinkificRetryableError(Exception):
    pass


@dataclasses.dataclass
class ThinkificResumeConfig:
    # 1-based page number to fetch next. Thinkific paginates by page number (meta.pagination), so the
    # page index is the only state needed to resume an endpoint mid-sync.
    next_page: int


def is_valid_subdomain(subdomain: str) -> bool:
    return bool(_SUBDOMAIN_RE.match(subdomain))


def _get_headers(api_key: str, subdomain: str) -> dict[str, str]:
    return {
        "X-Auth-API-Key": api_key,
        "X-Auth-Subdomain": subdomain,
        "Accept": "application/json",
    }


def _format_incremental_date(value: Any) -> str:
    """Thinkific's query[updated_*] filters take an ISO 8601 *date* (day granularity), so we reduce
    the stored cursor (a datetime watermark) to its UTC date."""
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return aware.astimezone(UTC).date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    # Already a string cursor (e.g. an ISO timestamp) - keep the leading date portion.
    return str(value)[:10]


def _build_base_params(
    page_size: int,
    supports_incremental: bool,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> dict[str, Any]:
    params: dict[str, Any] = {"limit": page_size}

    if supports_incremental and should_use_incremental_field and db_incremental_field_last_value is not None:
        # Inclusive, day-granularity filter on `updated_at`: re-fetch the whole boundary day so
        # updates that landed after the watermark within the same day aren't skipped. Re-pulled rows
        # are deduped by the primary key on merge. We deliberately use `updated_on_or_after` rather
        # than the exclusive `updated_after` to avoid that same-day gap.
        params["query[updated_on_or_after]"] = _format_incremental_date(db_incremental_field_last_value)

    return params


@retry(
    retry=retry_if_exception_type((ThinkificRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=60),
    reraise=True,
)
def _fetch_page(
    session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> dict[str, Any]:
    # allow_redirects=False so a server-side 3xx can never forward the X-Auth-API-Key/Subdomain
    # credential headers to another host. Pagination already targets the fixed THINKIFIC_BASE_URL
    # (by page number, never a response-supplied URL), so legitimate responses are always 2xx.
    response = session.get(url, headers=headers, timeout=60, allow_redirects=False)

    # 429 carries a RateLimit-Reset epoch header; tenacity's exponential backoff is a safe fallback
    # without parsing it. Transient 5xx are likewise retried.
    if response.status_code == 429 or response.status_code >= 500:
        raise ThinkificRetryableError(f"Thinkific API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Thinkific API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def get_rows(
    api_key: str,
    subdomain: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ThinkificResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[Any]:
    config = THINKIFIC_ENDPOINTS[endpoint]
    headers = _get_headers(api_key, subdomain)
    # One session reused across every page so urllib3 keeps the connection alive instead of
    # re-handshaking per request. `redact_values` masks the API key wherever it lands (the
    # X-Auth-API-Key header isn't on the name-based scrub denylist) in logs and sample capture.
    session = make_tracked_session(redact_values=(api_key,))

    base_params = _build_base_params(
        config.page_size,
        config.supports_incremental,
        should_use_incremental_field,
        db_incremental_field_last_value,
    )

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page = resume.next_page if resume else 1
    if resume is not None:
        logger.debug(f"Thinkific: resuming {endpoint} from page {page}")

    while True:
        url = f"{THINKIFIC_BASE_URL}{config.path}?{urlencode({**base_params, 'page': page})}"
        data = _fetch_page(session, url, headers, logger)

        # Thinkific wraps every list response as {"items": [...], "meta": {"pagination": {...}}};
        # records carry their fields at the top level (no JSON:API attributes envelope).
        items = data.get("items", [])
        if not items:
            break

        next_page = data.get("meta", {}).get("pagination", {}).get("next_page")

        # Yield the page's rows directly - the pipeline batches/buffers for us, so we don't run our
        # own Batcher here. One yield per page keeps resume checkpoints page-aligned.
        yield items

        if not next_page:
            break

        # Save AFTER yielding the page so a crash re-yields starting at next_page (merge dedupes on
        # the primary key) rather than skipping it.
        resumable_source_manager.save_state(ThinkificResumeConfig(next_page=next_page))
        page = next_page


def thinkific_source(
    api_key: str,
    subdomain: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ThinkificResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = THINKIFIC_ENDPOINTS[endpoint]

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
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # The public API exposes no sort parameter; list endpoints return id-ascending (≈ creation
        # order). Incremental enrollments sync stays correct regardless of exact ordering because the
        # day-granularity filter is inclusive and merge dedupes on the primary key.
        sort_mode="asc",
    )


def validate_credentials(api_key: str, subdomain: str, endpoint_path: str = "/courses") -> tuple[bool, int | None]:
    """Cheap probe to confirm the API key + subdomain are genuine. Returns (is_valid, status_code);
    status_code is None when the request never completed."""
    url = f"{THINKIFIC_BASE_URL}{endpoint_path}?{urlencode({'page': 1, 'limit': 1})}"
    try:
        session = make_tracked_session(redact_values=(api_key,))
        response = session.get(url, headers=_get_headers(api_key, subdomain), timeout=10, allow_redirects=False)
        return response.status_code == 200, response.status_code
    except Exception:
        return False, None
