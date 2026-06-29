import re
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter
from urllib3.util.retry import Retry

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SortMode, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.workable.settings import (
    PAGE_SIZE,
    WORKABLE_ENDPOINTS,
)

# Workable account subdomains are DNS labels — letters, digits and hyphens. Validating this before
# building the URL prevents host injection (e.g. a `subdomain` of `evil.com/` would otherwise retarget
# the request and exfiltrate the stored token).
_SUBDOMAIN_RE = re.compile(r"^[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?$")

DEFAULT_TIMEOUT = 60
RETRYABLE_STATUSES = {429, 500, 502, 503, 504}

# Maps the incremental cursor column to Workable's server-side time filter param. The column is
# `updated_at` / `created_at`; the filter is `updated_after` / `created_after`.
_TIME_FILTER_PARAM = {"updated_at": "updated_after", "created_at": "created_after"}


class WorkableRetryableError(Exception):
    pass


@dataclasses.dataclass
class WorkableResumeConfig:
    # Full `paging.next` URL to fetch next. `None` means start the endpoint from its first page.
    next_url: str | None = None


def _validate_subdomain(subdomain: str) -> str:
    subdomain = (subdomain or "").strip()
    if not _SUBDOMAIN_RE.match(subdomain):
        raise ValueError(
            "Invalid Workable subdomain. Use just the account subdomain from "
            "https://<subdomain>.workable.com (letters, digits and hyphens only)."
        )
    return subdomain


def _base_url(subdomain: str) -> str:
    return f"https://{_validate_subdomain(subdomain)}.workable.com/spi/v3"


def _get_headers(api_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_token}",
        "Accept": "application/json",
    }


def _format_datetime(value: Any) -> str:
    """Format an incremental cursor value as an ISO 8601 UTC timestamp with a `Z` suffix."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    elif isinstance(value, date):
        dt = datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    else:
        return str(value)
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _build_initial_url(
    subdomain: str,
    endpoint: str,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> str:
    config = WORKABLE_ENDPOINTS[endpoint]
    params: dict[str, Any] = {"limit": PAGE_SIZE}

    if config.supports_incremental and should_use_incremental_field and db_incremental_field_last_value is not None:
        # `updated_after` / `created_after` are the documented server-side filters. Honor the user's
        # chosen cursor field; default to `updated_at` so edits to existing rows are picked up.
        field_name = incremental_field or "updated_at"
        filter_param = _TIME_FILTER_PARAM.get(field_name, "updated_after")
        params[filter_param] = _format_datetime(db_incremental_field_last_value)

    return f"{_base_url(subdomain)}{config.path}?{urlencode(params)}"


@retry(
    retry=retry_if_exception_type((WorkableRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    # Workable allows ~10 requests / 10s and returns HTTP 429 past that. Back off well clear of the
    # window (≈2, 4, 8, 16s) rather than reading the X-Rate-Limit-Reset header, which keeps the retry
    # logic simple while still self-healing.
    wait=wait_exponential_jitter(initial=2, max=60),
    reraise=True,
)
def _fetch_page(session: requests.Session, url: str, logger: FilteringBoundLogger) -> dict:
    response = session.get(url, timeout=DEFAULT_TIMEOUT)

    if response.status_code in RETRYABLE_STATUSES:
        raise WorkableRetryableError(f"Workable API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Workable API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def get_rows(
    subdomain: str,
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[WorkableResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[list[dict[str, Any]]]:
    config = WORKABLE_ENDPOINTS[endpoint]
    # Tenacity owns retries (so it can honor the tight rate limit), so disable the adapter's own
    # status/transport retries to avoid retrying twice. One session is reused across every page so
    # the connection is kept alive.
    session = make_tracked_session(headers=_get_headers(api_token), retry=Retry(total=0), redact_values=(api_token,))

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.next_url:
        url = resume.next_url
        logger.debug(f"Workable: resuming {endpoint} from {url}")
    else:
        url = _build_initial_url(
            subdomain, endpoint, should_use_incremental_field, db_incremental_field_last_value, incremental_field
        )

    while True:
        data = _fetch_page(session, url, logger)
        items = data.get(config.data_key, [])
        # `paging.next` is a full URL that already carries the cursor params. Follow it verbatim.
        next_url = data.get("paging", {}).get("next")

        if items:
            yield items
            # Save state AFTER yielding so a crash re-yields the last page (merge dedupes on the
            # primary key) rather than skipping it. Only save when more pages remain.
            if next_url:
                resumable_source_manager.save_state(WorkableResumeConfig(next_url=next_url))

        if not next_url:
            break
        url = next_url


def _sort_mode_for(endpoint: str, should_use_incremental_field: bool, incremental_field: str | None) -> SortMode:
    """Pick the order the pipeline should assume rows arrive in.

    Workable paginates by `since_id` (ascending id, which tracks ascending `created_at`); it has no
    way to sort by `updated_at`. So when the cursor field is `created_at`, rows genuinely arrive in
    ascending cursor order and the watermark can advance per batch (`asc`). When the cursor is
    `updated_at`, arrival order is unrelated to the cursor, so we use `desc` — which defers the
    watermark commit to sync completion — to avoid advancing past unsynced rows on a partial failure.
    """
    if not should_use_incremental_field or not WORKABLE_ENDPOINTS[endpoint].supports_incremental:
        return "asc"
    return "asc" if incremental_field == "created_at" else "desc"


def workable_source(
    subdomain: str,
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[WorkableResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = WORKABLE_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            subdomain=subdomain,
            api_token=api_token,
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
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode=_sort_mode_for(endpoint, should_use_incremental_field, incremental_field),
    )


def validate_credentials(subdomain: str, api_token: str, path: str = "/jobs") -> tuple[int, bool]:
    """Probe a Workable endpoint. Returns ``(status_code, ok)``; ``status_code`` is ``0`` on a transport error."""
    try:
        url = f"{_base_url(subdomain)}{path}?{urlencode({'limit': 1})}"
        response = make_tracked_session(
            headers=_get_headers(api_token), retry=Retry(total=0), redact_values=(api_token,)
        ).get(url, timeout=DEFAULT_TIMEOUT)
        return response.status_code, response.ok
    except ValueError:
        # Invalid subdomain — surface as a non-transport failure.
        raise
    except Exception:
        return 0, False
