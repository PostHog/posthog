import base64
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional

from dateutil import parser
from requests import Response, Session
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.sources.close.search import (
    fetch_custom_field_selectors,
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
# Far-past cutoff used on the first incremental sync (no stored watermark yet) so we
# pull the full history before the cursor takes over on subsequent runs.
INITIAL_INCREMENTAL_VALUE = "1970-01-01T00:00:00+00:00"


# The shared DEFAULT_RETRY only allows GET/HEAD/OPTIONS, so a transient failure on the
# Advanced Filtering POST would not be retried. The search call is a read-only query, so it is
# safe to retry alongside everything else. Derived via `.new()` so the policy stays a
# BoundedRetry (Retry-After clamping) and every other knob tracks DEFAULT_RETRY.
CLOSE_RETRY = DEFAULT_RETRY.new(allowed_methods=frozenset(DEFAULT_RETRY.allowed_methods or ()) | {"POST"})


@dataclasses.dataclass
class CloseResumeConfig:
    next_skip: int = 0
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


def get_resource(
    endpoint: str,
    should_use_incremental_field: bool,
    incremental_field: Optional[str],
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

    endpoint_def: Endpoint = {
        "data_selector": config.data_selector,
        "path": config.path,
        "params": params,
    }
    # Dimension endpoints that take no `_skip`/`_limit` get a single-page paginator so we don't
    # inject pagination params the API doesn't accept; everything else uses the client default.
    if not config.paginated:
        endpoint_def["paginator"] = SinglePagePaginator()

    return {
        "name": config.name,
        "table_name": config.table_name,
        "primary_key": config.primary_keys,
        "write_disposition": {"disposition": "merge", "strategy": "upsert"} if is_incremental else "replace",
        "endpoint": endpoint_def,
        "table_format": "delta",
    }


def _make_search_session(api_key: str) -> Session:
    basic_token = base64.b64encode(f"{api_key}:".encode("ascii")).decode("ascii")
    return make_tracked_session(
        retry=CLOSE_RETRY,
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
        session = _make_search_session(api_key)
        fields = [*config.search_fields, *fetch_custom_field_selectors(session, CLOSE_BASE_URL, object_type, logger)]
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
    if CLOSE_ENDPOINTS[endpoint].search_object_type is not None:
        return close_search_source(
            api_key=api_key,
            endpoint=endpoint,
            resumable_source_manager=resumable_source_manager,
            logger=logger,
            db_incremental_field_last_value=db_incremental_field_last_value,
            should_use_incremental_field=should_use_incremental_field,
            incremental_field=incremental_field,
        )

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
        "resources": [get_resource(endpoint, should_use_incremental_field, incremental_field)],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = {"skip": resume_config.next_skip}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when there's a next page to resume to. Redis TTL handles cleanup on completion.
        if state and state.get("skip") is not None:
            resumable_source_manager.save_state(CloseResumeConfig(next_skip=int(state["skip"])))

    resource = rest_api_resource(
        config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    endpoint_config = CLOSE_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=endpoint_config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
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
