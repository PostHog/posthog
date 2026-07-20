import time
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode, urlsplit

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.better_stack.settings import (
    BETTER_STACK_BASE_URL,
    BETTER_STACK_ENDPOINTS,
    BetterStackEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

REQUEST_TIMEOUT_SECONDS = 60
# Better Stack publishes no fixed quota — 429s carry a Retry-After header; cap how long we honor it.
MAX_RETRY_AFTER_SECONDS = 60


class BetterStackRetryableError(Exception):
    pass


class BetterStackUntrustedURLError(Exception):
    pass


def _validate_pagination_url(url: str) -> str:
    """Pin every authenticated request to the Better Stack API origin.

    Both resumed `next_url` values (loaded from Redis) and upstream `pagination.next` URLs are
    followed verbatim with the customer's bearer token. Validating the scheme, host, and `/api/`
    path prefix keeps a poisoned resume state or a hostile upstream response from retargeting the
    request at another host and leaking the token (SSRF). Returns the URL unchanged when trusted.
    """
    parts = urlsplit(url)
    is_trusted = parts.scheme == "https" and parts.netloc == "uptime.betterstack.com" and parts.path.startswith("/api/")
    if not is_trusted:
        raise BetterStackUntrustedURLError(f"Refusing to follow pagination URL outside {BETTER_STACK_BASE_URL}/")
    return url


@dataclasses.dataclass
class BetterStackResumeConfig:
    # Full next-page URL from the response's `pagination.next` field (null on the last page). It
    # carries the page, per_page, and any `from` filter, so following it preserves the incremental
    # window on every page.
    next_url: str | None = None


def _get_headers(api_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_token}"}


def _build_url(base_url: str, params: dict[str, Any]) -> str:
    if not params:
        return base_url
    return f"{base_url}?{urlencode(params)}"


def _format_from_date(value: Any) -> str:
    """Format an incremental cursor value as the YYYY-MM-DD date the incidents `from` filter takes."""
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return aware.astimezone(UTC).date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _clamp_future_value_to_now(value: Any) -> Any:
    """Cap a future datetime/date cursor at now — asking for incidents newer than now is a no-op,
    so clamping keeps the filter sane if a future-dated record ever pushes the cursor forward."""
    now = datetime.now(UTC)
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return now if aware > now else value
    if isinstance(value, date):
        return now.date() if value > now.date() else value
    return value


def _build_initial_params(
    config: BetterStackEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> dict[str, Any]:
    params: dict[str, Any] = {"per_page": config.page_size}

    if config.supports_incremental and should_use_incremental_field and db_incremental_field_last_value:
        # The `from` filter is date-granular, so we re-fetch the watermark's whole day; merge on
        # the primary key dedupes the overlap.
        value = _clamp_future_value_to_now(db_incremental_field_last_value)
        params["from"] = _format_from_date(value)

    return params


def _flatten_item(item: dict[str, Any]) -> dict[str, Any]:
    """Flatten a JSON:API resource object's `attributes` into the root and keep `id`/`type`."""
    flattened = {k: v for k, v in item.items() if k != "attributes"}
    attributes = item.get("attributes")
    if isinstance(attributes, dict):
        flattened.update(attributes)
    return flattened


def _fetch_page_once(
    session: requests.Session, page_url: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> dict:
    response = session.get(page_url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429:
        # Better Stack signals rate limiting with a Retry-After header; honor it before tenacity's
        # exponential backoff kicks in.
        retry_after = response.headers.get("Retry-After")
        if retry_after is not None:
            try:
                sleep_seconds = int(retry_after)
            except ValueError:
                # Per RFC 7231, Retry-After may be an HTTP-date instead of a seconds count. We don't
                # parse the date; fall back to the cap so we still back off rather than hammering.
                sleep_seconds = MAX_RETRY_AFTER_SECONDS
            time.sleep(min(sleep_seconds, MAX_RETRY_AFTER_SECONDS))
        raise BetterStackRetryableError(f"Better Stack API rate limited: status=429, url={page_url}")

    if response.status_code >= 500:
        raise BetterStackRetryableError(
            f"Better Stack API error (retryable): status={response.status_code}, url={page_url}"
        )

    if not response.ok:
        logger.error(f"Better Stack API error: status={response.status_code}, body={response.text}, url={page_url}")
        response.raise_for_status()

    return response.json()


# Kept separate from `_fetch_page_once` so tests can exercise the request handling without
# tenacity's retry waits.
_fetch_page = retry(
    retry=retry_if_exception_type((BetterStackRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)(_fetch_page_once)


def probe_credentials(api_token: str, endpoint: str | None = None) -> int | None:
    """Cheap probe of a Better Stack collection. Returns the HTTP status code, or None on a
    connection failure. Probes the given endpoint's path when set, else the monitors collection."""
    config = BETTER_STACK_ENDPOINTS.get(endpoint) if endpoint else None
    path = config.path if config else "/v2/monitors"
    url = _build_url(f"{BETTER_STACK_BASE_URL}{path}", {"per_page": 1})
    try:
        response = make_tracked_session(capture=False).get(url, headers=_get_headers(api_token), timeout=10)
    except Exception:
        return None
    return response.status_code


def get_rows(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[BetterStackResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[Any]:
    config = BETTER_STACK_ENDPOINTS[endpoint]
    headers = _get_headers(api_token)
    # One session reused across pages so urllib3 keeps the connection alive.
    # capture=False: incident `response_content` and monitor URLs can carry arbitrary
    # secrets the name-based scrubbers can't recognise, so keep them out of HTTP samples.
    session = make_tracked_session(capture=False)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.next_url:
        url = _validate_pagination_url(resume.next_url)
        logger.debug(f"Better Stack: resuming {endpoint} from URL: {url}")
    else:
        params = _build_initial_params(config, should_use_incremental_field, db_incremental_field_last_value)
        url = _build_url(f"{BETTER_STACK_BASE_URL}{config.path}", params)

    while True:
        data = _fetch_page(session, url, headers, logger)

        items = data.get("data", [])
        next_url = data.get("pagination", {}).get("next")
        if next_url:
            next_url = _validate_pagination_url(next_url)

        if items:
            # Yield one page at a time as a list[dict]; the pipeline buffers and batches for us.
            yield [_flatten_item(item) for item in items]

        if not next_url:
            break

        # Save AFTER yielding so a crash re-yields the last page rather than skipping it — merge
        # dedupes on the primary key. Advance the URL before the next fetch to avoid re-looping it.
        resumable_source_manager.save_state(BetterStackResumeConfig(next_url=next_url))
        url = next_url


def better_stack_source(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[BetterStackResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = BETTER_STACK_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_token=api_token,
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
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # The incidents endpoint documents no sort param and its default ordering is unverified, so
        # declare "desc": the incremental watermark is committed once at the end of a successful
        # sync (safe for any arrival order) instead of checkpointed per batch.
        sort_mode="desc" if config.supports_incremental else "asc",
    )
