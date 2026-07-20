import dataclasses
from collections.abc import Iterator
from typing import Any, Optional
from urllib.parse import urlsplit

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.cloudbeds.settings import (
    CLOUDBEDS_ENDPOINTS,
    CloudbedsEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

CLOUDBEDS_BASE_URL = "https://api.cloudbeds.com/api/v1.2"
# List endpoints accept pageSize up to 100 (the default); the largest page minimises round trips
# against Cloudbeds' 5 req/sec property-credential rate limit.
PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 60
# Cheap endpoint used to confirm a token is genuine. Every credential (API key or OAuth token) can
# read the properties it is scoped to, so one probe validates the token itself; per-endpoint scopes
# are handled at sync time via get_non_retryable_errors.
DEFAULT_PROBE_PATH = "/getHotels"


class CloudbedsRetryableError(Exception):
    pass


class CloudbedsApiError(Exception):
    """Cloudbeds returned HTTP 200 with `success: false` (bad params, missing scope, ...)."""

    pass


@dataclasses.dataclass
class CloudbedsResumeConfig:
    # Next pageNumber to fetch (1-based). Cloudbeds paginates by page number, so a crashed
    # full-refresh sync resumes from the page after the last one yielded; merge dedupes the
    # re-pulled page on the primary key. `None` means start from the first page.
    page: int | None = None


def _headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}


def _flatten_rows(rows: list[dict[str, Any]], config: CloudbedsEndpointConfig) -> list[dict[str, Any]]:
    if not config.flatten_field:
        return rows

    flattened: list[dict[str, Any]] = []
    for parent in rows:
        nested = parent.get(config.flatten_field)
        if not isinstance(nested, list):
            continue
        # Direct access so a missing required parent field (e.g. propertyID) fails fast instead of
        # silently writing None across every flattened child row.
        parent_fields = {key: parent[key] for key in config.flatten_parent_fields}
        for row in nested:
            flattened.append({**row, **parent_fields})
    return flattened


@retry(
    retry=retry_if_exception_type((CloudbedsRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    path: str,
    params: dict[str, Any],
    logger: FilteringBoundLogger,
) -> list[dict[str, Any]]:
    response = session.get(f"{CLOUDBEDS_BASE_URL}{path}", params=params, timeout=REQUEST_TIMEOUT_SECONDS)

    # Exceeding Cloudbeds' rate limit (5 req/sec for property credentials) returns 429; backing off
    # matters because repeated violations can temporarily suspend the credential.
    if response.status_code == 429 or response.status_code >= 500:
        raise CloudbedsRetryableError(f"Cloudbeds API error (retryable): status={response.status_code}, path={path}")

    if not response.ok:
        # Cloudbeds error bodies can echo guest/reservation data, so log only a short capped
        # excerpt rather than the full body.
        logger.error(f"Cloudbeds API error: status={response.status_code}, path={path}, body={response.text[:200]}")
        # raise_for_status() would embed the full request URL in the exception, which is surfaced as
        # the schema's latest_error. Cloudbeds authenticates via the Authorization header today, but
        # rebuild the error from scheme/host/path only so a redirect or future query-param auth can
        # never leak the api_key into stored error state. The "<status> Client Error: <reason> for
        # url: https://api.cloudbeds.com" prefix stays stable for get_non_retryable_errors() matching.
        safe = urlsplit(response.url)
        raise requests.HTTPError(
            f"{response.status_code} Client Error: {response.reason} for url: {safe.scheme}://{safe.netloc}{safe.path}",
            response=response,
        )

    data = response.json()
    if not isinstance(data, dict):
        raise CloudbedsRetryableError(f"Cloudbeds returned an unexpected payload for {path}: {type(data).__name__}")

    # Cloudbeds signals request-level errors (bad params, missing OAuth scope, ...) as HTTP 200 with
    # success=false and a message - these are not transient, so fail instead of retrying.
    if data.get("success") is False:
        raise CloudbedsApiError(f"Cloudbeds API request to {path} failed: {data.get('message', 'unknown error')}")

    rows = data.get("data")
    if not isinstance(rows, list):
        raise CloudbedsRetryableError(f"Cloudbeds returned an unexpected data payload for {path}")

    return rows


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CloudbedsResumeConfig],
    property_id: str | None = None,
) -> Iterator[list[dict[str, Any]]]:
    config = CLOUDBEDS_ENDPOINTS[endpoint]
    session = make_tracked_session(headers=_headers(api_key), redact_values=(api_key,))

    # Group (multi-property) credentials require propertyID to scope reads; single-property
    # credentials can omit it.
    base_params: dict[str, Any] = {"propertyID": property_id} if property_id else {}

    if not config.paginated:
        rows = _fetch_page(session, config.path, base_params, logger)
        flattened = _flatten_rows(rows, config)
        if flattened:
            yield flattened
        return

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page = resume.page if (resume and resume.page) else 1
    if resume and resume.page:
        logger.debug(f"Cloudbeds: resuming {endpoint} from page {page}")

    while True:
        params = {**base_params, "pageNumber": page, "pageSize": PAGE_SIZE}
        rows = _fetch_page(session, config.path, params, logger)
        flattened = _flatten_rows(rows, config)
        if flattened:
            yield flattened

        # A short (or empty) page means we've reached the end of the collection.
        if len(rows) < PAGE_SIZE:
            break

        page += 1
        # Save AFTER yielding so a crash re-fetches from the next page (already-yielded pages are
        # persisted); merge dedupes the re-pulled page on the primary key.
        resumable_source_manager.save_state(CloudbedsResumeConfig(page=page))


def cloudbeds_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CloudbedsResumeConfig],
    property_id: str | None = None,
) -> SourceResponse:
    config = CLOUDBEDS_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            property_id=property_id,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
    )


def check_access(
    api_key: str, property_id: str | None = None, path: str = DEFAULT_PROBE_PATH
) -> tuple[int, Optional[str]]:
    """Probe a single endpoint to validate the API key or OAuth access token.

    Returns ``(status, message)``: ``200`` reachable, ``401``/``403`` auth failure, ``0`` for a
    connection problem, other HTTP status otherwise.
    """
    session = make_tracked_session(headers=_headers(api_key), redact_values=(api_key,))
    params: dict[str, Any] = {"propertyID": property_id} if property_id else {}
    try:
        response = session.get(f"{CLOUDBEDS_BASE_URL}{path}", params=params, timeout=15)
    except Exception as e:
        return 0, f"Could not connect to Cloudbeds: {e}"

    if response.status_code in (401, 403):
        return response.status_code, None

    if not response.ok:
        return response.status_code, f"Cloudbeds returned HTTP {response.status_code}"

    return 200, None


def validate_credentials(api_key: str, property_id: str | None = None) -> tuple[bool, str | None]:
    status, message = check_access(api_key, property_id)
    if status == 200:
        return True, None
    if status in (401, 403):
        return False, "Invalid Cloudbeds API key"
    return False, message or "Could not validate Cloudbeds API key"
