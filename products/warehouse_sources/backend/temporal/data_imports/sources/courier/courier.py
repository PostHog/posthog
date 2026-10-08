import dataclasses
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Optional, cast
from urllib.parse import quote

import structlog
from dateutil import parser as date_parser
from requests import Response

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    EndpointResource,
    IncrementalConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.courier.settings import (
    COURIER_BASE_URL,
    COURIER_PAGE_SIZE,
    ENDPOINTS_CONFIG,
    FANOUT_ENDPOINT_CONFIGS,
    CourierEndpointConfig,
)

# Courier returns HTTP 403 (not 401) for both a missing and an invalid bearer token, with this
# message in the body — confirmed by probing the live API with no/bad credentials.
AUTH_ERROR_MESSAGE = "Invalid or missing authentication credentials"

DEFAULT_INCREMENTAL_START = "1970-01-01T00:00:00Z"

logger = structlog.get_logger(__name__)


class CourierCursorPaginator(JSONResponseCursorPaginator):
    """Cursor paginator that stops once the cursor stops advancing.

    Courier's journey-versions endpoint returns a `paging.cursor` and its reference calls the
    endpoint cursor-paged, but it documents no `cursor` request param. An API that ignores the
    param returns the same page and the same cursor forever, so a repeated cursor ends the walk
    here the way a repeated next URL ends it in `BaseNextUrlPaginator`.
    """

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        previous_cursor = self._cursor_value
        super().update_state(response, data)
        if self._has_next_page and self._cursor_value == previous_cursor:
            logger.warning(
                "Pagination is not advancing (repeated cursor); treating as last page",
                paginator=str(self),
            )
            self._has_next_page = False


@frozen
class CourierResumeConfig:
    # Top-level endpoints resume from the cursor of the last fully-yielded page.
    cursor: str | None = None
    # Fan-out endpoints resume by parent: the child paths already fully synced, the one in
    # progress, and that parent's paginator state.
    completed: list[str] | None = None
    current: str | None = None
    child_state: dict[str, Any] | None = None


def _to_iso8601(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _normalize_row(item: dict[str, Any], timestamp_fields: tuple[str, ...]) -> dict[str, Any]:
    """Convert Courier's epoch-millisecond and ISO-8601 date fields to real datetimes.

    The warehouse then types these columns as timestamps (useful for querying) and the
    partitioner reads the datetime directly rather than misinterpreting raw millis as epoch
    seconds or leaving a string uninterpreted.
    """
    for name in timestamp_fields:
        value = item.get(name)
        if value is None:
            continue
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            item[name] = datetime.fromtimestamp(value / 1000, tz=UTC)
        elif isinstance(value, str):
            try:
                item[name] = date_parser.isoparse(value)
            except ValueError:
                pass
    return item


def _encode_parent_field(source_field: str, target_field: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Percent-encode a parent id into the field the child path binds.

    `process_parent_data_item` binds the path with `str.format`, so a digest schedule id in the
    legacy `sch/{uuid}` form would splice an unescaped "/" into the path and 404.
    """

    def _mapper(item: dict[str, Any]) -> dict[str, Any]:
        item[target_field] = quote(str(item[source_field]), safe="")
        return item

    return _mapper


def get_resource(name: str, should_use_incremental_field: bool) -> EndpointResource:
    config = ENDPOINTS_CONFIG[name]

    params: dict[str, Any] = {"limit": COURIER_PAGE_SIZE}
    if should_use_incremental_field and config.incremental_param and config.incremental_fields:
        params[config.incremental_param] = {
            "type": "incremental",
            "cursor_path": config.incremental_fields[0]["field"],
            "initial_value": DEFAULT_INCREMENTAL_START,
            "convert": _to_iso8601,
        }

    def data_map(item: dict[str, Any]) -> dict[str, Any]:
        return _normalize_row(item, config.timestamp_fields)

    endpoint_resource: EndpointResource = {
        "name": name,
        "table_name": name,
        "write_disposition": {
            "disposition": "merge",
            "strategy": "upsert",
        }
        if should_use_incremental_field
        else "replace",
        "endpoint": {
            "path": config.path,
            "params": params,
            "data_selector": config.data_selector,
            # Fail loud if Courier ever changes the response envelope key instead of silently
            # syncing 0 rows.
            "data_selector_required": True,
        },
        "table_format": "delta",
    }
    if config.timestamp_fields:
        endpoint_resource["data_map"] = data_map
    return endpoint_resource


def _client_config(api_key: str, config: CourierEndpointConfig) -> ClientConfig:
    return {
        "base_url": COURIER_BASE_URL,
        "auth": {
            "type": "bearer",
            "token": api_key,
        },
        "headers": {"Accept": "application/json"},
        "paginator": {
            "type": "cursor",
            "cursor_path": config.cursor_path,
            "cursor_param": "cursor",
        },
    }


def _top_level_resource(
    config: CourierEndpointConfig,
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[CourierResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
) -> Resource:
    rest_config: RESTAPIConfig = {
        "client": _client_config(api_key, config),
        "resource_defaults": {},
        "resources": [get_resource(endpoint, should_use_incremental_field)],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None and resume_config.cursor:
            initial_paginator_state = {"cursor": resume_config.cursor}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Only persist when there's a next page to resume to; the Redis TTL handles cleanup on
        # completion.
        if state and state.get("cursor"):
            resumable_source_manager.save_state(CourierResumeConfig(cursor=str(state["cursor"])))

    return rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


def _fanout_resource(
    config: CourierEndpointConfig,
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[CourierResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
) -> Resource:
    assert config.fanout is not None
    fanout = config.fanout
    parent_config = FANOUT_ENDPOINT_CONFIGS[fanout.parent_name]

    if config.parent_incremental_param and should_use_incremental_field:
        # The child endpoint takes no timestamp filter, so the run is bounded by the parent
        # listing instead. Like the Messages table, this means a record whose parent predates
        # the watermark is not revisited, even if the vendor added an entry to it since.
        fanout = dataclasses.replace(
            fanout,
            parent_params={
                **fanout.parent_params,
                config.parent_incremental_param: _to_iso8601(db_incremental_field_last_value)
                if db_incremental_field_last_value
                else DEFAULT_INCREMENTAL_START,
            },
        )

    initial_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None and (resume_config.completed or resume_config.current):
            initial_state = {
                "completed": resume_config.completed or [],
                "current": resume_config.current,
                "child_state": resume_config.child_state,
            }

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state is not None:
            resumable_source_manager.save_state(
                CourierResumeConfig(
                    completed=state.get("completed"),
                    current=state.get("current"),
                    child_state=state.get("child_state"),
                )
            )

    child_endpoint_extra: Endpoint = {
        "data_selector": config.data_selector,
        "data_selector_required": True,
    }
    if not config.paginated:
        child_endpoint_extra["paginator"] = SinglePagePaginator()
    elif config.child_cursor_path:
        child_endpoint_extra["paginator"] = CourierCursorPaginator(
            cursor_path=config.child_cursor_path, cursor_param="cursor"
        )

    def no_child_time_filter(_field: str) -> IncrementalConfig | None:
        # No Courier fan-out child accepts a timestamp filter of its own; an incremental run is
        # bounded through the parent listing and merges on the primary key.
        return None

    resource = build_dependent_resource(
        endpoint_configs=FANOUT_ENDPOINT_CONFIGS,
        child_endpoint=endpoint,
        fanout=fanout,
        client_config=_client_config(api_key, config),
        path_format_values={},
        team_id=team_id,
        job_id=job_id,
        db_incremental_field_last_value=db_incremental_field_last_value,
        should_use_incremental_field=should_use_incremental_field,
        incremental_config_factory=no_child_time_filter,
        parent_endpoint_extra={
            "data_selector": parent_config.data_selector,
            "data_selector_required": parent_config.data_selector_required,
        },
        child_endpoint_extra=child_endpoint_extra,
        parent_data_map=(
            _encode_parent_field(config.encode_parent_field, fanout.resolve_field)
            if config.encode_parent_field is not None
            else None
        ),
        page_size_param=config.fanout_page_size_param,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_state,
    )

    child = cast(Resource, resource)
    if config.timestamp_fields:
        # Applied after build_dependent_resource renames the projected parent fields, so a
        # parent timestamp is normalized under the name it ends up with.
        child = child.add_map(lambda item: _normalize_row(item, config.timestamp_fields))
    return child


def courier_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[CourierResumeConfig],
    db_incremental_field_last_value: Optional[Any],
    should_use_incremental_field: bool = False,
) -> SourceResponse:
    config = ENDPOINTS_CONFIG[endpoint]

    build = _fanout_resource if config.fanout is not None else _top_level_resource
    resource = build(
        config,
        api_key,
        endpoint,
        team_id,
        job_id,
        resumable_source_manager,
        should_use_incremental_field,
        db_incremental_field_last_value,
    )

    has_partition_key = config.partition_key is not None

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=list(config.primary_keys),
        partition_count=1 if has_partition_key else None,
        partition_size=1 if has_partition_key else None,
        partition_mode="datetime" if has_partition_key else None,
        partition_format="month" if has_partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode=config.sort_mode,
        column_hints=resource.column_hints,
    )


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{COURIER_BASE_URL}/messages?limit=1",
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        ok_statuses=(200,),
        # Courier's bearer auth carries the token in the standard `Authorization` header, which
        # `requests` already strips on cross-origin redirects.
        allow_redirects=True,
    )
    if ok:
        return True, None

    if status == 403:
        return False, f"Courier authentication failed: {AUTH_ERROR_MESSAGE}. Please check your API key."

    return False, f"Courier API returned an unexpected response (HTTP {status})"
