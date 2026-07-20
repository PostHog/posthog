import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode, urlparse

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.campfire.settings import (
    CAMPFIRE_BASE_URL,
    CAMPFIRE_ENDPOINTS,
    CampfireEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

# Bound the paginator so a misbehaving `next` chain can't loop forever.
MAX_PAGES = 100_000


class CampfireRetryableError(Exception):
    pass


@dataclasses.dataclass
class CampfireResumeConfig:
    # The `next` link of the last fully-yielded page. Absolute URL on api.meetcampfire.com,
    # carrying the pagination cursor/offset plus any incremental filter for this job.
    next_url: str


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Token {api_key}",
        "Accept": "application/json",
    }


def _format_incremental_value(value: Any) -> str:
    """Format the watermark for `last_modified_at__gte`, which accepts ISO 8601."""
    if isinstance(value, datetime):
        utc_value = value.astimezone(UTC) if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return utc_value.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _build_first_url(
    config: CampfireEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
) -> str:
    params: dict[str, Any] = {"limit": config.page_size, **config.extra_params}
    if config.use_cursor:
        # An empty `cursor=` opts the endpoint into cursor pagination; every later page
        # comes from the response's `next` link.
        params["cursor"] = ""
    if should_use_incremental_field and config.incremental_fields and db_incremental_field_last_value is not None:
        params["last_modified_at__gte"] = _format_incremental_value(db_incremental_field_last_value)
    return f"{CAMPFIRE_BASE_URL}{config.path}?{urlencode(params)}"


def _validate_next_url(next_url: str) -> None:
    """Only follow `next` links that stay on the Campfire API host.

    The API key rides in a header on every request, so following an off-host link would
    hand the credential to whatever host the response named.
    """
    parsed = urlparse(next_url)
    expected = urlparse(CAMPFIRE_BASE_URL)
    if parsed.scheme != "https" or parsed.netloc != expected.netloc:
        raise ValueError(f"Campfire returned a next link on an unexpected host: {parsed.netloc!r}")


@retry(
    retry=retry_if_exception_type(
        (
            CampfireRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    url: str,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
) -> Any:
    response = session.get(url, headers=headers, timeout=60)

    if response.status_code == 429 or response.status_code >= 500:
        raise CampfireRetryableError(f"Campfire API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        # Log status and URL only — error bodies can echo request data from an accounting
        # system, which must not spill into application logs.
        logger.error(f"Campfire API error: status={response.status_code}, url={url}")
        response.raise_for_status()

    return response.json()


def _parse_page(data: Any) -> tuple[list[dict[str, Any]], str | None]:
    """Split a response into (rows, next link) for both DRF envelopes and bare lists."""
    if isinstance(data, dict):
        results = data.get("results") or []
        return results, data.get("next")
    if isinstance(data, list):
        return data, None
    return [], None


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CampfireResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> Iterator[list[dict[str, Any]]]:
    config = CAMPFIRE_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)
    # One session reused across every page so urllib3 keeps the connection alive.
    # capture=False keeps accounting responses (amounts, invoice/transaction IDs, free-form
    # business fields the name-based scrubbers can't recognise) out of HTTP sample storage.
    session = make_tracked_session(redact_values=(api_key,), capture=False)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.next_url:
        _validate_next_url(resume.next_url)
        url = resume.next_url
        logger.debug(f"Campfire: resuming {endpoint} from URL: {url}")
    else:
        url = _build_first_url(config, should_use_incremental_field, db_incremental_field_last_value)

    pages = 0
    while True:
        data = _fetch_page(session, url, headers, logger)
        results, next_url = _parse_page(data)
        if next_url is not None:
            _validate_next_url(next_url)

        if results:
            yield results
            # Save AFTER yielding (and only when more pages remain) so a crash re-yields the
            # last page rather than skipping it — merge dedupes on the primary key.
            if next_url:
                resumable_source_manager.save_state(CampfireResumeConfig(next_url=next_url))

        if not next_url:
            break

        url = next_url
        pages += 1
        if pages >= MAX_PAGES:
            logger.error(f"Campfire: page cap of {MAX_PAGES} reached for endpoint {endpoint}; truncating sync")
            break


def campfire_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CampfireResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = CAMPFIRE_ENDPOINTS[endpoint]

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
        primary_keys=config.primary_keys,
        # "desc" endpoints persist the incremental watermark only at successful job end —
        # their response order is undocumented, so per-batch persistence could advance the
        # watermark past rows a crashed run still owes.
        sort_mode=config.sort_mode,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def validate_credentials(api_key: str, path: str | None = None) -> bool:
    """Probe the key with the cheapest call on the given endpoint (chart of accounts when
    unset — every Campfire role, including view-only, can GET it)."""
    probe_path = path or CAMPFIRE_ENDPOINTS["chart_of_accounts"].path
    try:
        response = make_tracked_session(redact_values=(api_key,), capture=False).get(
            f"{CAMPFIRE_BASE_URL}{probe_path}?{urlencode({'limit': 1})}",
            headers=_get_headers(api_key),
            timeout=10,
        )
        return response.status_code == 200
    except Exception:
        return False
