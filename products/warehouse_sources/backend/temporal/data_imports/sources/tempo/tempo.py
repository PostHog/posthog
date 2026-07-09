import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.tempo.settings import (
    TEMPO_ENDPOINTS,
    TempoEndpointConfig,
)

# Universal base path; Tempo also offers api.eu.tempo.io / api.us.tempo.io for geographic routing,
# but the universal host serves every region.
TEMPO_BASE_URL = "https://api.tempo.io/4"
# List endpoints default to 50 rows per page; 100 keeps round trips down without risking
# undocumented per-endpoint caps.
PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 60
# The plans endpoint requires a `from`/`to` window, so a full sync sends a wide fixed one. Plans
# are resource allocations that can extend into the future, hence the years of headroom.
PLANS_WINDOW_START = "2001-01-01"
PLANS_WINDOW_YEARS_AHEAD = 5
# Cheap endpoint used to confirm an API token is genuine at source-create. Tempo tokens carry
# granular scopes, so a 403 here still proves the token itself is valid.
DEFAULT_PROBE_ENDPOINT = "worklogs"


class TempoRetryableError(Exception):
    pass


@dataclasses.dataclass
class TempoResumeConfig:
    # Full URL of the next page, taken verbatim from the API's `metadata.next` (it embeds limit,
    # offset, and any filters). A crashed sync resumes from the page after the last one yielded;
    # merge dedupes the re-pulled page on the primary key. `None` means start from the first page.
    next_url: str | None = None


def _headers(api_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_token}", "Accept": "application/json"}


def _plans_window() -> tuple[str, str]:
    end = date.today() + timedelta(days=365 * PLANS_WINDOW_YEARS_AHEAD)
    return PLANS_WINDOW_START, end.isoformat()


def _format_updated_from(value: Any) -> str:
    # `updatedFrom` accepts "yyyy-MM-dd" or "yyyy-MM-dd'T'HH:mm:ss'Z'" (inclusive); the boundary
    # row is re-fetched and merge dedupes it on the primary key.
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(UTC)
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _probe_params(config: TempoEndpointConfig) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if config.paginated:
        params["limit"] = 1
    if config.requires_date_window:
        today = date.today().isoformat()
        params["from"] = today
        params["to"] = today
    return params


def _build_initial_params(
    config: TempoEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if config.paginated:
        params["limit"] = PAGE_SIZE
    if config.requires_date_window:
        window_from, window_to = _plans_window()
        params["from"] = window_from
        params["to"] = window_to
    if config.order_by:
        params["orderBy"] = config.order_by

    if should_use_incremental_field:
        advertised = {f["field"] for f in config.incremental_fields}
        if not config.incremental_param or incremental_field not in advertised:
            raise ValueError(f"Tempo endpoint '{config.name}' does not support incremental field '{incremental_field}'")
        if db_incremental_field_last_value:
            params[config.incremental_param] = _format_updated_from(db_incremental_field_last_value)

    return params


@retry(
    retry=retry_if_exception_type((TempoRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    url: str,
    params: Optional[dict[str, Any]],
    logger: FilteringBoundLogger,
) -> tuple[list[dict[str, Any]], Optional[str]]:
    # `params` is only set for the first request; `metadata.next` is a full URL with limit, offset,
    # and filters baked in, so follow-up requests must not re-send query params.
    response = session.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)

    # Tempo rate limiting is dynamic (no fixed quota) and surfaces as 429 — back off and retry.
    if response.status_code == 429 or response.status_code >= 500:
        raise TempoRetryableError(f"Tempo API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Tempo API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    data = response.json()
    # Every list endpoint wraps rows in {"results": [...], "metadata": {...}}; paginated ones set
    # `metadata.next` to the next page's URL (absent on the last page and on unpaginated endpoints).
    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        raise TempoRetryableError(f"Tempo returned an unexpected payload for {url}: {type(data).__name__}")

    metadata = data.get("metadata")
    next_url = metadata.get("next") if isinstance(metadata, dict) else None
    return data["results"], next_url if isinstance(next_url, str) and next_url else None


def get_rows(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[TempoResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> Iterator[list[dict[str, Any]]]:
    config = TEMPO_ENDPOINTS[endpoint]
    session = make_tracked_session(headers=_headers(api_token), redact_values=(api_token,))

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume and resume.next_url:
        logger.debug(f"Tempo: resuming {endpoint} from {resume.next_url}")
        url = resume.next_url
        params: Optional[dict[str, Any]] = None
    else:
        url = f"{TEMPO_BASE_URL}{config.path}"
        params = _build_initial_params(
            config, should_use_incremental_field, db_incremental_field_last_value, incremental_field
        )

    while True:
        items, next_url = _fetch_page(session, url, params, logger)
        if items:
            yield items

        # No `metadata.next` means we've reached the last page (or the endpoint is unpaginated).
        if not next_url:
            break

        url, params = next_url, None
        # Save AFTER yielding so a crash re-fetches from the next page (already-yielded pages are
        # persisted); merge dedupes the re-pulled page on the primary key.
        resumable_source_manager.save_state(TempoResumeConfig(next_url=next_url))


def tempo_source(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[TempoResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = TEMPO_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
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
        sort_mode=config.sort_mode,
    )


def check_access(api_token: str, endpoint: str = DEFAULT_PROBE_ENDPOINT) -> tuple[int, Optional[str]]:
    """Probe a single endpoint to check the API token.

    Returns ``(status, message)``: ``200`` reachable, ``401`` invalid token, ``403`` valid token
    missing the endpoint's view scope, ``0`` for a connection problem, other HTTP status otherwise.
    """
    config = TEMPO_ENDPOINTS[endpoint]
    session = make_tracked_session(headers=_headers(api_token), redact_values=(api_token,))
    try:
        response = session.get(f"{TEMPO_BASE_URL}{config.path}", params=_probe_params(config), timeout=15)
    except Exception as e:
        return 0, f"Could not connect to Tempo: {e}"

    if response.status_code in (401, 403):
        return response.status_code, None

    if not response.ok:
        return response.status_code, f"Tempo returned HTTP {response.status_code}"

    return 200, None


def validate_credentials(api_token: str, endpoint: str | None = None) -> tuple[bool, str | None]:
    status, message = check_access(api_token, endpoint or DEFAULT_PROBE_ENDPOINT)
    if status == 200:
        return True, None
    if status == 401:
        return False, "Invalid Tempo API token"
    if status == 403:
        # Tempo tokens carry granular scopes. At source-create (no endpoint) a 403 still proves the
        # token is genuine — the user may only have granted scopes for the tables they'll sync.
        if endpoint is None:
            return True, None
        return False, f"Your Tempo API token is missing the view scope for '{endpoint}'"
    return False, message or "Could not validate Tempo API token"
