import dataclasses
from collections.abc import Iterator
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.datetime_utils import (
    coerce_datetime_to_utc,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.paperform.settings import (
    PAPERFORM_ENDPOINTS,
    PaperformEndpointConfig,
)

PAPERFORM_BASE_URL = "https://api.paperform.co/v1"
# Paginated list endpoints cap `limit` at 100 (default 20); the largest page minimises round trips
# against the 60 req/min rate limit.
PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 5
# Cheap endpoint used to confirm an API key is genuine. The key is account-wide, so one probe
# validates the credential for every Standard API endpoint.
DEFAULT_PROBE_PATH = "/forms"


class PaperformRetryableError(Exception):
    pass


@dataclasses.dataclass
class PaperformResumeConfig:
    # `after_id` cursor for the next page to fetch. None starts a list at its first page.
    cursor: str | None = None
    # The form currently being processed. A stable form-ID bookmark (not a positional index) so a
    # form added or removed between a crash and the retry can't resume us into the wrong form. None
    # for the account-level endpoints (forms, spaces).
    form_id: str | None = None


def _headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}


def _format_after_date(value: Any) -> str:
    """Format the incremental watermark for Paperform's `after_date` filter (UTC ISO 8601).

    Truncates to whole seconds, which rounds the lower bound *down* — so a sync re-fetches at most
    a few boundary rows (the merge dedupes them on the primary key) rather than skipping any.
    """
    normalized_value = coerce_datetime_to_utc(value)
    if normalized_value is None:
        return str(value)
    return normalized_value.strftime("%Y-%m-%dT%H:%M:%SZ")


def _page_params(cursor: str | None, after_date: str | None) -> dict[str, Any]:
    # Ascending creation order keeps already-fetched pages stable while new rows arrive (they only
    # ever append) and matches the pipeline's ascending incremental watermark bookkeeping.
    params: dict[str, Any] = {"limit": PAGE_SIZE, "sort": "ASC"}
    if cursor is not None:
        # The API documents `after_date` as overwritten by `after_id`, so only the first page
        # carries the watermark; later pages advance purely on the id cursor.
        params["after_id"] = cursor
    elif after_date is not None:
        params["after_date"] = after_date
    return params


@retry(
    retry=retry_if_exception_type((PaperformRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(MAX_RETRIES),
    wait=wait_exponential_jitter(initial=1, max=60),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    path: str,
    params: dict[str, Any],
    logger: FilteringBoundLogger,
) -> dict[str, Any]:
    response = session.get(
        f"{PAPERFORM_BASE_URL}{path}",
        params=params,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    # Paperform rate-limits at 60 req/min and returns 429 with rate-limit headers; exponential
    # backoff comfortably outlasts the one-minute window.
    if response.status_code == 429 or response.status_code >= 500:
        raise PaperformRetryableError(f"Paperform API error (retryable): status={response.status_code}, path={path}")

    if not response.ok:
        logger.error(f"Paperform API error: status={response.status_code}, body={response.text}, path={path}")
        response.raise_for_status()

    data = response.json()
    if not isinstance(data, dict):
        raise PaperformRetryableError(f"Paperform returned an unexpected payload for {path}: {type(data).__name__}")

    return data


def _extract_rows(data: dict[str, Any], config: PaperformEndpointConfig, path: str) -> list[dict[str, Any]]:
    # Every list endpoint wraps rows as {"results": {"<resource>": [...]}, "has_more": bool, ...}.
    results = data.get("results")
    if not isinstance(results, dict) or not isinstance(results.get(config.results_key), list):
        raise PaperformRetryableError(f"Paperform returned an unexpected 'results' payload for {path}")
    return results[config.results_key]


def _iter_pages(
    session: requests.Session,
    config: PaperformEndpointConfig,
    path: str,
    logger: FilteringBoundLogger,
    manager: ResumableSourceManager[PaperformResumeConfig],
    start_cursor: str | None,
    after_date: str | None,
    form_id: str | None,
) -> Iterator[list[dict[str, Any]]]:
    """Page through a paginated list endpoint, yielding one page of raw rows at a time.

    Saves resume state AFTER yielding each page (pointing at the next page) so a crash re-fetches
    the in-flight page rather than skipping it — the merge dedupes the re-pulled rows on the
    primary key.
    """
    cursor = start_cursor
    while True:
        data = _fetch_page(session, path, _page_params(cursor, after_date), logger)
        items = _extract_rows(data, config, path)

        if items:
            yield items

        # `has_more` is false (or the page came back empty) once we've reached the end of the list.
        if not data.get("has_more") or not items:
            break

        cursor = str(items[-1]["id"])
        manager.save_state(PaperformResumeConfig(cursor=cursor, form_id=form_id))


def _iter_form_ids(session: requests.Session, logger: FilteringBoundLogger) -> Iterator[str]:
    """Page through /forms and yield each form id, for fanning out form-scoped endpoints."""
    cursor: str | None = None
    while True:
        data = _fetch_page(session, "/forms", _page_params(cursor, after_date=None), logger)
        items = _extract_rows(data, PAPERFORM_ENDPOINTS["forms"], "/forms")
        for item in items:
            yield str(item["id"])
        if not data.get("has_more") or not items:
            break
        cursor = str(items[-1]["id"])


def _get_top_level_rows(
    session: requests.Session,
    config: PaperformEndpointConfig,
    logger: FilteringBoundLogger,
    manager: ResumableSourceManager[PaperformResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    resume = manager.load_state() if manager.can_resume() else None
    start_cursor = resume.cursor if resume else None
    yield from _iter_pages(session, config, config.path, logger, manager, start_cursor, after_date=None, form_id=None)


def _get_form_scoped_rows(
    session: requests.Session,
    config: PaperformEndpointConfig,
    logger: FilteringBoundLogger,
    manager: ResumableSourceManager[PaperformResumeConfig],
    after_date: str | None,
) -> Iterator[list[dict[str, Any]]]:
    """Fan a form-scoped endpoint out over every form, injecting `form_id` into each row.

    Fields, products, and coupons don't carry their form id in the response, so we add it here to
    keep the composite ["form_id", ...] key unique across the whole table. Submissions already
    include `form_id` — the payload value wins over the injected one.
    """
    form_ids = list(_iter_form_ids(session, logger))

    # Resolve the saved form-ID bookmark to the slice of forms still to process. If the bookmarked
    # form no longer exists (deleted between runs), start over — merge dedupes the re-pulled rows.
    resume = manager.load_state() if manager.can_resume() else None
    remaining = form_ids
    resume_cursor: str | None = None
    if resume is not None and resume.form_id is not None and resume.form_id in form_ids:
        remaining = form_ids[form_ids.index(resume.form_id) :]
        resume_cursor = resume.cursor
        logger.debug(f"Paperform: resuming {config.name} from form_id={resume.form_id}, cursor={resume_cursor}")

    for index, form_id in enumerate(remaining):
        path = config.path.format(form_id=form_id)
        start_cursor = resume_cursor  # only the resumed-into form uses the saved cursor
        resume_cursor = None

        if config.paginated:
            for items in _iter_pages(session, config, path, logger, manager, start_cursor, after_date, form_id):
                yield [{"form_id": form_id, **item} for item in items]
        else:
            # Fields, products, and coupons return the whole collection in one response.
            data = _fetch_page(session, path, {}, logger)
            items = _extract_rows(data, config, path)
            if items:
                yield [{"form_id": form_id, **item} for item in items]

        # Advance the bookmark to the next form so a crash between forms resumes correctly. Its
        # first page is fetched fresh (cursor=None).
        if index + 1 < len(remaining):
            manager.save_state(PaperformResumeConfig(cursor=None, form_id=remaining[index + 1]))


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PaperformResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> Iterator[list[dict[str, Any]]]:
    config = PAPERFORM_ENDPOINTS[endpoint]
    # One session reused across every page (and every form, for fan-out) so urllib3 keeps the
    # connection alive instead of re-handshaking per request. The API key is redacted from logs.
    session = make_tracked_session(headers=_headers(api_key), redact_values=(api_key,))

    after_date: str | None = None
    if should_use_incremental_field and config.incremental_fields and db_incremental_field_last_value is not None:
        after_date = _format_after_date(db_incremental_field_last_value)

    if config.form_scoped:
        yield from _get_form_scoped_rows(session, config, logger, resumable_source_manager, after_date)
    else:
        yield from _get_top_level_rows(session, config, logger, resumable_source_manager)


def paperform_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PaperformResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = PAPERFORM_ENDPOINTS[endpoint]

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
        # We request `sort=ASC` (creation order) on every paginated endpoint, so rows arrive
        # oldest-first within each form and the ascending watermark bookkeeping is correct.
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def check_access(api_key: str, path: str = DEFAULT_PROBE_PATH) -> tuple[int, Optional[str]]:
    """Probe a single endpoint to validate the API key.

    Returns ``(status, message)``: ``200`` reachable, ``401``/``403`` auth failure, ``0`` for a
    connection problem, other HTTP status otherwise.
    """
    session = make_tracked_session(headers=_headers(api_key), redact_values=(api_key,))
    try:
        response = session.get(f"{PAPERFORM_BASE_URL}{path}", params={"limit": 1}, timeout=15)
    except Exception as e:
        return 0, f"Could not connect to Paperform: {e}"

    if response.status_code in (401, 403):
        return response.status_code, None

    if not response.ok:
        return response.status_code, f"Paperform returned HTTP {response.status_code}"

    return 200, None


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    status, message = check_access(api_key)
    if status == 200:
        return True, None
    if status == 401:
        return False, "Invalid Paperform API key"
    if status == 403:
        # The key authenticated but the account can't use the API — Paperform gates API access
        # behind its paid plans.
        return (
            False,
            "Your Paperform plan does not include API access. API access requires a Pro, Business, or Agency plan.",
        )
    return False, message or "Could not validate Paperform API key"
