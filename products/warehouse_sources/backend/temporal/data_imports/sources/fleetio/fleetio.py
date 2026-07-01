import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.fleetio.settings import (
    FLEETIO_ENDPOINTS,
    FleetioEndpointConfig,
)

FLEETIO_BASE_URL = "https://secure.fleetio.com/api/v1"
# Pin a modern date version explicitly. A Fleetio API key is locked to whatever version was current
# when it was created, but the `X-Api-Version` header overrides that lock per request. 2024-06-30 is
# the version where every index endpoint gained cursor pagination + `filter`/`sort`, while still
# living under the `/api/v1` path (integer paths are only dropped from 2025-05-05 onward). Pinning it
# means we get one consistent pagination/filtering contract regardless of the key's locked version.
FLEETIO_API_VERSION = "2024-06-30"
PER_PAGE = 100
DEFAULT_INCREMENTAL_FIELD = "updated_at"

MAX_RETRIES = 5


class FleetioRetryableError(Exception):
    """Transient 5xx — safe to retry with backoff."""


class FleetioRateLimitError(Exception):
    """429 Too Many Requests. Carries the server's Retry-After (seconds) so we can honor it."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


def _get_headers(api_key: str, account_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Token {api_key}",
        "Account-Token": account_token,
        "X-Api-Version": FLEETIO_API_VERSION,
        "Accept": "application/json",
    }


def _format_incremental_value(value: Any) -> str:
    """Format an incremental cursor value for Fleetio's `filter[...][gt]` parameter.

    Fleetio parses standard ISO 8601 timestamps (Rails `Time.zone.parse`), so isoformat with an
    explicit UTC offset is accepted. Naive datetimes are treated as UTC.
    """
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return aware.isoformat()
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).isoformat()
    return str(value)


def _build_url(base_url: str, params: dict[str, Any]) -> str:
    """Build a URL with an encoded query string.

    The `filter[updated_at][gt]` / `sort[updated_at]` keys contain literal brackets; `urlencode`
    percent-encodes them (and the timestamp's `+`/`:`), which Rack decodes back to brackets on the
    server, so the encoded form is equivalent to the documented literal form.
    """
    if not params:
        return base_url
    return f"{base_url}?{urlencode(params)}"


def _build_base_params(
    config: FleetioEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> dict[str, Any]:
    """Build the query params reused on every page (the cursor is added per request).

    Sort ascending on the field we checkpoint against so `SourceResponse.sort_mode="asc"` holds and
    the watermark advances correctly: the chosen incremental field when syncing incrementally, else a
    stable field (`created_at`) to keep full-refresh pagination from skipping/duplicating rows as data
    is inserted mid-sync.
    """
    params: dict[str, Any] = {"per_page": PER_PAGE}

    sort_field = (incremental_field if should_use_incremental_field else None) or config.partition_key or "created_at"
    params[f"sort[{sort_field}]"] = "asc"

    if should_use_incremental_field and db_incremental_field_last_value is not None:
        # `filter[<field>][gt]` is the documented server-side timestamp filter for API versions
        # 2024-01-01+ (the `gt` operator mirrors the legacy `q[<field>_gt]` ransack predicate). The
        # cursor envelope carries the active filter forward, so it stays applied on every page rather
        # than only the first — no unbounded history re-walk on incremental syncs. Not yet verified
        # against a live account (no test credentials); see PR notes.
        filter_field = incremental_field or DEFAULT_INCREMENTAL_FIELD
        params[f"filter[{filter_field}][gt]"] = _format_incremental_value(db_incremental_field_last_value)

    return params


@dataclasses.dataclass
class FleetioResumeConfig:
    # The cursor to start the next page from. None means "start at the first page".
    start_cursor: str | None = None


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _retry_wait(retry_state: Any) -> float:
    """Honor a 429's Retry-After header when present, else fall back to exponential backoff."""
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    if isinstance(exc, FleetioRateLimitError) and exc.retry_after is not None:
        return exc.retry_after
    return wait_exponential_jitter(initial=1, max=30)(retry_state)


@retry(
    retry=retry_if_exception_type(
        (FleetioRetryableError, FleetioRateLimitError, requests.ReadTimeout, requests.ConnectionError)
    ),
    stop=stop_after_attempt(MAX_RETRIES),
    wait=_retry_wait,
    reraise=True,
)
def _fetch_page(
    session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> dict[str, Any]:
    response = session.get(url, headers=headers, timeout=60)

    if response.status_code == 429:
        raise FleetioRateLimitError(
            f"Fleetio API rate limited: url={url}",
            retry_after=_parse_retry_after(response.headers.get("Retry-After")),
        )

    if response.status_code >= 500:
        raise FleetioRetryableError(f"Fleetio API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Fleetio API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    data = response.json()
    if not isinstance(data, dict):
        # With X-Api-Version pinned, every index endpoint returns the cursor envelope
        # ({"records": [...], "next_cursor": ...}). A bare list would mean the version pin was
        # ignored (legacy page-based response); fail loudly rather than silently syncing one page.
        raise FleetioRetryableError(f"Unexpected Fleetio response shape (expected cursor envelope): url={url}")
    return data


def validate_credentials(api_key: str, account_token: str) -> bool:
    # Probe a cheap index endpoint; Fleetio API keys are account-scoped (no per-endpoint scopes), so
    # one 200 confirms both headers are genuine.
    url = _build_url(f"{FLEETIO_BASE_URL}/vehicles", {"per_page": 1})
    try:
        # Redact both credentials in logged URLs and captured samples. `Account-Token` is a
        # connector-specific header name the generic auth scrubbers don't recognise, so value-based
        # redaction is required to keep it out of HTTP telemetry.
        session = make_tracked_session(redact_values=(api_key, account_token))
        response = session.get(url, headers=_get_headers(api_key, account_token), timeout=10)
        return response.status_code == 200
    except Exception:
        return False


def get_rows(
    api_key: str,
    account_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[FleetioResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[Any]:
    config = FLEETIO_ENDPOINTS[endpoint]
    headers = _get_headers(api_key, account_token)
    batcher = Batcher(logger=logger, chunk_size=2000, chunk_size_bytes=100 * 1024 * 1024)
    # One session reused across every page so urllib3 keeps the connection alive. Redact both
    # credentials in logged URLs and captured samples — `Account-Token` is a connector-specific
    # header name the generic auth scrubbers don't recognise.
    session = make_tracked_session(redact_values=(api_key, account_token))

    base_params = _build_base_params(
        config, should_use_incremental_field, db_incremental_field_last_value, incremental_field
    )

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    start_cursor = resume.start_cursor if resume else None
    if start_cursor:
        logger.debug(f"Fleetio: resuming {endpoint} from cursor={start_cursor}")

    while True:
        params = dict(base_params)
        if start_cursor:
            params["start_cursor"] = start_cursor
        url = _build_url(f"{FLEETIO_BASE_URL}{config.path}", params)

        data = _fetch_page(session, url, headers, logger)
        records = data.get("records", [])
        next_cursor = data.get("next_cursor")

        yielded_this_page = False
        for item in records:
            batcher.batch(item)

            if batcher.should_yield():
                yield batcher.get_table()
                yielded_this_page = True

        # Save state once, AFTER every record on this page has been batched, so a mid-page yield (the
        # 100 MB byte-size limit) can't advance the cursor past records we haven't seen yet. A crash
        # then re-fetches the whole page rather than skipping its tail — merge dedupes on the primary
        # key. Only save when we yielded data and more pages remain.
        if yielded_this_page and next_cursor:
            resumable_source_manager.save_state(FleetioResumeConfig(start_cursor=next_cursor))

        if not next_cursor:
            break
        start_cursor = next_cursor

    if batcher.should_yield(include_incomplete_chunk=True):
        yield batcher.get_table()


def fleetio_source(
    api_key: str,
    account_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[FleetioResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    endpoint_config = FLEETIO_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            account_token=account_token,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        ),
        primary_keys=endpoint_config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
        sort_mode="asc",
    )
