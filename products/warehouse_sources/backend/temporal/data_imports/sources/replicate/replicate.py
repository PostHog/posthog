import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode, urlsplit, urlunsplit

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.replicate.settings import (
    REPLICATE_ENDPOINTS,
    ReplicateEndpointConfig,
)

REPLICATE_BASE_URL = "https://api.replicate.com/v1"
REPLICATE_API_HOST = "api.replicate.com"


class ReplicateRetryableError(Exception):
    pass


@dataclasses.dataclass
class ReplicateResumeConfig:
    # Full next-page URL returned by the API (carries the opaque cursor and any created_after filter).
    # None means "start the endpoint from its first page".
    next_url: str | None = None
    # The `created_after` watermark this cursor was built against. A run whose watermark has since
    # advanced must not resume from this cursor (see `get_rows`), so we can tell the two apart.
    created_after: str | None = None


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }


def _format_incremental_value(value: Any) -> str:
    """Format an incremental cursor for Replicate's ISO 8601 `created_after` filter.

    Replicate returns and accepts UTC timestamps with a `Z` suffix (e.g.
    `2023-09-08T16:19:34.765994Z`), so we normalize to that rather than the `+00:00`
    offset `isoformat()` emits.
    """
    if isinstance(value, datetime):
        utc_dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return utc_dt.isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).isoformat().replace("+00:00", "Z")
    return str(value)


def _parse_datetime(value: Any) -> datetime | None:
    """Parse a Replicate ISO 8601 timestamp into an aware datetime, tolerating the Z suffix."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


def _to_cutoff(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    return _parse_datetime(value)


def validate_credentials(api_key: str) -> bool:
    try:
        response = make_tracked_session(redact_values=(api_key,)).get(
            f"{REPLICATE_BASE_URL}/account", headers=_get_headers(api_key), timeout=10
        )
        return response.status_code == 200
    except Exception:
        return False


@retry(
    retry=retry_if_exception_type(
        (
            ReplicateRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger) -> Any:
    response = session.get(url, headers=headers, timeout=60)

    # Replicate rate-limits at 3,000 req/min for read endpoints (429 on excess); 5xx are transient.
    if response.status_code == 429 or response.status_code >= 500:
        raise ReplicateRetryableError(f"Replicate API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Replicate API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def _extract_items(data: Any, config: ReplicateEndpointConfig) -> list[dict[str, Any]]:
    if config.response_shape == "object":
        # A single-object endpoint (e.g. /account) becomes one row.
        return [data] if isinstance(data, dict) else []
    if config.response_shape == "list":
        # A bare JSON array (e.g. /hardware).
        return data if isinstance(data, list) else []
    # Paginated: rows live under "results".
    return data.get("results", []) if isinstance(data, dict) else []


def _sanitize_next_url(raw_url: str | None) -> str | None:
    """Pin a Replicate pagination URL to the fixed HTTPS API origin.

    Replicate's documented pagination `next` (and any cursor loaded from resume state) can come
    back as `http://api.replicate.com/...`, which would send the bearer token over plaintext where
    an on-path attacker could capture it. Only the path and query are trusted; the scheme is forced
    to https and the host must be Replicate's API host, otherwise we stop rather than follow it.
    """
    if not raw_url:
        return None
    parts = urlsplit(raw_url)
    if parts.hostname != REPLICATE_API_HOST:
        return None
    return urlunsplit(("https", REPLICATE_API_HOST, parts.path, parts.query, ""))


def _next_url(data: Any) -> str | None:
    if isinstance(data, dict):
        return _sanitize_next_url(data.get("next"))
    return None


def _build_initial_url(
    config: ReplicateEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> str:
    base = f"{REPLICATE_BASE_URL}{config.path}"
    if config.time_filter_param and should_use_incremental_field and db_incremental_field_last_value is not None:
        query = urlencode({config.time_filter_param: _format_incremental_value(db_incremental_field_last_value)})
        return f"{base}?{query}"
    return base


def _page_predates_cutoff(items: list[dict[str, Any]], incremental_field: str, cutoff: datetime) -> bool:
    """True when every dated row in the page is at/older than the cutoff.

    Replicate returns predictions newest-first, so once a whole page predates the watermark there is
    nothing newer left to fetch. This bounds the walk even if the server silently ignores
    `created_after` on paginated requests (unverified against the live API), matching the skill's
    "incremental pagination must terminate at the watermark" rule. Merge dedupes the boundary re-read.
    """
    parsed = [_parse_datetime(item.get(incremental_field)) for item in items]
    dated = [d for d in parsed if d is not None]
    if not dated:
        return False
    return max(dated) <= cutoff


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ReplicateResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[list[dict[str, Any]]]:
    config = REPLICATE_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)
    # One session reused across every page so urllib3 keeps the connection alive. Redact the token so
    # it never lands in tracked HTTP logs, and disable capture entirely: prediction responses carry
    # user-authored model inputs, outputs, and logs that the generic scrubber can't reliably sanitize.
    session = make_tracked_session(redact_values=(api_key,), capture=False)

    # Single-request endpoints (bare array / single object) have no pagination or resume state.
    if config.response_shape != "paginated":
        data = _fetch_page(session, f"{REPLICATE_BASE_URL}{config.path}", headers, logger)
        items = _extract_items(data, config)
        if items:
            yield items
        return

    incremental = config.time_filter_param is not None and should_use_incremental_field
    current_watermark = (
        _format_incremental_value(db_incremental_field_last_value)
        if incremental and db_incremental_field_last_value is not None
        else None
    )

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    resumed_url = _sanitize_next_url(resume.next_url) if resume is not None else None
    # Only honor a saved cursor when it was written for the current watermark. If the watermark has
    # advanced, resuming from an older descending page would skip predictions created since the prior
    # run (they live on the first page), so rebuild from the initial URL instead.
    if resumed_url and resume is not None and resume.created_after == current_watermark:
        url = resumed_url
        logger.debug(f"Replicate: resuming {endpoint} from URL: {url}")
    else:
        url = _build_initial_url(config, should_use_incremental_field, db_incremental_field_last_value)

    cutoff = _to_cutoff(db_incremental_field_last_value) if incremental else None
    cursor_field = incremental_field or (config.incremental_fields[0]["field"] if config.incremental_fields else None)

    while True:
        data = _fetch_page(session, url, headers, logger)
        items = _extract_items(data, config)

        if items:
            yield items

        next_url = _next_url(data)

        # Desc + incremental: stop once a whole page predates the watermark, so we don't re-walk the
        # entire history if the server drops the created_after filter on later cursor pages.
        if next_url and cutoff is not None and cursor_field and _page_predates_cutoff(items, cursor_field, cutoff):
            break

        if not next_url:
            break

        # Save AFTER yielding, so a crash re-yields the last page rather than skipping it (merge
        # dedupes on the primary key). Tag it with the watermark so a later run with an advanced
        # watermark rebuilds from the first page instead of trusting this cursor.
        resumable_source_manager.save_state(ReplicateResumeConfig(next_url=next_url, created_after=current_watermark))
        url = next_url


def replicate_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ReplicateResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = REPLICATE_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        ),
        primary_keys=config.primary_keys,
        sort_mode=config.sort_mode,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
