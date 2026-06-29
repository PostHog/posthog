import dataclasses
from collections.abc import Iterator
from datetime import date, datetime
from typing import Any, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit

import requests
from structlog.types import FilteringBoundLogger
from tenacity import RetryCallState, retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.incident_io.settings import (
    INCIDENT_IO_ENDPOINTS,
    IncidentIoEndpointConfig,
)

# Single global host — incident.io has no regions or per-account base paths.
INCIDENT_IO_BASE_URL = "https://api.incident.io"
REQUEST_TIMEOUT_SECONDS = 60
VALIDATION_TIMEOUT_SECONDS = 10
MAX_RETRIES = 5
MAX_RETRY_AFTER_SECONDS = 120


class IncidentIoRetryableError(Exception):
    def __init__(self, message: str, retry_after: Optional[float] = None):
        super().__init__(message)
        self.retry_after = retry_after


@dataclasses.dataclass
class IncidentIoResumeConfig:
    next_url: str


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }


def _build_url(path: str, params: dict[str, Any]) -> str:
    clean_params = {key: value for key, value in params.items() if value is not None}
    if not clean_params:
        return f"{INCIDENT_IO_BASE_URL}{path}"
    return f"{INCIDENT_IO_BASE_URL}{path}?{urlencode(clean_params)}"


def _params_from_url(url: str) -> dict[str, str]:
    """Recover the query params of a saved next-page URL, minus the page cursor.

    On resume we keep the original chain's filters instead of rebuilding them from the
    (possibly advanced) incremental watermark — mixing a fresh `gte` filter with an old
    `after` cursor could skip rows the cursor hadn't reached yet.
    """
    params = dict(parse_qsl(urlsplit(url).query))
    params.pop("after", None)
    return params


def _format_filter_value(value: Any) -> Optional[str]:
    """Coerce an incremental cursor value to a date string for incident.io `[gte]` filters.

    The API docs only show date-formatted filter values (e.g. `2024-05-01`), so we
    conservatively truncate to a date. `gte` is inclusive and we merge on `id`, so the
    up-to-a-day overlap is deduped downstream.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
        except ValueError:
            return None
    return None


def _build_params(
    config: IncidentIoEndpointConfig,
    incremental_field: Optional[str],
    incremental_value: Optional[str],
) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if config.paginated:
        params["page_size"] = config.page_size
    if config.sort_by:
        params["sort_by"] = config.sort_by
    if incremental_field and incremental_value:
        params[f"{incremental_field}[gte]"] = incremental_value
    return params


def _parse_retry_after(header_value: Optional[str]) -> Optional[float]:
    if not header_value:
        return None
    try:
        return max(0.0, float(header_value))
    except ValueError:
        # Retry-After can also be an HTTP date; fall back to exponential backoff.
        return None


_fallback_wait = wait_exponential_jitter(initial=1, max=60)


def _wait_with_retry_after(retry_state: RetryCallState) -> float:
    exception = retry_state.outcome.exception() if retry_state.outcome else None
    if isinstance(exception, IncidentIoRetryableError) and exception.retry_after is not None:
        return min(exception.retry_after, MAX_RETRY_AFTER_SECONDS)
    return _fallback_wait(retry_state)


def validate_credentials(api_key: str, schema_name: Optional[str] = None) -> tuple[bool, str | None]:
    """Probe the API to confirm the key is genuine.

    incident.io API keys carry granular per-resource view/list scopes, so a 403 from one
    endpoint can just mean a missing scope rather than a bad key. At source-create
    (``schema_name=None``) we accept 403 — the key authenticated, it's only missing a
    scope the user may not need. When validating a specific schema, a 403 is an error.
    """
    config = INCIDENT_IO_ENDPOINTS.get(schema_name or "", INCIDENT_IO_ENDPOINTS["incidents"])
    params: dict[str, Any] = {"page_size": 1} if config.paginated else {}

    try:
        response = make_tracked_session().get(
            _build_url(config.path, params),
            headers=_get_headers(api_key),
            timeout=VALIDATION_TIMEOUT_SECONDS,
        )
    except Exception:
        return False, "Unable to reach the incident.io API. Please try again."

    if response.status_code == 401:
        return False, "incident.io authentication failed. Please check that your API key is valid."

    if response.status_code == 403:
        if schema_name is None:
            return True, None
        return (
            False,
            f"Your incident.io API key can't list {schema_name}. incident.io API keys have per-resource permissions — grant the key the 'view' scope for this resource and try again.",
        )

    if response.ok:
        return True, None

    return False, f"incident.io API returned an unexpected response (status {response.status_code})."


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[IncidentIoResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[list[dict[str, Any]]]:
    config = INCIDENT_IO_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)

    incremental_value = _format_filter_value(db_incremental_field_last_value) if should_use_incremental_field else None

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume_config is not None:
        url: str = resume_config.next_url
        params: dict[str, Any] = _params_from_url(url)
        logger.debug(f"incident.io: resuming from URL: {url}")
    else:
        params = _build_params(config, incremental_field if should_use_incremental_field else None, incremental_value)
        url = _build_url(config.path, params)

    @retry(
        retry=retry_if_exception_type((IncidentIoRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRIES),
        wait=_wait_with_retry_after,
        reraise=True,
    )
    def fetch_page(page_url: str) -> dict[str, Any]:
        response = make_tracked_session().get(page_url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

        # incident.io rate-limits at 1,200 req/min; honor Retry-After when present and
        # fall back to exponential backoff otherwise.
        if response.status_code == 429:
            raise IncidentIoRetryableError(
                f"incident.io rate limit hit: url={page_url}",
                retry_after=_parse_retry_after(response.headers.get("Retry-After")),
            )

        if response.status_code >= 500:
            raise IncidentIoRetryableError(
                f"incident.io API error (retryable): status={response.status_code}, url={page_url}"
            )

        if not response.ok:
            logger.error(f"incident.io API error: status={response.status_code}, body={response.text}, url={page_url}")
            response.raise_for_status()

        return response.json()

    while True:
        data = fetch_page(url)
        items = data.get(config.data_key) or []

        if items:
            yield items

        # `pagination_meta.after` is a record ID tied to this run's ordering — it's only
        # valid as a within-run page cursor, never persisted as the incremental watermark
        # (the pipeline persists the max incremental field value instead).
        after = (data.get("pagination_meta") or {}).get("after")
        if not config.paginated or not after:
            break

        url = _build_url(config.path, {**params, "after": after})
        resumable_source_manager.save_state(IncidentIoResumeConfig(next_url=url))


def incident_io_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[IncidentIoResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = INCIDENT_IO_ENDPOINTS[endpoint]

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
        primary_keys=[config.primary_key],
        # Incidents are requested with `sort_by=created_at_oldest_first` (the only sortable
        # endpoint). When syncing incrementally on `updated_at`, values within a run aren't
        # monotonic — the final watermark is still correct because a run fetches every row
        # matching the filter, and merge-on-id dedupes any overlap on the next run.
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
