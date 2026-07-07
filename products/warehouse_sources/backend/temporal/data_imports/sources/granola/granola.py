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
from products.warehouse_sources.backend.temporal.data_imports.sources.granola.settings import (
    GRANOLA_ENDPOINTS,
    GranolaEndpointConfig,
)

GRANOLA_BASE_URL = "https://public-api.granola.ai"

# Granola caps page_size at 30; use the max to keep request volume low against the
# 5 req/s sustained / 25-per-5s burst rate limit.
PAGE_SIZE = 30

REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRY_ATTEMPTS = 5


class GranolaRetryableError(Exception):
    pass


@dataclasses.dataclass
class GranolaResumeConfig:
    # Full, self-contained next-page URL (base + filters + cursor) so a resume can GET it directly.
    next_url: str


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }


def _format_timestamp(value: Any) -> str:
    """Format an incremental cursor value as an ISO 8601 UTC timestamp with a Z suffix."""
    if isinstance(value, datetime):
        dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


def _build_initial_params(
    config: GranolaEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> dict[str, Any]:
    params: dict[str, Any] = {"page_size": PAGE_SIZE}

    if should_use_incremental_field and db_incremental_field_last_value is not None:
        # Honour the user's chosen cursor field, falling back to the first advertised field.
        field_name = incremental_field or (config.incremental_fields[0]["field"] if config.incremental_fields else None)
        query_param = config.incremental_query_params.get(field_name) if field_name else None
        if query_param:
            params[query_param] = _format_timestamp(db_incremental_field_last_value)

    return params


def _build_url(path: str, params: dict[str, Any]) -> str:
    return f"{GRANOLA_BASE_URL}{path}?{urlencode(params)}"


def validate_credentials(api_key: str, schema_name: Optional[str] = None) -> tuple[bool, str | None]:
    """Probe the endpoint matching the schema being validated to confirm the API key is genuine.

    A 401 means the key is missing or invalid. A 403 means a valid key without the scope
    for this endpoint - accepted at source-create (schema_name is None) since users may only
    grant the scopes for the streams they want to sync. Probing the schema's own path means a
    scope-limited key (e.g. folders-only) isn't rejected by an unrelated stream's probe.
    """
    endpoint = GRANOLA_ENDPOINTS.get(schema_name) if schema_name else None
    path = endpoint.path if endpoint else GRANOLA_ENDPOINTS["notes"].path
    url = _build_url(path, {"page_size": 1})
    try:
        response = make_tracked_session().get(url, headers=_get_headers(api_key), timeout=REQUEST_TIMEOUT_SECONDS)
    except Exception:
        return False, "Could not reach the Granola API. Please try again."

    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return False, "Invalid Granola API key"
    if response.status_code == 403 and schema_name is None:
        return True, None
    if response.status_code == 403:
        return False, "Your Granola API key does not have access to this data"

    return False, f"Granola API returned an unexpected status code: {response.status_code}"


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[GranolaResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[list[dict[str, Any]]]:
    config = GRANOLA_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)

    params = _build_initial_params(
        config, should_use_incremental_field, db_incremental_field_last_value, incremental_field
    )

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume_config is not None:
        url = resume_config.next_url
        logger.debug(f"Granola: resuming {endpoint} from URL: {url}")
    else:
        url = _build_url(config.path, params)

    @retry(
        retry=retry_if_exception_type((GranolaRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=1, max=30),
        reraise=True,
    )
    def fetch_page(page_url: str) -> dict[str, Any]:
        response = make_tracked_session().get(page_url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code == 429 or response.status_code >= 500:
            raise GranolaRetryableError(f"Granola API error (retryable): status={response.status_code}, url={page_url}")

        if not response.ok:
            logger.error(f"Granola API error: status={response.status_code}, body={response.text}, url={page_url}")
            response.raise_for_status()

        return response.json()

    while True:
        data = fetch_page(url)

        items = data.get(config.data_key, [])

        # Compute the next-page URL before yielding so we can checkpoint after the batch.
        next_url: str | None = None
        if data.get("hasMore") and data.get("cursor"):
            next_url = _build_url(config.path, {**params, "cursor": data["cursor"]})

        if items:
            yield items

        if not next_url:
            break

        # Save state AFTER yielding so a crash re-yields the last batch (merge dedupes on id)
        # rather than skipping it.
        resumable_source_manager.save_state(GranolaResumeConfig(next_url=next_url))
        url = next_url


def granola_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[GranolaResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = GRANOLA_ENDPOINTS[endpoint]

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
        primary_keys=["id"],
        # Granola's list endpoints have no sort parameter, so within-page ordering is
        # undefined. "desc" here is the pipeline's "commit the incremental watermark only
        # after every page has been processed" mode - with undefined ordering we must not
        # advance the watermark per-batch (that could persist a high value early and skip
        # older, not-yet-fetched rows on the next run's server-side `*_after` filter).
        # Pagination is driven entirely by the opaque cursor, so we don't rely on ordering
        # or on `db_incremental_field_earliest_value` to scroll; merge dedupes on `id`.
        sort_mode="desc",
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
