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
from products.warehouse_sources.backend.temporal.data_imports.sources.elasticemail.settings import (
    ELASTICEMAIL_ENDPOINTS,
    PAGE_SIZE,
    ElasticEmailEndpointConfig,
)

ELASTICEMAIL_BASE_URL = "https://api.elasticemail.com/v4"

# Marker carried by ElasticEmailAuthError so `get_non_retryable_errors` can match credential failures.
# Elastic Email returns these as HTTP 400 with an `{"Error": "APIKey Expired"}` style body rather than
# the more usual 401/403, so we can't match on the status line alone.
AUTH_ERROR_MARKER = "Elastic Email API authentication failed"

# A cheap, parameter-free endpoint used to confirm a key is genuine at source-create time.
VALIDATION_PATH = "/statistics"

REQUEST_TIMEOUT_SECONDS = 60


class ElasticEmailRetryableError(Exception):
    pass


class ElasticEmailAuthError(Exception):
    pass


@dataclasses.dataclass
class ElasticEmailResumeConfig:
    # Next offset to request. Elastic Email paginates with limit/offset, so the offset alone is enough
    # to resume mid-endpoint; the incremental `from` window is re-derived from the stored cursor each run.
    offset: int = 0


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "X-ElasticEmail-ApiKey": api_key,
        "Accept": "application/json",
    }


def _format_datetime(value: Any) -> str:
    """Format a datetime/date as the `YYYY-MM-DDThh:mm:ss` (UTC, no offset) shape Elastic Email expects."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S")
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%S")
    return str(value)


def _clamp_future_value_to_now(value: Any) -> Any:
    """Cap a future datetime/date cursor at now so the `from` filter never asks for impossible records."""
    now = datetime.now(UTC)
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return now if aware > now else value
    if isinstance(value, date):
        return now.date() if value > now.date() else value
    return value


def _build_params(
    config: ElasticEmailEndpointConfig,
    offset: int,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> dict[str, Any]:
    """Assemble the query params for one page request."""
    params: dict[str, Any] = {"limit": PAGE_SIZE, "offset": offset}
    params.update(config.extra_params)

    # Only endpoints that advertise an incremental field have a server-side `from` time filter.
    if should_use_incremental_field and config.incremental_fields and db_incremental_field_last_value:
        params["from"] = _format_datetime(_clamp_future_value_to_now(db_incremental_field_last_value))

    return params


def _build_url(path: str, params: dict[str, Any]) -> str:
    # doseq=True expands list values (e.g. scopeType=Personal&scopeType=Global) into repeated params.
    return f"{ELASTICEMAIL_BASE_URL}{path}?{urlencode(params, doseq=True)}"


def _is_auth_error_body(status_code: int, body: str) -> bool:
    if status_code in (401, 403):
        return True
    if status_code != 400:
        return False
    lowered = body.lower()
    return any(token in lowered for token in ("apikey", "api key", "access token", "unauthorized", "expired"))


@retry(
    retry=retry_if_exception_type((ElasticEmailRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> list[dict[str, Any]]:
    response = session.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429 or response.status_code >= 500:
        raise ElasticEmailRetryableError(
            f"Elastic Email API error (retryable): status={response.status_code}, url={url}"
        )

    if not response.ok:
        body = response.text or ""
        # Elastic Email signals a bad/expired/under-scoped key with HTTP 400, not 401/403. Surface it as a
        # distinct, non-retryable error so the sync stops instead of hammering the API with a dead key.
        if _is_auth_error_body(response.status_code, body):
            raise ElasticEmailAuthError(f"{AUTH_ERROR_MARKER} (HTTP {response.status_code}): {body}")
        logger.error(f"Elastic Email API error: status={response.status_code}, body={body}, url={url}")
        response.raise_for_status()

    try:
        data = response.json()
    except ValueError as exc:
        # A 200 with a non-JSON body (e.g. an HTML error page from a CDN/proxy) raises JSONDecodeError,
        # which isn't a retryable type by default. Treat it as transient so the page is retried.
        raise ElasticEmailRetryableError(f"Non-JSON Elastic Email response: url={url}") from exc

    # Every v4 list endpoint returns a bare JSON array. Guard against an unexpected object payload.
    if not isinstance(data, list):
        raise ElasticEmailRetryableError(f"Unexpected Elastic Email response shape (expected list): url={url}")
    return data


def validate_credentials(
    api_key: str, path: str = VALIDATION_PATH, extra_params: Optional[dict[str, list[str] | str]] = None
) -> bool:
    """Probe a single endpoint to confirm the key is accepted. `path` lets callers check a specific scope."""
    params: dict[str, Any] = {"limit": 1, "offset": 0, **(extra_params or {})}
    url = _build_url(path, params)
    try:
        # redact_values masks the API key in logged URLs and captured HTTP samples; the X-ElasticEmail-ApiKey
        # header name isn't in the transport's generic auth denylist, so we redact the value explicitly.
        response = make_tracked_session(redact_values=(api_key,)).get(url, headers=_get_headers(api_key), timeout=10)
    except requests.RequestException:
        # A transport failure (DNS, connection, timeout) isn't a credential verdict, but at source-create
        # time we can only report valid/invalid — treat an unreachable API as "can't validate" → invalid.
        return False
    if response.ok:
        return True
    return not _is_auth_error_body(response.status_code, response.text or "")


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ElasticEmailResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[Any]:
    config = ELASTICEMAIL_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)
    batcher = Batcher(logger=logger, chunk_size=2000, chunk_size_bytes=100 * 1024 * 1024)
    # One session reused across every page so urllib3 keeps the connection alive between requests.
    # redact_values masks the API key in logged URLs and captured HTTP samples; the X-ElasticEmail-ApiKey
    # header name isn't in the transport's generic auth denylist, so we redact the value explicitly.
    session = make_tracked_session(redact_values=(api_key,))

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    offset = resume.offset if resume is not None else 0
    if resume is not None:
        logger.debug(f"Elastic Email: resuming {endpoint} from offset={offset}")

    while True:
        params = _build_params(config, offset, should_use_incremental_field, db_incremental_field_last_value)
        url = _build_url(config.path, params)
        items = _fetch_page(session, url, headers, logger)

        for item in items:
            batcher.batch(item)

        offset += len(items)
        last_page = len(items) < PAGE_SIZE

        if batcher.should_yield():
            yield batcher.get_table()
            # Save AFTER yielding so a crash re-fetches from the last persisted offset rather than skipping
            # rows. Only persist when more pages remain; the final flush below needs no checkpoint.
            if not last_page:
                resumable_source_manager.save_state(ElasticEmailResumeConfig(offset=offset))

        if last_page:
            break

    if batcher.should_yield(include_incomplete_chunk=True):
        yield batcher.get_table()


def elasticemail_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ElasticEmailResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = ELASTICEMAIL_ENDPOINTS[endpoint]

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
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # Events are fetched oldest-first (orderBy=DateAscending); the other endpoints are full refresh
        # where order does not affect correctness.
        sort_mode="asc",
    )
