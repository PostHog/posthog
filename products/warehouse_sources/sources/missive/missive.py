from collections.abc import Callable, Iterator
from dataclasses import field
from datetime import UTC, datetime
from typing import Any

import requests
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.sources.missive.settings import (
    MISSIVE_ENDPOINTS,
    MissiveEndpointConfig,
    Pagination,
    Parent,
)
from products.warehouse_sources.sources.sdk import (
    ResumableSourceManager,
    SourceResponse,
    frozen,
    make_tracked_session,
    request_deadline,
)

BASE_URL = "https://public.missiveapp.com/v1"
REQUEST_TIMEOUT_SECONDS = (10, 60)


@frozen
class MissiveResumeConfig:
    # Position of the next page of the top-level list. For a fan-out table that is the parent list.
    until: int | None = None
    # Ids of the rows at `until` that an earlier page already returned. `until` is inclusive.
    seen_ids: list[str] = field(default_factory=list)
    offset: int = 0
    variant: int = 0
    # Fan-out only: parents of the current parent page that are read in full.
    done_parent_ids: list[str] = field(default_factory=list)
    # Fan-out only: the parent being read, and the position of its next child page.
    child_parent_id: str | None = None
    child_variant: int = 0
    child_until: int | None = None
    child_seen_ids: list[str] = field(default_factory=list)
    child_offset: int = 0
    # Every page is read. A resume reads nothing more.
    finished: bool = False


@frozen
class PagePosition:
    variant: int = 0
    until: int | None = None
    seen_ids: tuple[str, ...] = ()
    offset: int = 0


# Sends one GET for a path and its query params, and returns the decoded body. A None body has no rows.
FetchPage = Callable[[str, dict[str, Any]], Any]


def _headers(api_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_token}", "Accept": "application/json"}


def _make_fetch(api_token: str) -> FetchPage:
    session = make_tracked_session(headers=_headers(api_token), redact_values=(api_token,))

    def fetch(path: str, params: dict[str, Any]) -> Any:
        with request_deadline():
            response = session.get(f"{BASE_URL}{path}", params=params, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        return response.json()

    return fetch


def validate_credentials(api_token: str) -> tuple[bool, str | None]:
    session = make_tracked_session(headers=_headers(api_token), redact_values=(api_token,))
    try:
        with request_deadline():
            response = session.get(f"{BASE_URL}/organizations", params={"limit": 1}, timeout=REQUEST_TIMEOUT_SECONDS)
    except requests.RequestException as error:
        return False, f"Couldn't connect to Missive: {error}. Try again in a few minutes."

    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return False, "Missive rejected the API token. Create a new token in Missive and try again."
    if response.status_code == 403:
        return (
            False,
            "Missive refused the API token. Check that your organization is on the Missive Productive plan, which includes API access.",
        )
    return False, f"Missive returned an unexpected status: {response.status_code}. Try again in a few minutes."


def to_unix_seconds(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        return int((value if value.tzinfo else value.replace(tzinfo=UTC)).timestamp())
    if isinstance(value, int | float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(float(value))
        except ValueError:
            try:
                return to_unix_seconds(datetime.fromisoformat(value))
            except ValueError:
                return None
    return None


def _timestamp(row: dict[str, Any], cursor_field: str) -> int | None:
    value = row.get(cursor_field)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _next_until_position(
    config: MissiveEndpointConfig, raw_rows: list[dict[str, Any]], variant_index: int, watermark: int | None
) -> PagePosition | None:
    """The position after one newest-first page, or None when the page is the last one."""
    assert config.cursor_field is not None
    cursor_field = config.cursor_field
    stamps = [stamp for row in raw_rows if (stamp := _timestamp(row, cursor_field)) is not None]
    if not stamps or len(raw_rows) < config.page_size:
        return None
    oldest = min(stamps)
    if watermark is not None and oldest < watermark:
        return None
    if oldest == max(stamps):
        if not config.same_timestamp_page_continues:
            return None
        return PagePosition(variant=variant_index, until=oldest - 1)
    return PagePosition(
        variant=variant_index,
        until=oldest,
        seen_ids=tuple(
            str(row["id"]) for row in raw_rows if _timestamp(row, cursor_field) == oldest and row.get("id") is not None
        ),
    )


def _pages(
    config: MissiveEndpointConfig,
    fetch_rows: Callable[[dict[str, Any]], Any],
    start: PagePosition,
    base_params: dict[str, Any],
    watermark: int | None,
) -> Iterator[tuple[list[dict[str, Any]], PagePosition | None]]:
    """Walk every page of one list, in order, from `start`.

    Each item is the rows of one page and the position of the next page, or None after the last page.
    `watermark` stops a newest-first walk after the first page that reaches back before it.
    """
    position = start
    for variant_index in range(start.variant, len(config.param_variants)):
        variant_params = config.param_variants[variant_index]
        while True:
            params: dict[str, Any] = {**base_params, **variant_params, "limit": config.page_size}
            if config.pagination is Pagination.OFFSET:
                params["offset"] = position.offset
            elif position.until is not None:
                params["until"] = position.until

            body = fetch_rows(params)
            raw = body.get(config.data_key) if isinstance(body, dict) else None
            raw_rows = [row for row in raw or [] if isinstance(row, dict)]

            if config.variant_columns:
                raw_rows = [{**row, **variant_params} for row in raw_rows]
            if config.nullable_columns:
                raw_rows = [{**dict.fromkeys(config.nullable_columns), **row} for row in raw_rows]

            next_position: PagePosition | None
            if config.pagination is Pagination.OFFSET:
                rows = raw_rows
                next_position = (
                    PagePosition(variant=variant_index, offset=position.offset + len(raw_rows))
                    if len(raw_rows) >= config.page_size
                    else None
                )
            else:
                seen = set(position.seen_ids)
                rows = [row for row in raw_rows if row.get("id") not in seen]
                next_position = _next_until_position(config, raw_rows, variant_index, watermark)

            if next_position is None and variant_index + 1 < len(config.param_variants):
                next_position = PagePosition(variant=variant_index + 1)
                yield rows, next_position
                position = next_position
                break

            yield rows, next_position
            if next_position is None:
                return
            position = next_position


# Each step of a walk is the rows of one page and the resume state that covers them.
Steps = Iterator[tuple[list[dict[str, Any]], MissiveResumeConfig]]


def _top_level_steps(
    config: MissiveEndpointConfig,
    fetch: FetchPage,
    resume: MissiveResumeConfig | None,
    watermark: int | None,
) -> Steps:
    start = PagePosition(
        until=resume.until if resume else None,
        seen_ids=tuple(resume.seen_ids) if resume else (),
        offset=resume.offset if resume else 0,
        variant=resume.variant if resume else 0,
    )
    for rows, next_position in _pages(config, lambda params: fetch(config.path, params), start, {}, watermark):
        if next_position is None:
            yield rows, MissiveResumeConfig(finished=True)
        else:
            yield (
                rows,
                MissiveResumeConfig(
                    until=next_position.until,
                    seen_ids=list(next_position.seen_ids),
                    offset=next_position.offset,
                    variant=next_position.variant,
                ),
            )


def _child_params(config: MissiveEndpointConfig, parent_id: str, watermark: int | None) -> dict[str, Any]:
    if config.parent is Parent.CONTACT_BOOKS:
        params: dict[str, Any] = {"contact_book": parent_id}
        if config.name == "contacts" and watermark is not None:
            # Missive filters contacts on their modification time and, on request, includes deleted ones.
            params["modified_since"] = watermark
            params["include_deleted"] = "true"
        return params
    return {}


def _fan_out_steps(
    config: MissiveEndpointConfig,
    parent_fetch: FetchPage,
    child_fetch: FetchPage,
    resume: MissiveResumeConfig | None,
    watermark: int | None,
) -> Steps:
    assert config.parent is not None and config.parent_id_column is not None
    parent_id_column = config.parent_id_column
    parent_config = MISSIVE_ENDPOINTS[config.parent.value]
    # Activity on an entry moves its conversation's `last_activity_at`. So a conversation whose last
    # activity predates the watermark has no newer entries, and an incremental run stops there.
    parent_watermark = watermark if config.parent is Parent.CONVERSATIONS else None
    child_watermark = watermark if config.pagination is Pagination.UNTIL else None

    page_start = PagePosition(
        variant=resume.variant if resume else 0,
        until=resume.until if resume else None,
        seen_ids=tuple(resume.seen_ids) if resume else (),
        offset=resume.offset if resume else 0,
    )
    done_parent_ids = list(resume.done_parent_ids) if resume else []

    def state(**child: Any) -> MissiveResumeConfig:
        return MissiveResumeConfig(
            until=page_start.until,
            seen_ids=list(page_start.seen_ids),
            offset=page_start.offset,
            variant=page_start.variant,
            done_parent_ids=list(done_parent_ids),
            **child,
        )

    def child_steps(parent_id: str, child_start: PagePosition) -> Steps:
        child_path = config.path.replace("{id}", parent_id)

        def fetch_child_page(params: dict[str, Any]) -> Any:
            return child_fetch(child_path, params)

        child_pages = _pages(
            config, fetch_child_page, child_start, _child_params(config, parent_id, watermark), child_watermark
        )
        for rows, next_child in child_pages:
            tagged = [{**row, parent_id_column: parent_id} for row in rows]
            if next_child is None:
                done_parent_ids.append(parent_id)
                yield tagged, state()
            else:
                yield (
                    tagged,
                    state(
                        child_parent_id=parent_id,
                        child_variant=next_child.variant,
                        child_until=next_child.until,
                        child_seen_ids=list(next_child.seen_ids),
                        child_offset=next_child.offset,
                    ),
                )

    # New activity can move the parent that was being read above the saved `until`, and the parent
    # list then no longer returns it. So the run finishes that parent by id before it lists parents.
    if resume is not None and resume.child_parent_id is not None:
        resumed_start = PagePosition(
            variant=resume.child_variant,
            until=resume.child_until,
            seen_ids=tuple(resume.child_seen_ids),
            offset=resume.child_offset,
        )
        yield from child_steps(resume.child_parent_id, resumed_start)

    def fetch_parent_page(params: dict[str, Any]) -> Any:
        return parent_fetch(parent_config.path, params)

    for parents, next_page in _pages(parent_config, fetch_parent_page, page_start, {}, parent_watermark):
        for parent in parents:
            parent_id = parent.get("id")
            if not isinstance(parent_id, str) or parent_id in done_parent_ids:
                continue
            last_activity = _timestamp(parent, "last_activity_at")
            if parent_watermark is not None and last_activity is not None and last_activity < parent_watermark:
                continue
            yield from child_steps(parent_id, PagePosition())

        if next_page is None:
            yield [], MissiveResumeConfig(finished=True)
        else:
            page_start = next_page
            done_parent_ids.clear()
            yield [], state()


def _skip_missing_parent(fetch: FetchPage, logger: FilteringBoundLogger) -> FetchPage:
    """Read a deleted, merged or hidden parent as one with no children, rather than failing the sync."""

    def fetch_children(path: str, params: dict[str, Any]) -> Any:
        try:
            return fetch(path, params)
        except requests.HTTPError as error:
            status = error.response.status_code if error.response is not None else None
            if status in (403, 404):
                logger.debug(f"Missive: skipping {path} after status {status}")
                return None
            raise

    return fetch_children


def get_rows(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[MissiveResumeConfig],
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = MISSIVE_ENDPOINTS[endpoint]
    fetch = _make_fetch(api_token)
    watermark = to_unix_seconds(db_incremental_field_last_value)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.finished:
        return

    steps = (
        _top_level_steps(config, fetch, resume, watermark)
        if config.parent is None
        else _fan_out_steps(config, fetch, _skip_missing_parent(fetch, logger), resume, watermark)
    )
    for rows, state in steps:
        # Stage the state before its rows, so the pipeline commits them together.
        resumable_source_manager.save_state(state)
        if rows:
            yield rows
        else:
            resumable_source_manager.safe_point()


def missive_source(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[MissiveResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> SourceResponse:
    config = MISSIVE_ENDPOINTS[endpoint]
    incremental = should_use_incremental_field and bool(config.incremental_fields)
    partitioned = config.partition_key is not None

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_token=api_token,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            db_incremental_field_last_value=db_incremental_field_last_value if incremental else None,
        ),
        primary_keys=list(config.primary_keys),
        partition_count=1 if partitioned else None,
        partition_size=1 if partitioned else None,
        partition_mode="datetime" if partitioned else None,
        partition_format="month" if partitioned else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # A top-level `until` list is one newest-first series. Fan-out children are ordered per parent only.
        sort_mode="desc" if incremental and config.pagination is Pagination.UNTIL and config.parent is None else None,
    )
