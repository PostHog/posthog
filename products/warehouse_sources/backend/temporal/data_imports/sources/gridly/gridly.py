import json
import dataclasses
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlsplit

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.gridly.settings import GRIDLY_ENDPOINTS

GRIDLY_BASE_URL = "https://api.gridly.com/v1"

# Gridly caps `limit` at 1000 records per page; larger values are rejected.
PAGE_SIZE = 1000

MAX_RETRY_ATTEMPTS = 5


class GridlyRetryableError(Exception):
    pass


@dataclasses.dataclass
class GridlyResumeConfig:
    # Offset of the next records page to fetch. Records is the only paginated endpoint; the columns
    # endpoint is a single request and never resumes.
    offset: int = 0


def _headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"ApiKey {api_key}",
        "Accept": "application/json",
    }


def _parse_total_count(value: str | None) -> int | None:
    """Parse the `X-Total-Count` response header, tolerating a missing/garbage value."""
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


@retry(
    # ChunkedEncodingError is a mid-stream connection break (the server truncated a chunked
    # response body); it's transient like ConnectionError/ReadTimeout, not a ConnectionError subclass.
    retry=retry_if_exception_type(
        (
            GridlyRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch(
    session: requests.Session,
    url: str,
    params: dict[str, Any],
    headers: dict[str, str],
    logger: FilteringBoundLogger,
) -> requests.Response:
    response = session.get(url, params=params, headers=headers, timeout=60)

    if response.status_code == 429 or response.status_code >= 500:
        raise GridlyRetryableError(f"Gridly API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        # Never log response.text or the raw URL: the error body can echo customer record content
        # from the synced view, and the query string carries the paginated `page` blob. Both would
        # leak into operational logs. Log only status plus scheme/host/path.
        safe = urlsplit(response.url)
        safe_url = f"{safe.scheme}://{safe.netloc}{safe.path}"
        logger.error(f"Gridly API error: status={response.status_code}, url={safe_url}")
        # raise_for_status() would embed the full request URL (query string included) in the
        # exception, which is surfaced as the schema's latest_error. Rebuild the error from
        # scheme/host/path only so no request params or response body reach stored error state. The
        # "<status> Client Error: <reason> for url: https://api.gridly.com" prefix stays stable for
        # get_non_retryable_errors() matching.
        raise requests.HTTPError(
            f"{response.status_code} Client Error: {response.reason} for url: {safe_url}",
            response=response,
        )

    return response


def _iter_records(
    session: requests.Session,
    view_id: str,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[GridlyResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    """Walk the view's records with offset/limit pagination.

    Gridly's `page` query param is a JSON blob (`{"offset": n, "limit": m}`) and the total row
    count comes from the `X-Total-Count` response header. Rows are yielded in the shape the API
    returns them (`{id, path, cells}`) — `cells` is left as a nested list rather than flattened,
    since a record's columns are user-defined and vary per view.
    """
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    offset = resume.offset if resume is not None else 0
    if offset:
        logger.debug(f"Gridly: resuming records from offset={offset}")

    url = f"{GRIDLY_BASE_URL}/views/{view_id}/records"

    while True:
        page = json.dumps({"offset": offset, "limit": PAGE_SIZE}, separators=(",", ":"))
        response = _fetch(session, url, {"page": page}, headers, logger)
        records = response.json()

        if not records:
            break

        yield records

        total = _parse_total_count(response.headers.get("X-Total-Count"))
        offset += len(records)

        # A short page means we've reached the end regardless of the (possibly stale) total.
        if len(records) < PAGE_SIZE:
            break
        if total is not None and offset >= total:
            break

        # Save AFTER yielding so a crash re-fetches the last page rather than skipping it — merge
        # dedupes the re-pulled rows on the primary key.
        resumable_source_manager.save_state(GridlyResumeConfig(offset=offset))


def _iter_columns(
    session: requests.Session,
    view_id: str,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    """Yield the view's column definitions, read from the view object.

    Gridly has no standalone "list columns" endpoint; the column list is embedded in the view
    resource (`GET /v1/views/{viewId}`).
    """
    response = _fetch(session, f"{GRIDLY_BASE_URL}/views/{view_id}", {}, headers, logger)
    columns = response.json().get("columns", [])
    if columns:
        yield columns


def get_rows(
    api_key: str,
    view_id: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[GridlyResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    # One session reused across every page so urllib3 keeps the connection alive instead of
    # re-handshaking per request.
    session = make_tracked_session(redact_values=(api_key,))
    headers = _headers(api_key)

    if endpoint == "columns":
        yield from _iter_columns(session, view_id, headers, logger)
    elif endpoint == "records":
        yield from _iter_records(session, view_id, headers, logger, resumable_source_manager)
    else:
        raise ValueError(f"Unknown Gridly endpoint: {endpoint!r}")


def gridly_source(
    api_key: str,
    view_id: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[GridlyResumeConfig],
) -> SourceResponse:
    endpoint_config = GRIDLY_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            view_id=view_id,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=endpoint_config.primary_keys,
        # Records carry no stable datetime (no createdAt/updatedAt), so there's nothing to
        # partition on — this is a full-refresh replace on every sync.
        partition_count=1,
        partition_size=1,
        sort_mode="asc",
    )


def validate_credentials(api_key: str, view_id: str) -> tuple[bool, str | None]:
    """Probe the configured view to confirm the key is genuine and can reach the view."""
    try:
        response = make_tracked_session(redact_values=(api_key,)).get(
            f"{GRIDLY_BASE_URL}/views/{view_id}",
            headers=_headers(api_key),
            timeout=10,
        )
    except Exception as e:
        return False, str(e)

    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return False, "Invalid Gridly API key. Create a new API key in your Gridly company settings, then reconnect."
    if response.status_code == 403:
        return (
            False,
            "Your Gridly API key can't access this view. Grant the key access to the view (or use a "
            "Full Access key), then reconnect.",
        )
    if response.status_code == 404:
        return False, "Gridly view not found. Check the View ID and try again."
    return False, f"Gridly returned an unexpected status code: {response.status_code}"
