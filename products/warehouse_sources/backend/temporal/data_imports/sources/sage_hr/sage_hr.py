import re
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.sage_hr.settings import (
    SAGE_HR_ENDPOINTS,
    SageHREndpointConfig,
)

REQUEST_TIMEOUT_SECONDS = 60
# Credential validation is a single cheap probe; keep it snappy so source creation doesn't feel hung.
VALIDATE_TIMEOUT_SECONDS = 15
# Cheap collection endpoint used to confirm the subdomain + API key are genuine.
DEFAULT_PROBE_PATH = "/employees"

# Time off requests default to the current month unless an explicit `from`/`to` window is passed,
# and the API rejects windows of 65 days or more — so a full sync walks fixed-size windows from a
# start date predating any Sage HR (formerly CakeHR, launched 2013) account through to future
# bookings. Sage HR doesn't publish rate limits, but ~100 mostly-empty window probes per sync is a
# trivial request volume.
LEAVE_WINDOW_START = "2010-01-01"
LEAVE_WINDOW_DAYS = 60
LEAVE_FUTURE_DAYS = 730

# A single DNS label: letters, digits, hyphens. Rejects anything that could retarget the host
# (slashes, `@`, dots) so the stored API key is only ever sent to `<subdomain>.sage.hr`.
_SUBDOMAIN_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")


class SageHRRetryableError(Exception):
    pass


@dataclasses.dataclass
class SageHRResumeConfig:
    # Next 1-indexed page to fetch (from the response `meta.next_page`). None means "start over".
    next_page: int | None = None
    # For the windowed leave_requests endpoint: ISO date of the window `next_page` belongs to.
    window_from: str | None = None


def normalize_subdomain(subdomain: str) -> str:
    """Reduce user input to a bare, validated Sage HR subdomain label.

    Accepts either the full host (``yourcompany.sage.hr``) or the bare subdomain
    (``yourcompany``). Raises ``ValueError`` on anything that isn't a single DNS label so the
    API key can never be retargeted away from ``<subdomain>.sage.hr``.
    """
    cleaned = subdomain.strip().removeprefix("https://").removeprefix("http://")
    cleaned = cleaned.strip("/")
    cleaned = cleaned.removesuffix(".sage.hr")
    if not _SUBDOMAIN_RE.match(cleaned):
        raise ValueError(
            f"Invalid Sage HR company subdomain: {subdomain!r}. Enter just your subdomain, e.g. 'yourcompany' "
            "for yourcompany.sage.hr."
        )
    return cleaned


def _base_url(subdomain: str) -> str:
    return f"https://{normalize_subdomain(subdomain)}.sage.hr/api"


def _headers(api_key: str) -> dict[str, str]:
    return {"X-Auth-Token": api_key, "Accept": "application/json"}


def _build_url(base_url: str, path: str, params: dict[str, Any]) -> str:
    if not params:
        return f"{base_url}{path}"
    return f"{base_url}{path}?{urlencode(params)}"


def _extract_next_page(payload: dict[str, Any]) -> int | None:
    # Collection responses carry a `meta` block: current_page, next_page, previous_page,
    # total_pages, per_page, total_entries. `next_page` is null on the last page. Unpaginated
    # endpoints omit `meta` entirely, which reads as a single page.
    meta = payload.get("meta")
    if not isinstance(meta, dict):
        return None
    next_page = meta.get("next_page")
    return next_page if isinstance(next_page, int) else None


@retry(
    retry=retry_if_exception_type((SageHRRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    url: str,
    logger: FilteringBoundLogger,
) -> tuple[list[dict[str, Any]], int | None]:
    response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429 or response.status_code >= 500:
        raise SageHRRetryableError(f"Sage HR API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Sage HR API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    payload = response.json()
    # Collection endpoints wrap results in {"data": [...], "meta": {...}}.
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise SageHRRetryableError(f"Sage HR returned an unexpected payload for {url}: {type(payload).__name__}")

    return payload["data"], _extract_next_page(payload)


def _leave_window_range() -> tuple[date, date]:
    """Full date range the leave_requests sync covers: account prehistory through future bookings."""
    today = datetime.now(UTC).date()
    return date.fromisoformat(LEAVE_WINDOW_START), today + timedelta(days=LEAVE_FUTURE_DAYS)


def _iter_windows(start: date, end: date) -> Iterator[tuple[date, date]]:
    cursor = start
    while cursor <= end:
        window_end = min(cursor + timedelta(days=LEAVE_WINDOW_DAYS - 1), end)
        yield cursor, window_end
        cursor = window_end + timedelta(days=1)


def _get_windowed_rows(
    session: requests.Session,
    base_url: str,
    config: SageHREndpointConfig,
    resume: SageHRResumeConfig | None,
    resumable_source_manager: ResumableSourceManager[SageHRResumeConfig],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    start, end = _leave_window_range()
    resume_from = date.fromisoformat(resume.window_from) if resume and resume.window_from else None
    # The docs don't state whether `from`/`to` match on overlap or containment, so a request spanning
    # a window boundary may come back from both windows. Full-refresh batches append without merging,
    # so drop ids already yielded this sync. (After a mid-sync resume the set starts empty — a rare
    # boundary duplicate then persists until the next successful full sync replaces the table.)
    seen_ids: set[Any] = set()

    for window_start, window_end in _iter_windows(start, end):
        if resume_from is not None and window_start < resume_from:
            continue

        page = 1
        if resume is not None and resume.next_page is not None and resume.window_from == window_start.isoformat():
            page = resume.next_page

        while True:
            params = {"page": page, "from": window_start.isoformat(), "to": window_end.isoformat()}
            items, next_page = _fetch_page(session, _build_url(base_url, config.path, params), logger)

            fresh = []
            for row in items:
                # `id` is the declared primary key — fail loudly on a missing one rather than
                # silently yielding rows the dedupe (and later merges) can't identify.
                row_id = row["id"]
                if row_id in seen_ids:
                    continue
                seen_ids.add(row_id)
                fresh.append(row)
            if fresh:
                yield fresh

            # `next_page` is null on the last page; an empty or non-advancing page also terminates
            # defensively so a bad meta block can never produce an infinite loop.
            if not next_page or not items or next_page <= page:
                break

            page = next_page
            # Save AFTER yielding so a crash re-fetches from the next page (already-yielded pages
            # are persisted).
            resumable_source_manager.save_state(
                SageHRResumeConfig(next_page=page, window_from=window_start.isoformat())
            )

        # Window exhausted — everything up to it has been yielded, so a resume can skip straight to
        # the next window.
        next_window_start = window_end + timedelta(days=1)
        if next_window_start <= end:
            resumable_source_manager.save_state(
                SageHRResumeConfig(next_page=1, window_from=next_window_start.isoformat())
            )


def get_rows(
    subdomain: str,
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SageHRResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = SAGE_HR_ENDPOINTS[endpoint]
    session = make_tracked_session(headers=_headers(api_key), redact_values=(api_key,))
    base_url = _base_url(subdomain)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None:
        logger.debug(f"Sage HR: resuming {endpoint} from page={resume.next_page}, window={resume.window_from}")

    if config.requires_date_window:
        yield from _get_windowed_rows(session, base_url, config, resume, resumable_source_manager, logger)
        return

    if not config.paginated:
        items, _ = _fetch_page(session, _build_url(base_url, config.path, {}), logger)
        if items:
            yield items
        return

    page = resume.next_page if (resume is not None and resume.next_page is not None) else 1
    while True:
        items, next_page = _fetch_page(session, _build_url(base_url, config.path, {"page": page}), logger)
        if items:
            yield items

        # `next_page` is null on the last page; an empty or non-advancing page also terminates
        # defensively so a bad meta block can never produce an infinite loop.
        if not next_page or not items or next_page <= page:
            break

        page = next_page
        # Save AFTER yielding so a crash re-fetches from the next page (already-yielded pages are
        # persisted).
        resumable_source_manager.save_state(SageHRResumeConfig(next_page=page))


def sage_hr_source(
    subdomain: str,
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SageHRResumeConfig],
) -> SourceResponse:
    config = SAGE_HR_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            subdomain=subdomain,
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
    )


def check_access(subdomain: str, api_key: str, path: str = DEFAULT_PROBE_PATH) -> tuple[int, Optional[str]]:
    """Probe a single collection endpoint to validate the subdomain + API key.

    Returns ``(status, message)``: ``200`` reachable, ``401``/``403`` auth failure, ``0`` for a
    connection problem, other HTTP status otherwise.
    """
    try:
        url = _build_url(_base_url(subdomain), path, {"page": 1})
    except ValueError as e:
        return 0, str(e)

    session = make_tracked_session(headers=_headers(api_key), redact_values=(api_key,))
    try:
        response = session.get(url, timeout=VALIDATE_TIMEOUT_SECONDS)
    except Exception:
        return 0, "Could not connect to Sage HR. Check the company subdomain and try again."

    if response.status_code in (401, 403):
        return response.status_code, None

    if response.status_code == 404:
        return 404, "Sage HR company subdomain not found. Use the subdomain from your Sage HR URL."

    if not response.ok:
        return response.status_code, f"Sage HR returned HTTP {response.status_code}"

    return 200, None


def validate_credentials(subdomain: str, api_key: str) -> tuple[bool, str | None]:
    status, message = check_access(subdomain, api_key)
    if status == 200:
        return True, None
    if status == 401:
        return False, "Invalid Sage HR API key. Make sure API access is enabled under Settings → Integrations → API."
    if status == 403:
        return (
            False,
            "Your Sage HR API key does not have access to this data. Check that API access is enabled under Settings → Integrations → API.",
        )
    return False, message or "Could not validate Sage HR credentials"
