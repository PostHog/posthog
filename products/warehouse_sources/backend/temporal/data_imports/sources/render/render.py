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
from products.warehouse_sources.backend.temporal.data_imports.sources.render.settings import (
    RENDER_ENDPOINTS,
    RenderEndpointConfig,
)

RENDER_BASE_URL = "https://api.render.com/v1"

REQUEST_TIMEOUT_SECONDS = 60

REDACTED_VALUE = "__redacted__"


class RenderRetryableError(Exception):
    pass


@dataclasses.dataclass
class RenderResumeConfig:
    # Cursor of the last processed item — passed back as `?cursor=` to fetch what follows.
    # None means "start the listing from its first page".
    cursor: str | None = None
    # The fan-out parent currently being processed. A stable parent-ID bookmark (not a
    # positional index) so parents added/removed between a crash and the retry can't resume
    # us into the wrong parent. None for top-level endpoints.
    parent_id: str | None = None


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }


def _format_incremental_value(value: Any) -> str:
    """Format a watermark as an ISO 8601 UTC timestamp, the format Render's time filters document."""
    if isinstance(value, datetime):
        utc_value = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return utc_value.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return f"{value.isoformat()}T00:00:00Z"
    return str(value)


def validate_credentials(api_key: str) -> bool:
    # /owners is the cheapest authenticated probe: every valid key can list the workspaces
    # it belongs to, regardless of what resources exist.
    url = f"{RENDER_BASE_URL}/owners?limit=1"
    try:
        response = make_tracked_session().get(url, headers=_get_headers(api_key), timeout=10)
        return response.status_code == 200
    except Exception:
        return False


@retry(
    retry=retry_if_exception_type(
        (
            RenderRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=2, max=60),
    reraise=True,
)
def _fetch_page(
    session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> list[dict[str, Any]]:
    response = session.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

    # Render rate-limits per user (400/min for most GETs) and returns 429 with
    # Ratelimit-* headers; exponential backoff comfortably outlasts the window.
    if response.status_code == 429 or response.status_code >= 500:
        raise RenderRetryableError(f"Render API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        # 404 is expected during fan-out (a service deleted mid-sync) and handled by the caller.
        log = logger.warning if response.status_code == 404 else logger.error
        log(f"Render API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    data = response.json()
    if not isinstance(data, list):
        raise ValueError(f"Render API returned a non-list response for url={url}")
    return data


def _unwrap_item(item: dict[str, Any], wrapper_key: str) -> tuple[dict[str, Any], str | None]:
    """Split a list item into (resource row, sibling cursor).

    Render list items wrap the resource next to its pagination cursor:
    `{"service": {...}, "cursor": "..."}`. A couple of endpoints (env groups) are documented
    unwrapped, so fall back to treating the item as the row itself when the key is absent.
    """
    if wrapper_key in item and isinstance(item[wrapper_key], dict):
        return item[wrapper_key], item.get("cursor")
    return item, item.get("cursor") if isinstance(item.get("cursor"), str) else None


def _build_params(
    config: RenderEndpointConfig,
    owner_id: str | None,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
    logger: FilteringBoundLogger,
) -> dict[str, Any]:
    params: dict[str, Any] = {"limit": config.page_size}

    if config.supports_owner_filter and owner_id:
        params["ownerId"] = owner_id

    if should_use_incremental_field and db_incremental_field_last_value is not None:
        field = incremental_field or config.default_incremental_field
        param = config.incremental_param_by_field.get(field) if field else None
        if param:
            params[param] = _format_incremental_value(db_incremental_field_last_value)
        else:
            logger.warning(
                f"Render: incremental field {field} has no server-side filter for endpoint "
                f"{config.name}, syncing the full endpoint instead"
            )

    return params


def _walk_pages(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    config: RenderEndpointConfig,
    path: str,
    params: dict[str, Any],
    cursor: str | None,
    max_pages: int | None = None,
) -> Iterator[tuple[list[dict[str, Any]], str | None]]:
    """Yield (rows, next_cursor) per page, following each page's last-item cursor.

    Render doesn't document an explicit end-of-results signal, so pagination only stops on an
    empty page (a short page could in principle still have more results). The next cursor is
    the cursor of the last item in the page.
    """
    pages_fetched = 0
    while True:
        page_params = dict(params)
        if cursor:
            page_params["cursor"] = cursor
        url = f"{RENDER_BASE_URL}{path}?{urlencode(page_params)}"

        items = _fetch_page(session, url, headers, logger)
        if not items:
            return

        rows: list[dict[str, Any]] = []
        next_cursor: str | None = None
        for item in items:
            row, item_cursor = _unwrap_item(item, config.wrapper_key)
            rows.append(row)
            if item_cursor:
                next_cursor = item_cursor

        yield rows, next_cursor

        if next_cursor is None:
            # Unwrapped responses carry no cursor, so a full page here may mean truncation.
            if len(items) >= config.page_size:
                logger.warning(
                    f"Render: endpoint {config.name} returned a full page with no pagination "
                    f"cursor — results may be truncated at {config.page_size} items"
                )
            return

        pages_fetched += 1
        if max_pages is not None and pages_fetched >= max_pages:
            logger.warning(
                f"Render: page cap of {max_pages} reached for endpoint {config.name} "
                f"(path={path}) — remaining results were not fetched"
            )
            return

        cursor = next_cursor


def _iter_parent_rows(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    parent_config: RenderEndpointConfig,
    owner_id: str | None,
) -> Iterator[dict[str, Any]]:
    """Fully enumerate the parent endpoint (no incremental bound: a new child can land on an
    old parent, so every sync must consider every parent)."""
    params: dict[str, Any] = {"limit": parent_config.page_size}
    if parent_config.supports_owner_filter and owner_id:
        params["ownerId"] = owner_id

    for rows, _ in _walk_pages(session, headers, logger, parent_config, parent_config.path, params, cursor=None):
        yield from rows


def _get_top_level_rows(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[RenderResumeConfig],
    config: RenderEndpointConfig,
    params: dict[str, Any],
) -> Iterator[list[dict[str, Any]]]:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    cursor = resume.cursor if resume else None
    if cursor:
        logger.debug(f"Render: resuming {config.name} from cursor={cursor}")

    for rows, next_cursor in _walk_pages(session, headers, logger, config, config.path, params, cursor):
        yield rows
        # Save AFTER yielding so a crash re-yields the last page rather than skipping it —
        # merge dedupes on the primary key.
        if next_cursor:
            resumable_source_manager.save_state(RenderResumeConfig(cursor=next_cursor))


def _get_fan_out_rows(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[RenderResumeConfig],
    config: RenderEndpointConfig,
    params: dict[str, Any],
    owner_id: str | None,
) -> Iterator[list[dict[str, Any]]]:
    """Fan out over every parent resource, fetching this child endpoint once per parent.

    Fan-out runs report sort_mode="desc" (see render_source), so the incremental watermark
    persists only after every parent completes — a partial run's max says nothing about
    parents it never reached.
    """
    assert config.parent is not None
    parent_config = RENDER_ENDPOINTS[config.parent]
    parents = [
        (row["id"], row) for row in _iter_parent_rows(session, headers, logger, parent_config, owner_id) if "id" in row
    ]

    # Resolve the saved parent-ID bookmark to the slice of parents still to process. If the
    # bookmarked parent no longer exists (deleted between runs), start over from the first
    # parent — merge dedupes the re-pulled rows on the primary key.
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    remaining = parents
    resume_cursor: str | None = None
    if resume is not None and resume.parent_id is not None:
        parent_ids = [parent_id for parent_id, _ in parents]
        if resume.parent_id in parent_ids:
            remaining = parents[parent_ids.index(resume.parent_id) :]
            resume_cursor = resume.cursor
            logger.debug(f"Render: resuming {config.name} from parent_id={resume.parent_id}, cursor={resume_cursor}")

    window_param = (
        config.incremental_param_by_field.get(config.default_incremental_field)
        if config.window_start_from_parent_field and config.default_incremental_field
        else None
    )

    for index, (parent_id, parent_row) in enumerate(remaining):
        child_params = dict(params)
        # Events default to a one-hour server-side window, so always pass an explicit lower
        # bound: the watermark when incremental, else the parent's creation time.
        if window_param and window_param not in child_params:
            window_start = parent_row.get(config.window_start_from_parent_field or "")
            if window_start:
                child_params[window_param] = window_start

        if config.parent_query_param:
            path = config.path
            child_params[config.parent_query_param] = parent_id
        else:
            path = config.path.format(parent_id=parent_id)

        cursor = resume_cursor
        resume_cursor = None  # only the resumed-into parent uses the saved cursor

        try:
            for rows, next_cursor in _walk_pages(
                session, headers, logger, config, path, child_params, cursor, max_pages=config.max_pages_per_parent
            ):
                if config.inject_parent_key:
                    rows = [{config.inject_parent_key: parent_id, **row} for row in rows]
                yield rows
                if next_cursor:
                    resumable_source_manager.save_state(RenderResumeConfig(cursor=next_cursor, parent_id=parent_id))
        except requests.HTTPError as exc:
            # A parent deleted between enumeration and this fetch 404s. Skip it rather than
            # failing the whole sync — the resource is genuinely gone.
            if exc.response is not None and exc.response.status_code == 404:
                logger.warning(f"Render: {config.parent} {parent_id} not found while fetching {config.name}, skipping")
            else:
                raise

        # Advance the bookmark to the next parent so a crash between parents resumes correctly.
        if index + 1 < len(remaining):
            resumable_source_manager.save_state(RenderResumeConfig(cursor=None, parent_id=remaining[index + 1][0]))


def _redact_row(row: dict[str, Any], redact_spec: dict[str, tuple[str, ...]]) -> dict[str, Any]:
    """Strip secret values out of a row before it reaches the warehouse.

    Render's env-group payload carries the actual env var values and secret-file contents; the
    API key is meant to *use* those for sync, not surface them as queryable columns. Replace the
    value-bearing fields with a marker while keeping the surrounding metadata (names/keys/ids).
    """
    for list_field, secret_keys in redact_spec.items():
        items = row.get(list_field)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            for key in secret_keys:
                if key in item:
                    item[key] = REDACTED_VALUE
    return row


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[RenderResumeConfig],
    owner_id: str | None = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[list[dict[str, Any]]]:
    config = RENDER_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)
    # One session reused across every page (and, for fan-out, every parent) so urllib3 keeps
    # the connection alive instead of re-handshaking per request. Sensitive endpoints opt out of
    # HTTP sample capture — capture snapshots the raw response before row-level redaction runs.
    session = make_tracked_session(capture=not config.is_sensitive)

    params = _build_params(
        config, owner_id, should_use_incremental_field, db_incremental_field_last_value, incremental_field, logger
    )

    if config.parent:
        batches = _get_fan_out_rows(session, headers, logger, resumable_source_manager, config, params, owner_id)
    else:
        batches = _get_top_level_rows(session, headers, logger, resumable_source_manager, config, params)

    if config.redact_list_item_fields:
        for batch in batches:
            yield [_redact_row(row, config.redact_list_item_fields) for row in batch]
    else:
        yield from batches


def render_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[RenderResumeConfig],
    owner_id: str | None = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    endpoint_config = RENDER_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            owner_id=owner_id,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        ),
        primary_keys=endpoint_config.primary_keys,
        # Render doesn't document list ordering and cursor pagination accepts no sort param, so
        # the watermark is only safe to persist once the run completes (desc mode computes the
        # max across all batches and saves it at successful job end).
        sort_mode="desc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )
