import base64
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional

from dateutil import parser
from requests import Request, Response, Session
from structlog.types import FilteringBoundLogger
from urllib3.util.retry import Retry

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.close.search import (
    ALL_CUSTOM_FIELDS_SELECTOR,
    iter_search_rows,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.close.settings import (
    CLOSE_ENDPOINTS,
    CloseEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import (
    DEFAULT_RETRY,
    make_tracked_session,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    OffsetPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

CLOSE_BASE_URL = "https://api.close.com/api/v1"
PAGE_LIMIT = 100
# Close caps the event log's `_limit` at 50 and defaults to it.
EVENT_PAGE_LIMIT = 50
REQUEST_TIMEOUT_SECONDS = 30
# Far-past cutoff used on the first incremental sync (no stored watermark yet) so we
# pull the full history before the cursor takes over on subsequent runs.
INITIAL_INCREMENTAL_VALUE = "1970-01-01T00:00:00+00:00"


# The shared DEFAULT_RETRY only allows GET/HEAD/OPTIONS, so a transient failure on the
# Advanced Filtering POST would not be retried. The search call is a read-only query, so it is
# safe to retry alongside everything else. Derived via `.new()` so the policy stays a
# BoundedRetry (Retry-After clamping) and every other knob tracks DEFAULT_RETRY.
CLOSE_RETRY = DEFAULT_RETRY.new(allowed_methods=frozenset(DEFAULT_RETRY.allowed_methods or ()) | {"POST"})


@frozen
class CloseResumeConfig:
    next_skip: int = 0
    # Event log walk: the `cursor_next` the next page starts from.
    next_cursor: Optional[str] = None
    # Advanced Filtering walk (Leads/Contacts): the last cursor-field value already emitted.
    search_anchor: Optional[str] = None
    search_cursor_field: Optional[str] = None


def _format_close_datetime(value: Any) -> str:
    """Format an incremental cursor value as the ISO 8601 string Close expects for `<field>__gte`."""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime.combine(value, datetime.min.time())
    else:
        try:
            dt = parser.parse(str(value))
        except (ValueError, OverflowError):
            return str(value)

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat()


def _parse_close_datetime(value: Any) -> Optional[datetime]:
    """Parse a Close timestamp into a UTC-aware datetime, or None when it isn't one."""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str) and value:
        try:
            dt = parser.parse(value)
        except (ValueError, OverflowError):
            return None
    else:
        return None
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


class CloseOffsetPaginator(OffsetPaginator):
    """Offset paginator driven by Close's `has_more` response flag.

    Close list endpoints page with `_skip`/`_limit` and return `{"data": [...], "has_more": bool}`.
    Small dimension endpoints omit `has_more`; treating a missing flag as `False` stops after the
    single page they return.
    """

    def __init__(self, limit: int = PAGE_LIMIT, offset: int = 0) -> None:
        super().__init__(
            limit=limit,
            offset=offset,
            offset_param="_skip",
            limit_param="_limit",
            total_path=None,
            stop_after_empty_page=True,
        )

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        if data is None or len(data) == 0:
            self._has_next_page = False
            return

        try:
            body = response.json()
            has_more = bool(body.get("has_more")) if isinstance(body, dict) else False
        except (ValueError, AttributeError):
            has_more = False

        if not has_more:
            self._has_next_page = False
            return

        self.offset += self.limit
        self._has_next_page = True

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        if self._has_next_page:
            return {"skip": self.offset}
        return None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        skip = state.get("skip")
        if skip is not None:
            self.offset = int(skip)
            self._has_next_page = True


class CloseEventCursorPaginator(BasePaginator):
    """Cursor paginator for Close's event log.

    `/event/` rejects `_skip`: it pages with `_cursor` and hands back the next cursor as
    `cursor_next`. Close documents that a cursor request must re-send every other filter
    *except* `date_updated`, so an incremental window only bounds the first request and later
    pages walk back through history unbounded. Events arrive newest-first, so once a whole page
    predates the watermark everything behind it has already been synced and we stop.
    """

    def __init__(self, stop_when_older_than: Optional[datetime] = None) -> None:
        super().__init__()
        self._cursor: Optional[str] = None
        self._stop_when_older_than = stop_when_older_than

    def init_request(self, request: Request) -> None:
        # Only set when resuming a part-walked run; a fresh run starts at the newest event.
        if self._cursor is not None:
            self._apply_cursor(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        if not data:
            self._cursor = None
            self._has_next_page = False
            return

        try:
            body = response.json()
        except ValueError:
            body = None
        cursor = body.get("cursor_next") if isinstance(body, dict) else None
        next_cursor = cursor if isinstance(cursor, str) and cursor else None
        if next_cursor is not None and next_cursor == self._cursor:
            # Following it again would re-request the same page for as long as the activity runs.
            raise ValueError("Close returned the same event cursor twice")
        self._cursor = next_cursor
        self._has_next_page = self._cursor is not None

        if self._has_next_page and self._stop_when_older_than is not None:
            timestamps = [
                parsed
                for parsed in (_parse_close_datetime(row.get("date_updated")) for row in data if isinstance(row, dict))
                if parsed is not None
            ]
            if len(timestamps) == len(data) and max(timestamps) < self._stop_when_older_than:
                self._has_next_page = False

    def update_request(self, request: Request) -> None:
        if self._cursor is not None:
            self._apply_cursor(request)

    def _apply_cursor(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params.pop("date_updated__gte", None)
        request.params["_cursor"] = self._cursor

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        if self._has_next_page and self._cursor is not None:
            return {"cursor": self._cursor}
        return None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        cursor = state.get("cursor")
        if cursor:
            self._cursor = str(cursor)
            self._has_next_page = True


def get_resource(
    endpoint: str,
    should_use_incremental_field: bool,
    incremental_field: Optional[str],
    db_incremental_field_last_value: Optional[Any] = None,
) -> EndpointResource:
    config: CloseEndpointConfig = CLOSE_ENDPOINTS[endpoint]

    is_incremental = should_use_incremental_field and bool(config.incremental_fields)

    params: dict[str, Any] = {}
    if is_incremental:
        # Honor the user's chosen cursor field; fall back to the first advertised option.
        advertised = {f["field"] for f in config.incremental_fields}
        cursor = incremental_field if incremental_field in advertised else config.incremental_fields[0]["field"]
        params[f"{cursor}__gte"] = {
            "type": "incremental",
            "cursor_path": cursor,
            "initial_value": INITIAL_INCREMENTAL_VALUE,
            "convert": _format_close_datetime,
        }
        if config.supports_order_by:
            # Ascending sort on the cursor so the pipeline watermark advances correctly
            # (matches SourceResponse.sort_mode="asc").
            params["_order_by"] = cursor

    paginator: Optional[BasePaginator] = None
    # Dimension endpoints that take no `_skip`/`_limit` get a single-page paginator so we don't
    # inject pagination params the API doesn't accept; offset endpoints use the client default.
    if config.pagination == "single_page":
        paginator = SinglePagePaginator()
    elif config.pagination == "event_cursor":
        params["_limit"] = EVENT_PAGE_LIMIT
        paginator = CloseEventCursorPaginator(
            stop_when_older_than=_parse_close_datetime(db_incremental_field_last_value) if is_incremental else None
        )

    endpoint_def: Endpoint = {
        "data_selector": config.data_selector,
        "path": config.path,
        "params": params,
    }
    if paginator is not None:
        endpoint_def["paginator"] = paginator

    return {
        "name": config.name,
        "table_name": config.table_name,
        "primary_key": config.primary_keys,
        "write_disposition": {"disposition": "merge", "strategy": "upsert"} if is_incremental else "replace",
        "endpoint": endpoint_def,
        "table_format": "delta",
    }


def _make_session(api_key: str, retry: Optional[Retry] = None) -> Session:
    basic_token = base64.b64encode(f"{api_key}:".encode("ascii")).decode("ascii")
    return make_tracked_session(
        retry=retry,
        headers={"Authorization": f"Basic {basic_token}"},
        redact_values=(api_key, basic_token),
    )


def _search_cursor_field(config: CloseEndpointConfig, is_incremental: bool, incremental_field: Optional[str]) -> str:
    if not is_incremental:
        # Full refresh walks creation order, which never reorders under us.
        return "date_created"
    advertised = {f["field"] for f in config.incremental_fields}
    return incremental_field if incremental_field in advertised else config.incremental_fields[0]["field"]


def close_search_source(
    api_key: str,
    endpoint: str,
    resumable_source_manager: ResumableSourceManager[CloseResumeConfig],
    logger: FilteringBoundLogger,
    db_incremental_field_last_value: Optional[Any] = None,
    should_use_incremental_field: bool = False,
    incremental_field: Optional[str] = None,
) -> SourceResponse:
    """Read Leads or Contacts through Close's Advanced Filtering API.

    Their list endpoints take no date filter, so offset pagination is the only option there and
    Close's `_skip` cap silently truncates large tables. See search.py for the paging strategy.
    """
    config = CLOSE_ENDPOINTS[endpoint]
    object_type = config.search_object_type
    if object_type is None:
        raise ValueError(f"Close endpoint {endpoint} is not backed by the search API")

    is_incremental = should_use_incremental_field and bool(config.incremental_fields)
    cursor_field = _search_cursor_field(config, is_incremental, incremental_field)

    start_anchor: Optional[str] = None
    if is_incremental and db_incremental_field_last_value is not None:
        start_anchor = _format_close_datetime(db_incremental_field_last_value)

    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        # Only resume a walk that used the same cursor field; otherwise the anchor is meaningless.
        if resume_config is not None and resume_config.search_cursor_field == cursor_field:
            start_anchor = resume_config.search_anchor or start_anchor

    def save_checkpoint(anchor: str) -> None:
        resumable_source_manager.save_state(CloseResumeConfig(search_anchor=anchor, search_cursor_field=cursor_field))

    def items() -> Iterator[list[dict[str, Any]]]:
        session = _make_session(api_key, retry=CLOSE_RETRY)
        # One `custom` selector pulls every custom field, so the field list stays bounded no
        # matter how many an org has. See ALL_CUSTOM_FIELDS_SELECTOR.
        fields = [*config.search_fields, ALL_CUSTOM_FIELDS_SELECTOR]
        yield from iter_search_rows(
            session=session,
            base_url=CLOSE_BASE_URL,
            object_type=object_type,
            fields=fields,
            cursor_field=cursor_field,
            start_anchor=start_anchor,
            logger=logger,
            on_checkpoint=save_checkpoint,
        )

    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode="asc",
    )


def _organization_ids(me: dict[str, Any]) -> list[str]:
    """Collect the organization ids this API key can read, in the order Close lists them."""
    ids = [
        organization["id"]
        for organization in me.get("organizations") or []
        if isinstance(organization, dict) and organization.get("id")
    ]
    ids += [
        membership["organization_id"]
        for membership in me.get("memberships") or []
        if isinstance(membership, dict) and membership.get("organization_id")
    ]
    return list(dict.fromkeys(ids))


def close_organizations_source(api_key: str, endpoint: str) -> SourceResponse:
    """Read every organization the API key belongs to.

    Close publishes no `/organization/` list endpoint, so `/me/` supplies the ids and each
    organization is fetched on its own.
    """
    config = CLOSE_ENDPOINTS[endpoint]

    def items() -> Iterator[list[dict[str, Any]]]:
        session = _make_session(api_key)
        me_response = session.get(f"{CLOSE_BASE_URL}/me/", timeout=REQUEST_TIMEOUT_SECONDS)
        me_response.raise_for_status()
        me = me_response.json()

        rows: list[dict[str, Any]] = []
        for organization_id in _organization_ids(me if isinstance(me, dict) else {}):
            response = session.get(f"{CLOSE_BASE_URL}/organization/{organization_id}/", timeout=REQUEST_TIMEOUT_SECONDS)
            response.raise_for_status()
            organization = response.json()
            if isinstance(organization, dict):
                rows.append(organization)

        if rows:
            yield rows

    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
    )


def close_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[CloseResumeConfig],
    db_incremental_field_last_value: Optional[Any],
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool = False,
    incremental_field: Optional[str] = None,
) -> SourceResponse:
    endpoint_config = CLOSE_ENDPOINTS[endpoint]

    if endpoint_config.search_object_type is not None:
        return close_search_source(
            api_key=api_key,
            endpoint=endpoint,
            resumable_source_manager=resumable_source_manager,
            logger=logger,
            db_incremental_field_last_value=db_incremental_field_last_value,
            should_use_incremental_field=should_use_incremental_field,
            incremental_field=incremental_field,
        )

    if endpoint_config.fan_out_from_me:
        return close_organizations_source(api_key=api_key, endpoint=endpoint)

    config: RESTAPIConfig = {
        "client": {
            "base_url": CLOSE_BASE_URL,
            "auth": {
                "type": "http_basic",
                "username": api_key,
                "password": "",
            },
            "paginator": CloseOffsetPaginator(),
        },
        # Write disposition is set per-resource in get_resource (it always wins over
        # resource_defaults), so no default is needed here.
        "resource_defaults": {},
        "resources": [
            get_resource(endpoint, should_use_incremental_field, incremental_field, db_incremental_field_last_value)
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            if endpoint_config.pagination == "event_cursor":
                if resume_config.next_cursor is not None:
                    initial_paginator_state = {"cursor": resume_config.next_cursor}
            else:
                initial_paginator_state = {"skip": resume_config.next_skip}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when there's a next page to resume to. Redis TTL handles cleanup on completion.
        if not state:
            return
        if state.get("cursor") is not None:
            resumable_source_manager.save_state(CloseResumeConfig(next_cursor=str(state["cursor"])))
        elif state.get("skip") is not None:
            resumable_source_manager.save_state(CloseResumeConfig(next_skip=int(state["skip"])))

    resource = rest_api_resource(
        config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=endpoint_config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
        sort_mode=endpoint_config.sort_mode,
    )


def validate_credentials(api_key: str) -> bool:
    basic_token = base64.b64encode(f"{api_key}:".encode("ascii")).decode("ascii")
    try:
        response = make_tracked_session().get(
            f"{CLOSE_BASE_URL}/me/",
            headers={"Authorization": f"Basic {basic_token}"},
            timeout=30,
        )
    except Exception:
        return False
    return response.status_code == 200
