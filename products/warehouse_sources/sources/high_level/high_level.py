import re
import dataclasses
from abc import abstractmethod
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Optional

from requests import Request, Response

from products.warehouse_sources.sources.high_level.settings import (
    HIGHLEVEL_API_VERSION_V3,
    HIGHLEVEL_BASE_URL,
    HIGHLEVEL_ENDPOINTS,
    SUBMISSIONS_EARLIEST_DATE,
    HighLevelEndpointConfig,
    IncrementalFilter,
    LocationParam,
    Pagination,
)
from products.warehouse_sources.sources.sdk import (
    BasePaginator,
    Endpoint,
    EndpointResource,
    JSONResponseCursorPaginator,
    OffsetPaginator,
    PageNumberPaginator,
    PaginatorConfig,
    RESTAPIConfig,
    ResumableSourceManager,
    SinglePagePaginator,
    SourceResponse,
    make_tracked_session,
    parse_datetime_value,
    probe_status_message,
    rest_api_resource,
    set_json_param,
)

# The location id is interpolated into request paths, so only the characters HighLevel ids use
# are allowed. This keeps a crafted value from changing the path.
LOCATION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

PROBE_TIMEOUT_SECONDS = 10

# HighLevel answers 401 for a valid token that lacks the route's scope, with a message such as
# "The token is not authorized for this scope." An invalid token also gets a 401, with another message.
_MISSING_SCOPE_MARKER = "scope"


@dataclasses.dataclass(frozen=True)
class HighLevelResumeConfig:
    paginator_state: dict[str, Any]


@dataclasses.dataclass(frozen=True)
class HighLevelRequest:
    method: Literal["get", "post"]
    path: str
    params: dict[str, Any]
    json: Optional[dict[str, Any]]


def _format_timestamp(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%S.") + f"{value.microsecond // 1000:03d}Z"


def _location_params(config: HighLevelEndpointConfig, location_id: str) -> dict[str, Any]:
    if config.location_param == LocationParam.QUERY:
        return {"locationId": location_id}
    if config.location_param == LocationParam.ALT_ID:
        return {"altId": location_id, "altType": "location"}
    return {}


def _contacts_body(location_id: str, page_size: int, start: Optional[datetime]) -> dict[str, Any]:
    body: dict[str, Any] = {
        "locationId": location_id,
        "pageLimit": page_size,
        # Contacts that tie on the sort field are ordered by id, so the searchAfter walk is stable.
        "sort": [{"field": "dateUpdated" if start is not None else "dateAdded", "direction": "asc"}],
        # Skips the total count, and the response carries `hasMore` instead.
        "fastPagination": True,
    }
    if start is not None:
        body["filters"] = [{"field": "dateUpdated", "operator": "range", "value": {"gte": _format_timestamp(start)}}]
    return body


def build_request(
    config: HighLevelEndpointConfig,
    location_id: str,
    *,
    incremental_last_value: Any = None,
    page_size: Optional[int] = None,
) -> HighLevelRequest:
    if not LOCATION_ID_RE.match(location_id):
        raise ValueError("The HighLevel location ID can only contain letters, digits, hyphens and underscores.")

    size = page_size or config.page_size
    start = parse_datetime_value(incremental_last_value) if config.incremental_filter else None
    path = config.path.replace("{location_id}", location_id)

    if config.pagination == Pagination.CONTACTS_SEARCH_AFTER:
        return HighLevelRequest(method="post", path=path, params={}, json=_contacts_body(location_id, size, start))

    params: dict[str, Any] = {**_location_params(config, location_id), **config.extra_params}
    if config.pagination == Pagination.OFFSET:
        # The paginator sets these on every page. The credential probe sends them itself, because
        # endpoints such as /invoices/ reject a request without them.
        params[config.offset_param] = 0
    if config.pagination != Pagination.SINGLE:
        params["limit"] = size

    if config.incremental_filter == IncrementalFilter.START_DATE_TIMESTAMP and start is not None:
        params["startDate"] = _format_timestamp(start)
    elif config.incremental_filter == IncrementalFilter.START_AT_DAY:
        today = datetime.now(UTC).date()
        params["startAt"] = start.date().isoformat() if start is not None else SUBMISSIONS_EARLIEST_DATE
        # `endAt` is a day. Tomorrow keeps every submission made today in range.
        params["endAt"] = (today + timedelta(days=1)).isoformat()

    return HighLevelRequest(method="get", path=path, params=params, json=None)


class HighLevelKeysetPaginator(BasePaginator):
    """Base for the HighLevel endpoints whose next page starts after values taken from the last page."""

    def __init__(self, param_location: Literal["query", "json"] = "query") -> None:
        super().__init__()
        self.param_location = param_location
        self._cursor: Optional[dict[str, Any]] = None

    def _apply_cursor(self, request: Request) -> None:
        if self._cursor is None:
            return
        for name, value in self._cursor.items():
            if self.param_location == "json":
                if request.json is None:
                    request.json = {}
                set_json_param(request.json, name, value)
            else:
                if request.params is None:
                    request.params = {}
                request.params[name] = value

    def init_request(self, request: Request) -> None:
        self._apply_cursor(request)

    def update_request(self, request: Request) -> None:
        self._apply_cursor(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        rows = [row for row in data or [] if isinstance(row, dict)]
        try:
            body = response.json()
        except ValueError:
            body = None
        if not isinstance(body, dict):
            body = {}

        if not rows or not self._has_more(body):
            self._has_next_page = False
            return

        cursor = self._next_cursor(body, rows)
        if cursor is None:
            # Stopping here would drop the rest of the table without an error.
            raise ValueError("HighLevel returned a page without the values that start the next page")
        if cursor == self._cursor:
            raise ValueError(f"HighLevel pagination is not advancing: the next page cursor repeats {cursor!r}")

        self._cursor = cursor
        self._has_next_page = True

    def _has_more(self, body: dict[str, Any]) -> bool:
        # The page size is not a stop signal, because HighLevel can return fewer rows than the
        # requested limit. Without an explicit signal, the walk ends at the first empty page.
        return True

    @abstractmethod
    def _next_cursor(self, body: dict[str, Any], rows: list[dict[str, Any]]) -> Optional[dict[str, Any]]: ...

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        if self._has_next_page and self._cursor is not None:
            return {"cursor": self._cursor}
        return None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        cursor = state.get("cursor")
        if isinstance(cursor, dict) and cursor:
            self._cursor = cursor
            self._has_next_page = True


class ContactsSearchAfterPaginator(HighLevelKeysetPaginator):
    """POST /contacts/search: each contact carries the `searchAfter` array that starts the next page."""

    def __init__(self) -> None:
        super().__init__(param_location="json")

    def _has_more(self, body: dict[str, Any]) -> bool:
        has_more = body.get("hasMore")
        return has_more if isinstance(has_more, bool) else True

    def _next_cursor(self, body: dict[str, Any], rows: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
        search_after = rows[-1].get("searchAfter")
        if isinstance(search_after, list) and search_after:
            return {"searchAfter": search_after}
        return None


class OpportunitiesStartAfterPaginator(HighLevelKeysetPaginator):
    """GET /opportunities/search: `meta.startAfter` and `meta.startAfterId` start the next page."""

    def _has_more(self, body: dict[str, Any]) -> bool:
        meta = body.get("meta")
        return not (isinstance(meta, dict) and "nextPage" in meta and meta["nextPage"] is None)

    def _next_cursor(self, body: dict[str, Any], rows: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
        meta = body.get("meta")
        if not isinstance(meta, dict):
            return None
        start_after, start_after_id = meta.get("startAfter"), meta.get("startAfterId")
        if start_after is None or not start_after_id:
            return None
        return {"startAfter": start_after, "startAfterId": start_after_id}


class ConversationsStartAfterDatePaginator(HighLevelKeysetPaginator):
    """GET /conversations/search: `startAfterDate` takes the sort value of the last conversation."""

    def _next_cursor(self, body: dict[str, Any], rows: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
        last = rows[-1]
        sort_values = last.get("sort")
        value = sort_values[0] if isinstance(sort_values, list) and sort_values else last.get("lastMessageDate")
        if value is None:
            return None
        return {"startAfterDate": value}


def _paginator(config: HighLevelEndpointConfig) -> PaginatorConfig:
    if config.pagination == Pagination.SINGLE:
        return SinglePagePaginator()
    if config.pagination == Pagination.OFFSET:
        return OffsetPaginator(
            limit=config.page_size, offset_param=config.offset_param, limit_param="limit", total_path=config.total_path
        )
    if config.pagination == Pagination.PAGE:
        return PageNumberPaginator(base_page=1, page_param="page")
    if config.pagination == Pagination.CURSOR:
        return JSONResponseCursorPaginator(cursor_path="nextCursor", cursor_param="cursor")
    if config.pagination == Pagination.CONTACTS_SEARCH_AFTER:
        return ContactsSearchAfterPaginator()
    if config.pagination == Pagination.OPPORTUNITIES_START_AFTER:
        return OpportunitiesStartAfterPaginator()
    return ConversationsStartAfterDatePaginator()


def get_resource(
    config: HighLevelEndpointConfig,
    location_id: str,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any = None,
) -> EndpointResource:
    use_incremental = should_use_incremental_field and config.incremental_filter is not None
    request = build_request(
        config,
        location_id,
        incremental_last_value=db_incremental_field_last_value if use_incremental else None,
    )
    endpoint: Endpoint = {
        "path": request.path,
        "method": request.method,
        "params": request.params,
        "data_selector": config.data_selector,
        # A response without the documented wrapper key means the API shape changed, so fail
        # loudly instead of syncing zero rows.
        "data_selector_required": True,
        "data_selector_empty_ok": True,
        "paginator": _paginator(config),
    }
    if request.json is not None:
        endpoint["json"] = request.json

    return {
        "name": config.name,
        "table_name": config.name,
        "write_disposition": {"disposition": "merge", "strategy": "upsert"} if use_incremental else "replace",
        "endpoint": endpoint,
        "table_format": "delta",
    }


def high_level_source(
    token: str,
    location_id: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[HighLevelResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> SourceResponse:
    config = HIGHLEVEL_ENDPOINTS[endpoint]
    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": HIGHLEVEL_BASE_URL,
            "auth": {"type": "bearer", "token": token},
            "headers": {"Version": HIGHLEVEL_API_VERSION_V3, "Accept": "application/json"},
            # Pin every request to the HighLevel host and refuse redirects, so the bearer token
            # never goes to another host.
            "allowed_hosts": [],
            "allow_redirects": False,
        },
        "resources": [get_resource(config, location_id, should_use_incremental_field, db_incremental_field_last_value)],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = resume_config.paginator_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state:
            resumable_source_manager.save_state(HighLevelResumeConfig(paginator_state=state))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value if should_use_incremental_field else None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=config.name,
        items=lambda: resource,
        primary_keys=[config.primary_key],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def _error_message(response: Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return ""
    message = body.get("message") if isinstance(body, dict) else None
    if isinstance(message, list):
        message = " ".join(str(part) for part in message)
    return str(message or "")


def validate_credentials(token: str, location_id: str, schema_name: Optional[str] = None) -> tuple[bool, str | None]:
    if not LOCATION_ID_RE.match(location_id):
        return False, (
            "That doesn't look like a HighLevel location ID. Copy the ID from Settings > Business Profile "
            "in the sub-account, or from the sub-account URL."
        )

    config = HIGHLEVEL_ENDPOINTS.get(schema_name) if schema_name else None
    if schema_name and config is None:
        return False, f"Unknown HighLevel table: {schema_name}"

    if config is None:
        request = HighLevelRequest(method="get", path=f"/locations/{location_id}", params={}, json=None)
    else:
        request = build_request(config, location_id, page_size=1)

    try:
        session = make_tracked_session(redact_values=(token,), allow_redirects=False)
        response = session.request(
            request.method.upper(),
            f"{HIGHLEVEL_BASE_URL}{request.path}",
            params=request.params,
            json=request.json,
            headers={
                "Authorization": f"Bearer {token}",
                "Version": HIGHLEVEL_API_VERSION_V3,
                "Accept": "application/json",
            },
            timeout=PROBE_TIMEOUT_SECONDS,
        )
    except Exception:
        return False, probe_status_message("HighLevel", None) or "Couldn't reach HighLevel. Try again in a few minutes."

    status = response.status_code
    if status in (200, 201):
        return True, None

    if status == 401:
        if _MISSING_SCOPE_MARKER in _error_message(response).lower():
            # The token is genuine. At source creation the probe only checks the token, because the
            # user may not have granted the scope of the location lookup.
            if config is None:
                return True, None
            return False, (
                f"Your private integration token doesn't have the `{config.scope}` scope that the {config.name} "
                "table needs. Add the scope to the private integration in HighLevel, then try again."
            )
        return False, (
            "HighLevel rejected the private integration token. Check that you copied the whole token and that "
            "the private integration still exists."
        )

    if status in (400, 403, 404, 422):
        return False, (
            "HighLevel didn't accept the location ID for this token. Check that the location ID belongs to the "
            "sub-account where you created the private integration."
        )

    return False, probe_status_message("HighLevel", status) or f"HighLevel returned an unexpected status: {status}"
