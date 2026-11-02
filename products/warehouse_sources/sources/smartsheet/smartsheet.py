from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any, Optional, cast

from requests import Request, Response

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.datetime_utils import parse_datetime_value
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    JSONResponseCursorPaginator,
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ClientConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.smartsheet.settings import (
    SMARTSHEET_ENDPOINTS,
    Pagination,
    SmartsheetEndpointConfig,
)

SMARTSHEET_BASE_URL = "https://api.smartsheet.com/2.0"

# List Events needs a `since` (or a stream position). A full refresh asks from a date before any
# retained event, so it reads the whole retained stream.
EVENTS_FULL_REFRESH_SINCE = "2000-01-01T00:00:00Z"
# Smartsheet resolves `since` to the nearest hour, which can round it past the watermark. Moving
# the watermark back one hour first means no event is skipped; the merge on eventId drops the overlap.
EVENTS_SINCE_OVERLAP = timedelta(hours=1)


@frozen
class SmartsheetResumeConfig:
    # 1-based number of the next unfetched page — Smartsheet list endpoints page with `page`.
    next_page: Optional[int] = None
    # `nextStreamPosition` of the events stream, which pages by position instead of by page number.
    stream_position: Optional[str] = None


class SheetRowsPaginator(PageNumberPaginator):
    """Page the rows of Get Sheet.

    The response reports `totalRowCount` but no page count, and a page past the end returns the
    last page again rather than an empty one, so the walk stops on the row count.
    """

    def __init__(self, page_size: int) -> None:
        super().__init__(base_page=1, page_param="page")
        self.page_size = page_size

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        if not self._has_next_page:
            return
        total_rows = response.json().get("totalRowCount")
        # `self.page` already points at the next page, so the earlier pages hold every row before it.
        rows_fetched = (self.page - 1) * self.page_size
        if len(data or []) < self.page_size or not isinstance(total_rows, int) or rows_fetched >= total_rows:
            self._has_next_page = False


class EventStreamPaginator(JSONResponseCursorPaginator):
    """Follow the List Events stream.

    Every response carries a `nextStreamPosition`, so `moreAvailable` is the only end signal. The
    API takes exactly one of `since` and `streamPosition`, so a request with a position drops `since`.
    """

    def __init__(self) -> None:
        super().__init__(cursor_path="nextStreamPosition", cursor_param="streamPosition")

    def init_request(self, request: Request) -> None:
        super().init_request(request)
        self._drop_since(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        if response.json().get("moreAvailable") is not True:
            self._has_next_page = False

    def update_request(self, request: Request) -> None:
        super().update_request(request)
        self._drop_since(request)

    def _drop_since(self, request: Request) -> None:
        if self._cursor_value is not None and request.params:
            request.params.pop("since", None)


def _paginator(pagination: Pagination, page_size: int) -> BasePaginator:
    if pagination == "token":
        return JSONResponseCursorPaginator(cursor_path="lastKey", cursor_param="lastKey")
    if pagination == "single_page":
        return SinglePagePaginator()
    if pagination == "sheet_rows":
        return SheetRowsPaginator(page_size)
    if pagination == "event_stream":
        return EventStreamPaginator()
    return PageNumberPaginator(base_page=1, page_param="page", total_path="totalPages")


def _incremental_start(
    should_use_incremental_field: bool, db_incremental_field_last_value: Optional[Any]
) -> Optional[datetime]:
    if not should_use_incremental_field:
        return None
    return parse_datetime_value(db_incremental_field_last_value)


def _iso(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def _non_secret_headers() -> dict[str, str]:
    # Auth (Bearer) is supplied via the framework auth config so its value is redacted from raised
    # errors; only the non-secret Accept header is set here.
    return {"Accept": "application/json"}


def _client_config(access_token: str) -> ClientConfig:
    return {
        "base_url": SMARTSHEET_BASE_URL,
        "headers": _non_secret_headers(),
        "auth": {"type": "bearer", "token": access_token},
    }


def _primary_keys(config: SmartsheetEndpointConfig) -> list[str]:
    return config.primary_key if isinstance(config.primary_key, list) else [config.primary_key]


def _fanout_source(
    access_token: str,
    endpoint: str,
    config: SmartsheetEndpointConfig,
    team_id: int,
    job_id: str,
    incremental_start: Optional[datetime],
) -> SourceResponse:
    """Fan out from each parent (report, sheet or group) to its child endpoint.

    The parent walks its list page-by-page; each child request resolves a parent id into its path
    and pages the way its `pagination` names. Resume is not wired for fan-out.
    """
    assert config.fanout is not None
    pagination = config.pagination
    child_params_extra: Optional[dict[str, Any]] = None
    if pagination == "sheet_rows" and incremental_start is not None:
        # Get Sheet documents `totalRowCount` only for the whole sheet, not for the rows that
        # `rowsModifiedSince` keeps, so a filtered read takes its rows in one unpaged request.
        pagination = "single_page"
        child_params_extra = {"rowsModifiedSince": _iso(incremental_start)}
    elif pagination in ("sheet_rows", "page_number"):
        child_params_extra = {"pageSize": config.page_size}
    dependent_resource = cast(
        Iterable[Any],
        build_dependent_resource(
            endpoint_configs=SMARTSHEET_ENDPOINTS,
            child_endpoint=endpoint,
            fanout=config.fanout,
            client_config=_client_config(access_token),
            path_format_values={},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=None,
            # Parent uses `pageSize`, child uses `maxItems`; both are supplied through the fan-out
            # config's parent_params / child_params rather than a shared page-size param.
            page_size_param=None,
            parent_endpoint_extra={
                "paginator": PageNumberPaginator(base_page=1, page_param="page", total_path="totalPages"),
                "data_selector": "data",
            },
            child_endpoint_extra={
                "paginator": _paginator(pagination, config.page_size),
                "data_selector": config.data_selector,
            },
            child_params_extra=child_params_extra,
        ),
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: dependent_resource,
        primary_keys=_primary_keys(config),
        partition_count=1,
        partition_size=1,
        sort_mode=config.sort_mode,
    )


def smartsheet_source(
    access_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[SmartsheetResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = SMARTSHEET_ENDPOINTS[endpoint]
    incremental_start = (
        _incremental_start(should_use_incremental_field, db_incremental_field_last_value)
        if config.incremental_fields
        else None
    )

    if config.fanout is not None:
        return _fanout_source(access_token, endpoint, config, team_id, job_id, incremental_start)

    client_config = _client_config(access_token)
    client_config["paginator"] = _paginator(config.pagination, config.page_size)

    params: dict[str, Any] = {"pageSize": config.page_size}
    if config.pagination == "event_stream":
        since = (
            _iso(incremental_start - EVENTS_SINCE_OVERLAP)
            if incremental_start is not None
            else EVENTS_FULL_REFRESH_SINCE
        )
        params = {"since": since, "maxCount": config.page_size}

    rest_config: RESTAPIConfig = {
        "client": client_config,
        # Per-resource settings are fully specified below, so no shared defaults are needed.
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    "data_selector": config.data_selector,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.stream_position is not None:
            initial_paginator_state = {"cursor": resume.stream_position}
        elif resume is not None and resume.next_page is not None:
            initial_paginator_state = {"page": resume.next_page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes) rather than skipping it.
        if not state:
            return
        if state.get("cursor") is not None:
            resumable_source_manager.save_state(SmartsheetResumeConfig(stream_position=str(state["cursor"])))
        elif state.get("page") is not None:
            resumable_source_manager.save_state(SmartsheetResumeConfig(next_page=int(state["page"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=_primary_keys(config),
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode=config.sort_mode,
        column_hints=resource.column_hints,
    )


def validate_credentials(access_token: str) -> bool:
    """Confirm the access token is valid. ``/users/me`` is a cheap authenticated probe
    that works for any valid token regardless of granted scopes."""
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(access_token,)),
        f"{SMARTSHEET_BASE_URL}/users/me",
        headers={"Authorization": f"Bearer {access_token}", **_non_secret_headers()},
    )
    return ok
