import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.concord.settings import (
    AGREEMENT_STATUSES,
    CONCORD_ENDPOINTS,
    ConcordEndpointConfig,
)

# Concord exposes the same REST surface on two hosts; the API key is environment-specific.
CONCORD_BASE_URLS = {
    "production": "https://api.concordnow.com/api/rest/1",
    "sandbox": "https://uat.concordnow.com/api/rest/1",
}

REQUEST_TIMEOUT_SECONDS = 60
# The events audit endpoint rejects ranges longer than 7 days, so walk it a week at a time.
EVENTS_WINDOW_DAYS = 7


class ConcordRetryableError(Exception):
    pass


@dataclasses.dataclass(frozen=False)
class ConcordResumeConfig:
    # Page index to fetch on resume (page-number pagination). 0-based, matching Concord.
    page: Optional[int] = None
    # Row offset to fetch on resume (offset pagination).
    offset: Optional[int] = None
    # Rows of `page`/`offset` already emitted, so a resume skips them rather than re-walking the
    # whole page. Advances on every mid-page flush so progress is monotonic even across crashes.
    row_offset: Optional[int] = None
    # Start of the next audit-log window as a Unix ms timestamp (events_window pagination).
    window_start_ms: Optional[int] = None
    # Position in the agreements walk a fan-out endpoint resumes at: the parent page, and the index
    # of the agreement within it whose children were in flight.
    parent_page: Optional[int] = None
    parent_index: Optional[int] = None


def base_url_for_environment(environment: str | None) -> str:
    return CONCORD_BASE_URLS.get(environment or "production", CONCORD_BASE_URLS["production"])


def _headers(api_key: str) -> dict[str, str]:
    return {"X-API-KEY": api_key, "Accept": "application/json"}


def _to_epoch_ms(value: Any) -> int | None:
    """Coerce an incremental cursor value into a Unix millisecond timestamp.

    Concord's date filters are all Unix epoch milliseconds. The pipeline may hand us a datetime
    (first parse) or an int/float (already-stored cursor), so normalize both.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return int(aware.timestamp() * 1000)
    if isinstance(value, date):
        return int(datetime.combine(value, datetime.min.time(), tzinfo=UTC).timestamp() * 1000)
    if isinstance(value, int | float):
        return int(value)
    return None


def _epoch_ms_to_date(value: int) -> date:
    return datetime.fromtimestamp(value / 1000, tz=UTC).date()


def _build_url(base_url: str, path: str, params: dict[str, Any] | None = None) -> str:
    url = f"{base_url}{path}"
    if not params:
        return url
    # doseq=True so list-valued params (e.g. repeated `statuses`) expand to repeated keys.
    return f"{url}?{urlencode(params, doseq=True)}"


@retry(
    retry=retry_if_exception_type((ConcordRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch(session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger) -> Any:
    response = session.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429 or response.status_code >= 500:
        raise ConcordRetryableError(f"Concord API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        # Don't log the response body: Concord error payloads can echo contract/member/audit data
        # back, and these logs are readable internally. Status + URL is enough to triage.
        logger.error(f"Concord API error: status={response.status_code}, url={url}")
        response.raise_for_status()

    return response.json()


def resolve_organization_id(
    session: requests.Session, base_url: str, api_key: str, configured_org_id: str | None, logger: FilteringBoundLogger
) -> str:
    """Return the organization id to scope requests under.

    Uses the user-provided id when set, otherwise resolves the first organization the API key can
    see. Every data endpoint is scoped under /organizations/{id}/, so this must succeed before any
    org-scoped sync runs.
    """
    if configured_org_id and configured_org_id.strip():
        return configured_org_id.strip()

    data = _fetch(session, f"{base_url}/user/me/organizations", _headers(api_key), logger)
    organizations = data.get("organizations") or []
    if not organizations:
        raise ValueError("No Concord organizations are accessible with this API key.")
    return str(organizations[0]["id"])


def validate_credentials(api_key: str, environment: str | None) -> bool:
    base_url = base_url_for_environment(environment)
    try:
        # Concord auth is a custom `X-API-KEY` header the name-based scrubber can't recognise, so
        # redact the key by value from logged URLs and captured HTTP samples.
        response = make_tracked_session(redact_values=(api_key,)).get(
            f"{base_url}/user/me/organizations", headers=_headers(api_key), timeout=10
        )
        return response.status_code == 200
    except Exception:
        return False


def _select_rows(
    payload: Any, selector: str | None, logger: FilteringBoundLogger | None = None
) -> list[dict[str, Any]]:
    if selector is None:
        return []
    if isinstance(payload, dict):
        # A non-empty body that lacks the expected key usually means Concord changed its response
        # shape — surface it so the sync doesn't silently complete with zero rows.
        if selector not in payload and payload and logger is not None:
            logger.warning(f"Concord response missing expected key '{selector}'; got keys={list(payload.keys())}")
        rows = payload.get(selector)
    else:
        rows = None
    return rows or []


def _select_child_rows(
    payload: Any,
    selector: str | None,
    logger: FilteringBoundLogger | None = None,
    single_object: bool = False,
) -> list[dict[str, Any]]:
    """Select the rows of a per-agreement child response.

    `/approval`, `/signature` and `/metadata` answer with one object describing the agreement, which
    becomes a single row. `/members` and `/versions` answer with a bare JSON array; every other
    child endpoint wraps its rows in a key.
    """
    if single_object:
        # An agreement with nothing configured answers `{}`, which would seed a row holding only the
        # parent uid — drop it so the table carries a row only where Concord has something to say.
        return [payload] if isinstance(payload, dict) and payload else []
    if selector is None:
        return payload if isinstance(payload, list) else []
    return _select_rows(payload, selector, logger)


def _member_id(row: dict[str, Any]) -> Any:
    """Return the id a member row is keyed on within its agreement.

    `/members` mixes active users, invitations and delayed invitations. Only the invitation shapes
    carry an `invitation` object, so preferring it keeps each `status` on a single id space — user
    ids and invitation ids are separate sequences and would otherwise collide in the primary key.
    """
    invitation = row.get("invitation")
    if isinstance(invitation, dict) and invitation.get("id") is not None:
        return invitation["id"]
    user = row.get("user")
    if isinstance(user, dict):
        return user.get("id")
    return None


def _normalize_child_row(endpoint: str, row: dict[str, Any], agreement_uuid: str) -> dict[str, Any]:
    normalized = {**row, "agreement_uuid": agreement_uuid}
    if endpoint == "agreement_members":
        normalized["member_id"] = _member_id(row)
    return normalized


def _scope_organizations_to_org(rows: list[dict[str, Any]], configured_org_id: str | None) -> list[dict[str, Any]]:
    """Restrict the organizations listing to the single org this source syncs.

    /user/me/organizations returns every org the API key can reach, so without this filter a source
    configured for one organization would still expose every other accessible org's name/id in the
    warehouse table. Mirror resolve_organization_id: keep the configured org, else the first one.
    """
    if not rows:
        return rows
    if configured_org_id and configured_org_id.strip():
        target = configured_org_id.strip()
        return [row for row in rows if str(row.get("id")) == target]
    return rows[:1]


def _flatten_folder_tree(node: Any) -> Iterator[dict[str, Any]]:
    """Flatten Concord's nested folder tree into one row per folder.

    Each row keeps the folder's own fields (id, name, parentId, …) but drops the nested `children`
    array so the warehouse table stays flat; hierarchy is still recoverable via `parentId`.
    """
    if not isinstance(node, dict):
        return
    children = node.get("children") or []
    row = {key: value for key, value in node.items() if key != "children"}
    if "id" in row:
        yield row
    for child in children:
        yield from _flatten_folder_tree(child)


def _agreement_incremental_params(
    incremental_field: str | None,
    db_incremental_field_last_value: Any,
) -> dict[str, Any]:
    last_ms = _to_epoch_ms(db_incremental_field_last_value)
    if last_ms is None:
        return {}
    # `modifiedAt`/`createdAt` are the only fields the schema advertises; default to modifiedAt.
    field = incremental_field if incremental_field in ("modifiedAt", "createdAt") else "modifiedAt"
    return {f"{field}.from": last_ms}


def _iter_page(
    session: requests.Session,
    base_url: str,
    path: str,
    headers: dict[str, str],
    config: ConcordEndpointConfig,
    logger: FilteringBoundLogger,
    batcher: Batcher,
    manager: ResumableSourceManager[ConcordResumeConfig],
    base_params: dict[str, Any],
    start_page: int,
    start_row_offset: int = 0,
) -> Iterator[Any]:
    page = start_page
    # Rows of the first page already emitted in a prior run; skip them so a resume doesn't re-walk
    # the whole page. Only the page we resume on carries a non-zero skip.
    skip = start_row_offset
    while True:
        params = {**base_params, "page": page, "numberOfItemsByPage": config.page_size}
        payload = _fetch(session, _build_url(base_url, path, params), headers, logger)
        rows = _select_rows(payload, config.data_selector, logger)
        for local_index, row in enumerate(rows):
            if local_index < skip:
                continue
            batcher.batch(row)
            if batcher.should_yield():
                yield batcher.get_table()
                # A byte-limit flush can fire mid-page. Checkpoint this page plus how many of its
                # rows are now committed, so a resume skips them instead of re-emitting from the
                # page start. row_offset advances on every flush, so progress is monotonic and a
                # crash can't pin the import to replaying the same rows forever.
                manager.save_state(ConcordResumeConfig(page=page, row_offset=local_index + 1))
        skip = 0
        if len(rows) < config.page_size:
            break
        page += 1


def _iter_offset(
    session: requests.Session,
    base_url: str,
    path: str,
    headers: dict[str, str],
    config: ConcordEndpointConfig,
    logger: FilteringBoundLogger,
    batcher: Batcher,
    manager: ResumableSourceManager[ConcordResumeConfig],
    base_params: dict[str, Any],
    start_offset: int,
    start_row_offset: int = 0,
) -> Iterator[Any]:
    offset = start_offset
    # Rows of the first window already emitted in a prior run; skip them so a resume doesn't re-walk
    # the whole window. Only the offset we resume on carries a non-zero skip.
    skip = start_row_offset
    while True:
        params = {**base_params, config.offset_param: offset, "limit": config.page_size}
        payload = _fetch(session, _build_url(base_url, path, params), headers, logger)
        rows = _select_rows(payload, config.data_selector, logger)
        for local_index, row in enumerate(rows):
            if local_index < skip:
                continue
            batcher.batch(row)
            if batcher.should_yield():
                yield batcher.get_table()
                # A byte-limit flush can fire mid-window. Checkpoint this offset plus how many of
                # its rows are now committed, so a resume skips them instead of re-emitting from the
                # window start. row_offset advances on every flush, so progress is monotonic and a
                # crash can't pin the import to replaying the same rows forever.
                manager.save_state(ConcordResumeConfig(offset=offset, row_offset=local_index + 1))
        skip = 0
        if len(rows) < config.page_size:
            break
        offset += config.page_size


def _iter_events_windows(
    session: requests.Session,
    base_url: str,
    path: str,
    headers: dict[str, str],
    config: ConcordEndpointConfig,
    logger: FilteringBoundLogger,
    batcher: Batcher,
    manager: ResumableSourceManager[ConcordResumeConfig],
    start_ms: int,
    start_row_offset: int = 0,
) -> Iterator[Any]:
    window_start = _epoch_ms_to_date(start_ms)
    today = datetime.now(UTC).date()
    # Rows of the first window already emitted in a prior run; skip them so a resume doesn't re-walk
    # the whole (up to 7-day) window. Only the window we resume on carries a non-zero skip.
    skip = start_row_offset
    while window_start <= today:
        window_end = min(window_start + timedelta(days=EVENTS_WINDOW_DAYS), today)
        params = {"start": window_start.isoformat(), "end": window_end.isoformat()}
        window_start_ms = int(datetime.combine(window_start, datetime.min.time(), tzinfo=UTC).timestamp() * 1000)
        payload = _fetch(session, _build_url(base_url, path, params), headers, logger)
        for local_index, row in enumerate(_select_rows(payload, config.data_selector, logger)):
            if local_index < skip:
                continue
            batcher.batch(row)
            if batcher.should_yield():
                yield batcher.get_table()
                # A byte-limit flush can fire mid-window. Checkpoint this window plus how many of
                # its rows are now committed, so a resume skips them instead of re-walking the whole
                # window. row_offset advances on every flush, so progress is monotonic and a crash
                # can't pin the import to replaying the same window forever.
                manager.save_state(ConcordResumeConfig(window_start_ms=window_start_ms, row_offset=local_index + 1))
        skip = 0
        if window_end >= today:
            break
        # Start the next window on the boundary day we just queried, so the windows overlap by one
        # day. We don't know whether Concord's `end` is inclusive or exclusive, and the overlap is
        # free: merge dedupes on the event id primary key, so no event can fall through the seam.
        next_start = window_end
        manager.save_state(
            ConcordResumeConfig(
                window_start_ms=int(datetime.combine(next_start, datetime.min.time(), tzinfo=UTC).timestamp() * 1000)
            )
        )
        window_start = next_start


def _fetch_child_rows(
    session: requests.Session,
    base_url: str,
    child_path: str,
    headers: dict[str, str],
    config: ConcordEndpointConfig,
    logger: FilteringBoundLogger,
    agreement_uuid: str,
) -> list[dict[str, Any]]:
    """Fetch one agreement's child rows, or none when that agreement is out of reach.

    A key that can list agreements is not guaranteed access to every one of them, and an agreement
    can be deleted while we walk the list. Either would fail the whole table for one bad parent, so
    skip the agreement and keep going.
    """
    try:
        payload = _fetch(session, _build_url(base_url, child_path, config.fanout_params), headers, logger)
    except requests.HTTPError as error:
        status = error.response.status_code if error.response is not None else None
        if status in (403, 404):
            logger.warning(
                f"Skipping Concord agreement for '{config.name}': status={status}, agreement={agreement_uuid}"
            )
            return []
        raise
    return [
        _normalize_child_row(config.name, row, agreement_uuid)
        for row in _select_child_rows(payload, config.data_selector, logger, config.single_object_child)
    ]


def _iter_agreement_fanout(
    session: requests.Session,
    base_url: str,
    org_id: str,
    child_template: str,
    headers: dict[str, str],
    config: ConcordEndpointConfig,
    logger: FilteringBoundLogger,
    batcher: Batcher,
    manager: ResumableSourceManager[ConcordResumeConfig],
    start_page: int,
    start_index: int = 0,
) -> Iterator[Any]:
    """Walk the agreements list and fetch `child_template` once per agreement.

    None of the per-agreement endpoints paginate or expose a change filter, so every sync re-reads
    each agreement's children and merge dedupes on the composite primary key.
    """
    parent_config = CONCORD_ENDPOINTS["agreements"]
    parent_path = parent_config.path.replace("{organization_id}", org_id)

    page = start_page
    # Agreements of the first page whose children a prior run already finished.
    skip = start_index
    while True:
        parent_params: dict[str, Any] = {
            "statuses": AGREEMENT_STATUSES,
            "page": page,
            "numberOfItemsByPage": parent_config.page_size,
        }
        parent_payload = _fetch(session, _build_url(base_url, parent_path, parent_params), headers, logger)
        agreements = _select_rows(parent_payload, parent_config.data_selector, logger)
        for local_index, agreement in enumerate(agreements):
            if local_index < skip:
                continue
            agreement_uuid = agreement.get("uuid")
            if not agreement_uuid:
                continue
            child_path = child_template.replace("{agreement_uid}", str(agreement_uuid))
            for row in _fetch_child_rows(session, base_url, child_path, headers, config, logger, str(agreement_uuid)):
                batcher.batch(row)
                if batcher.should_yield():
                    yield batcher.get_table()
                    # Checkpoint the agreement still in flight rather than the next one: its rows
                    # may be split across this flush and the next, so a resume has to redo it whole.
                    # Merge dedupes the replayed rows on the composite primary key.
                    manager.save_state(ConcordResumeConfig(parent_page=page, parent_index=local_index))
        skip = 0
        if len(agreements) < parent_config.page_size:
            break
        page += 1


def get_rows(
    api_key: str,
    environment: str | None,
    organization_id: str | None,
    endpoint: str,
    logger: FilteringBoundLogger,
    manager: ResumableSourceManager[ConcordResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[Any]:
    config = CONCORD_ENDPOINTS[endpoint]
    base_url = base_url_for_environment(environment)
    headers = _headers(api_key)
    # Concord auth is a custom `X-API-KEY` header the name-based scrubber can't recognise, so redact
    # the key by value from logged URLs and captured HTTP samples.
    session = make_tracked_session(redact_values=(api_key,))
    batcher = Batcher(logger=logger, chunk_size=2000, chunk_size_bytes=100 * 1024 * 1024)

    org_id = resolve_organization_id(session, base_url, api_key, organization_id, logger) if config.org_scoped else None
    # `.replace` not `.format`: fan-out paths still carry an unresolved `{agreement_uid}`.
    path = config.path.replace("{organization_id}", org_id) if org_id else config.path

    base_params: dict[str, Any] = {}
    if config.org_in_query and org_id:
        base_params["organizationId"] = org_id

    resume = manager.load_state() if manager.can_resume() else None

    if config.pagination == "single":
        payload = _fetch(session, _build_url(base_url, path, base_params), headers, logger)
        rows = _select_rows(payload, config.data_selector, logger)
        if config.scope_to_org:
            rows = _scope_organizations_to_org(rows, organization_id)
        for row in rows:
            batcher.batch(row)
            if batcher.should_yield():
                yield batcher.get_table()

    elif config.pagination == "folders_tree":
        payload = _fetch(session, _build_url(base_url, path, base_params), headers, logger)
        nodes = payload if isinstance(payload, list) else [payload]
        for node in nodes:
            for row in _flatten_folder_tree(node):
                batcher.batch(row)
                if batcher.should_yield():
                    yield batcher.get_table()

    elif config.pagination == "page":
        if should_use_incremental_field and config.supports_incremental:
            base_params.update(_agreement_incremental_params(incremental_field, db_incremental_field_last_value))
        if endpoint == "agreements":
            base_params["statuses"] = AGREEMENT_STATUSES
        start_page = resume.page if resume and resume.page is not None else 0
        start_row_offset = resume.row_offset if resume and resume.row_offset is not None else 0
        yield from _iter_page(
            session,
            base_url,
            path,
            headers,
            config,
            logger,
            batcher,
            manager,
            base_params,
            start_page,
            start_row_offset,
        )

    elif config.pagination == "offset":
        start_offset = resume.offset if resume and resume.offset is not None else 0
        start_row_offset = resume.row_offset if resume and resume.row_offset is not None else 0
        yield from _iter_offset(
            session,
            base_url,
            path,
            headers,
            config,
            logger,
            batcher,
            manager,
            base_params,
            start_offset,
            start_row_offset,
        )

    elif config.pagination == "events_window":
        if resume and resume.window_start_ms is not None:
            start_ms = resume.window_start_ms
        else:
            last_ms = _to_epoch_ms(db_incremental_field_last_value) if should_use_incremental_field else None
            if last_ms is None and config.default_lookback_days is not None:
                last_ms = int((datetime.now(UTC) - timedelta(days=config.default_lookback_days)).timestamp() * 1000)
            start_ms = last_ms if last_ms is not None else int(datetime.now(UTC).timestamp() * 1000)
        start_row_offset = resume.row_offset if resume and resume.row_offset is not None else 0
        yield from _iter_events_windows(
            session, base_url, path, headers, config, logger, batcher, manager, start_ms, start_row_offset
        )

    elif config.pagination == "agreement_fanout":
        assert org_id is not None
        start_page = resume.parent_page if resume and resume.parent_page is not None else 0
        start_index = resume.parent_index if resume and resume.parent_index is not None else 0
        yield from _iter_agreement_fanout(
            session, base_url, org_id, path, headers, config, logger, batcher, manager, start_page, start_index
        )

    if batcher.should_yield(include_incomplete_chunk=True):
        yield batcher.get_table()


def concord_source(
    api_key: str,
    environment: str | None,
    organization_id: str | None,
    endpoint: str,
    logger: FilteringBoundLogger,
    manager: ResumableSourceManager[ConcordResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = CONCORD_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            environment=environment,
            organization_id=organization_id,
            endpoint=endpoint,
            logger=logger,
            manager=manager,
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
        # Concord's list endpoints don't guarantee an order we can pass reliably, so we walk the
        # entire (optionally server-filtered) result set every sync. The pipeline's incremental
        # watermark takes the running max, so ascending is the correct, safe declaration here.
        sort_mode="asc",
    )
