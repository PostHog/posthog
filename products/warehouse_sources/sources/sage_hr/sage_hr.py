import re
import json
import hashlib
import dataclasses
from collections import Counter
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import quote, urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import RetryCallState, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.sources.sage_hr.settings import SAGE_HR_ENDPOINTS, SageHREndpointConfig
from products.warehouse_sources.sources.sdk import (
    ResumableSourceManager,
    SourceResponse,
    SyncWindow,
    make_tracked_session,
    reach_safe_point,
    retry_with_deadline,
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


@dataclasses.dataclass(frozen=True)
class SageHRResumeConfig:
    # Next 1-indexed page to fetch (from the response `meta.next_page`). None means "start over".
    next_page: int | None = None
    # For the windowed leave_requests endpoint: ISO date of the window `next_page` belongs to.
    window_from: str | None = None
    # For fan-out endpoints: the parent page, and the index and id on it of the parent `next_page` belongs to.
    parent_page: int | None = None
    parent_index: int | None = None
    parent_id: Any = None
    # For endpoints with derived row ids: how often each row hash already appeared under `parent_id`.
    row_occurrences: dict[str, int] | None = None


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


def _safe_point_before_retry_wait(_state: RetryCallState) -> None:
    # Each page is fetched only after the rows before it are yielded, and nothing is buffered.
    reach_safe_point()


@retry_with_deadline(
    retry=retry_if_exception_type((SageHRRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    before_sleep=_safe_point_before_retry_wait,
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


def _leave_window_range() -> SyncWindow[date]:
    """Full date range the leave_requests sync covers: account prehistory through future bookings."""
    today = datetime.now(UTC).date()
    return SyncWindow(start=date.fromisoformat(LEAVE_WINDOW_START), end=today + timedelta(days=LEAVE_FUTURE_DAYS))


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
    window = _leave_window_range()
    resume_from = date.fromisoformat(resume.window_from) if resume and resume.window_from else None
    # The docs don't state whether `from`/`to` match on overlap or containment, so a request spanning
    # a window boundary may come back from both windows. Full-refresh batches append without merging,
    # so drop ids already yielded this sync. (After a mid-sync resume the set starts empty — a rare
    # boundary duplicate then persists until the next successful full sync replaces the table.)
    seen_ids: set[Any] = set()

    for window_start, window_end in _iter_windows(window.start, window.end):
        if resume_from is not None and window_start < resume_from:
            continue

        page = 1
        if resume is not None and resume.next_page is not None and resume.window_from == window_start.isoformat():
            page = resume.next_page
        next_window_start = window_end + timedelta(days=1)

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

            # `next_page` is null on the last page; an empty or non-advancing page also terminates
            # defensively so a bad meta block can never produce an infinite loop.
            has_next_page = bool(next_page and items and next_page > page)
            if has_next_page:
                resumable_source_manager.save_state(
                    SageHRResumeConfig(next_page=next_page, window_from=window_start.isoformat())
                )
            elif next_window_start <= window.end:
                # Window exhausted: a resume can skip straight to the next window.
                resumable_source_manager.save_state(
                    SageHRResumeConfig(next_page=1, window_from=next_window_start.isoformat())
                )
            if fresh:
                yield fresh
            else:
                # Most windows are empty, so the walk needs a stop point that does not depend on rows.
                resumable_source_manager.safe_point()

            if not has_next_page or next_page is None:
                break
            page = next_page


def _derive_row_id(parent_id: Any, row: dict[str, Any], occurrences: Counter[str]) -> str:
    payload = json.dumps({"parent": parent_id, "row": row}, sort_keys=True, default=str)
    row_hash = hashlib.sha256(payload.encode()).hexdigest()[:32]
    # Identical rows under one parent would share a hash, so each repeat adds its ordinal to stay unique.
    occurrence = occurrences[row_hash]
    occurrences[row_hash] += 1
    if not occurrence:
        return row_hash
    return hashlib.sha256(f"{row_hash}#{occurrence}".encode()).hexdigest()[:32]


def _shape_child_row(
    config: SageHREndpointConfig, parent_key: str, parent_id: Any, row: dict[str, Any], occurrences: Counter[str]
) -> dict[str, Any]:
    shaped = {**row, parent_key: parent_id}
    if config.derive_row_id:
        shaped["id"] = _derive_row_id(parent_id, row, occurrences)
    return shaped


def _get_fan_out_rows(
    session: requests.Session,
    base_url: str,
    config: SageHREndpointConfig,
    resume: SageHRResumeConfig | None,
    resumable_source_manager: ResumableSourceManager[SageHRResumeConfig],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    fan_out = config.fan_out
    if fan_out is None:
        raise ValueError(f"Sage HR endpoint {config.name} has no fan-out parent")

    parent_page = resume.parent_page if resume is not None and resume.parent_page is not None else 1
    resume_index = resume.parent_index if resume is not None and resume.parent_index is not None else 0
    resume_child_page = resume.next_page if resume is not None and resume.next_page is not None else 1
    is_resumed_page = resume is not None

    while True:
        parents, next_parent_page = _fetch_page(
            session, _build_url(base_url, fan_out.parent_path, {"page": parent_page}), logger
        )
        has_next_parent_page = bool(next_parent_page and parents and next_parent_page > parent_page)
        first_index, first_child_page = 0, 1
        if is_resumed_page and resume is not None:
            # The parent list can shift between attempts, so the saved child page applies only to the
            # parent with the saved id. A parent that is gone restarts at its saved index from page 1.
            first_index = resume_index
            for candidate_index, parent in enumerate(parents):
                if resume.parent_id is not None and parent.get("id") == resume.parent_id:
                    first_index, first_child_page = candidate_index, resume_child_page
                    break

        for index in range(first_index, len(parents)):
            parent_id = parents[index]["id"]
            child_path = config.path.format(id=quote(str(parent_id), safe=""))
            child_page = first_child_page if index == first_index else 1
            occurrences: Counter[str] = Counter()
            if is_resumed_page and resume is not None and child_page > 1 and index == first_index:
                occurrences.update(resume.row_occurrences or {})

            while True:
                params = {"page": child_page} if config.paginated else {}
                items, next_child_page = _fetch_page(session, _build_url(base_url, child_path, params), logger)
                has_next_child_page = config.paginated and bool(
                    next_child_page and items and next_child_page > child_page
                )

                # Shape before staging the cursor, so the saved occurrences cover this page's rows.
                rows = [_shape_child_row(config, fan_out.parent_key, parent_id, row, occurrences) for row in items]

                if has_next_child_page:
                    resumable_source_manager.save_state(
                        SageHRResumeConfig(
                            next_page=next_child_page,
                            parent_page=parent_page,
                            parent_index=index,
                            parent_id=parent_id,
                            row_occurrences=dict(occurrences) if config.derive_row_id else None,
                        )
                    )
                elif index + 1 < len(parents):
                    resumable_source_manager.save_state(
                        SageHRResumeConfig(
                            next_page=1,
                            parent_page=parent_page,
                            parent_index=index + 1,
                            parent_id=parents[index + 1]["id"],
                        )
                    )
                elif has_next_parent_page:
                    resumable_source_manager.save_state(
                        SageHRResumeConfig(next_page=1, parent_page=next_parent_page, parent_index=0)
                    )

                if rows:
                    yield rows
                else:
                    # Many parents have no children, so the walk needs a stop point that does not depend on rows.
                    resumable_source_manager.safe_point()

                if not has_next_child_page or next_child_page is None:
                    break
                child_page = next_child_page

        is_resumed_page = False
        if not has_next_parent_page or next_parent_page is None:
            break
        parent_page = next_parent_page


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

    if config.fan_out is not None:
        yield from _get_fan_out_rows(session, base_url, config, resume, resumable_source_manager, logger)
        return

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
        # `next_page` is null on the last page; an empty or non-advancing page also terminates
        # defensively so a bad meta block can never produce an infinite loop.
        has_next_page = bool(next_page and items and next_page > page)
        if has_next_page:
            resumable_source_manager.save_state(SageHRResumeConfig(next_page=next_page))
        if items:
            yield items

        if not has_next_page or next_page is None:
            break
        page = next_page


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
