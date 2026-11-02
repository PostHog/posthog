import json
import contextlib
import dataclasses
from collections.abc import Iterator
from typing import Any
from urllib.parse import quote, urlsplit

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import (
    make_tracked_session,
    retry_with_deadline,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http.observer import redact_request_urls
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.gridly.settings import GRIDLY_ENDPOINTS

GRIDLY_BASE_URL = "https://api.gridly.com/v1"

# Gridly caps `limit` at 1000 records per page; larger values are rejected.
PAGE_SIZE = 1000

MAX_RETRY_ATTEMPTS = 5


class GridlyRetryableError(Exception):
    pass


@dataclasses.dataclass  # nosemgrep: prefer-frozen-dataclasses -- pre-existing; new field shifts the backlog finding into diff
class GridlyResumeConfig:
    # Position to resume from. For `records` it is the offset of the next records page. For
    # `record_histories` and `automation_executions` it is the index of the next parent (record or
    # automation) to fan out over. The other endpoints never resume.
    offset: int = 0
    # For `record_histories` only: the offset of the next history page of the record at `offset`.
    history_offset: int = 0


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


@retry_with_deadline(
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
    redacted_url: str | None = None,
) -> requests.Response:
    # `redacted_url` replaces `url` in every log line and error when the URL embeds customer content,
    # such as a customer-defined record id.
    try:
        # The tracked transport records the request URL, so a redacted request hides it there too.
        with redact_request_urls() if redacted_url else contextlib.nullcontext():
            response = session.get(url, params=params, headers=headers, timeout=60)
    except (requests.ReadTimeout, requests.ConnectionError, requests.exceptions.ChunkedEncodingError) as error:
        if redacted_url is None:
            raise
        # The transport message repeats the request path and query, so rebuild it from the redacted URL.
        raise type(error)(f"{type(error).__name__} requesting {redacted_url}") from None

    if response.status_code == 429 or response.status_code >= 500:
        raise GridlyRetryableError(
            f"Gridly API error (retryable): status={response.status_code}, url={redacted_url or url}"
        )

    if not response.ok:
        # Never log response.text or the raw URL: the error body can echo customer record content
        # from the synced view, and the query string carries the paginated `page` blob. Both would
        # leak into operational logs. Log only status plus scheme/host/path.
        safe = urlsplit(redacted_url or response.url)
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


def _iter_dependencies(
    session: requests.Session,
    view_id: str,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    dependencies = _fetch(session, f"{GRIDLY_BASE_URL}/views/{view_id}/dependencies", {}, headers, logger).json()
    if dependencies:
        yield dependencies


def _iter_automation_executions(
    session: requests.Session,
    view_id: str,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[GridlyResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    """Yield the executions of every automation of the view, one request per automation.

    The API reference documents no pagination for automations or their executions, so each list is
    read in a single request.
    """
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    start = resume.offset if resume is not None else 0

    automations = _fetch(session, f"{GRIDLY_BASE_URL}/automations", {"viewId": view_id}, headers, logger).json()

    for index, automation in enumerate(automations[start:], start=start):
        automation_id = automation["id"]
        url = f"{GRIDLY_BASE_URL}/automations/{automation_id}/executions"
        executions = _fetch(session, url, {}, headers, logger).json()

        resumable_source_manager.save_state(GridlyResumeConfig(offset=index + 1))
        if executions:
            yield [{**execution, "automationId": automation_id} for execution in executions]
        else:
            resumable_source_manager.safe_point()


def _iter_record_histories(
    session: requests.Session,
    view_id: str,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[GridlyResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    """Yield the history entries of every record of the view, one paginated walk per record.

    A history entry carries no record id, so each row gets the `recordId` of the record it belongs to.
    """
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    record_offset = resume.offset if resume is not None else 0
    # Only the first record of a resumed walk starts partway through its history.
    resume_history_offset = resume.history_offset if resume is not None else 0
    if record_offset:
        logger.debug(
            f"Gridly: resuming record histories from record offset={record_offset}, "
            f"history offset={resume_history_offset}"
        )

    records_url = f"{GRIDLY_BASE_URL}/views/{view_id}/records"

    while True:
        records_page = json.dumps({"offset": record_offset, "limit": PAGE_SIZE}, separators=(",", ":"))
        records = _fetch(session, records_url, {"page": records_page}, headers, logger).json()

        for record in records:
            record_id = record["id"]
            record_offset += 1
            # Record ids are customer-defined, so they may hold `/`, `?` or `#`.
            url = f"{records_url}/{quote(str(record_id), safe='')}/histories"
            history_offset = resume_history_offset
            resume_history_offset = 0

            while True:
                page = json.dumps({"offset": history_offset, "limit": PAGE_SIZE}, separators=(",", ":"))
                histories = _fetch(
                    session, url, {"page": page}, headers, logger, redacted_url=f"{records_url}/{{recordId}}/histories"
                ).json()
                history_offset += len(histories)
                is_last_page = len(histories) < PAGE_SIZE

                # An earlier page keeps the cursor on this record, at the page after it, so a resume
                # neither skips the pages that follow nor replays the ones already written. The last
                # page moves the cursor to the next record.
                if is_last_page:
                    resumable_source_manager.save_state(GridlyResumeConfig(offset=record_offset))
                else:
                    resumable_source_manager.save_state(
                        GridlyResumeConfig(offset=record_offset - 1, history_offset=history_offset)
                    )
                if histories:
                    yield [{**history, "recordId": record_id} for history in histories]
                else:
                    resumable_source_manager.safe_point()
                if is_last_page:
                    break

        if len(records) < PAGE_SIZE:
            break


def _iter_hierarchy(
    session: requests.Session,
    endpoint: str,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    """Walk the project > database > grid > view hierarchy down to `endpoint`.

    Only `projects` lists without a parent, so each lower level fans out over every row of the
    level above it, one unpaginated request per parent.
    """
    endpoint_config = GRIDLY_ENDPOINTS[endpoint]
    url = f"{GRIDLY_BASE_URL}/{endpoint}"

    if endpoint_config.parent is None or endpoint_config.parent_id_param is None:
        rows = _fetch(session, url, {}, headers, logger).json()
        if rows:
            yield rows
        return

    parent_id_param = endpoint_config.parent_id_param
    for parents in _iter_hierarchy(session, endpoint_config.parent, headers, logger):
        for parent in parents:
            rows = _fetch(session, url, {parent_id_param: parent["id"]}, headers, logger).json()
            if rows:
                yield [{**row, parent_id_param: parent["id"]} for row in rows]


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
    elif endpoint in ("projects", "databases", "grids", "views", "branches"):
        yield from _iter_hierarchy(session, endpoint, headers, logger)
    elif endpoint == "dependencies":
        yield from _iter_dependencies(session, view_id, headers, logger)
    elif endpoint == "automation_executions":
        yield from _iter_automation_executions(session, view_id, headers, logger, resumable_source_manager)
    elif endpoint == "record_histories":
        yield from _iter_record_histories(session, view_id, headers, logger, resumable_source_manager)
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
