import dataclasses
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from typing import Any, Optional, cast

from requests.exceptions import RequestException

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.bugherd.settings import (
    BUGHERD_BASE_URL,
    BUGHERD_ENDPOINTS,
    BugherdEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.datetime_utils import (
    coerce_datetime_to_utc,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    EndpointResource,
    IncrementalConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

REQUEST_TIMEOUT_SECONDS = 30


@dataclasses.dataclass
class BugherdResumeConfig:
    page: int


def _format_bugherd_datetime(value: Any) -> str:
    """Format a date/datetime-like value as the ISO 8601 `YYYY-MM-DDTHH:MM:SSZ` string
    BugHerd's `updated_since`/`created_since` filters document. Falls back to `str(value)`
    for values that are already a formatted string (e.g. our own `initial_value` seed)."""
    normalized = coerce_datetime_to_utc(value)
    if normalized is None:
        return str(value)
    capped = min(normalized, datetime.now(UTC))
    return capped.strftime("%Y-%m-%dT%H:%M:%SZ")


def _incremental_window(field_name: str, query_param: str) -> IncrementalConfig:
    return {
        "cursor_path": field_name,
        "start_param": query_param,
        "initial_value": "1970-01-01T00:00:00Z",
        "convert": _format_bugherd_datetime,
    }


def _client_config(api_key: str) -> ClientConfig:
    return {
        "base_url": BUGHERD_BASE_URL,
        # BugHerd auth is the API key as the Basic Auth username with the literal string
        # "x" as the password.
        "auth": {"type": "http_basic", "username": api_key, "password": "x"},
        "headers": {"Accept": "application/json"},
    }


def _list_paginator(config: BugherdEndpointConfig) -> PageNumberPaginator | SinglePagePaginator:
    if not config.paginated:
        return SinglePagePaginator()
    # Pages start at 1; an empty array signals the last page (no total-page count is
    # documented), so we rely on the paginator's default stop-on-empty-page behaviour.
    return PageNumberPaginator(base_page=1, page_param="page")


def validate_credentials(api_key: str, schema_name: Optional[str] = None) -> tuple[bool, str | None]:
    """Probe Show Organization -- the cheapest authenticated call, with no query params."""
    try:
        response = make_tracked_session(redact_values=(api_key,)).get(
            f"{BUGHERD_BASE_URL}/api_v2/organization.json",
            auth=(api_key, "x"),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except RequestException as exc:
        return False, f"Could not reach the BugHerd API: {exc}"

    if response.status_code == 401:
        return False, "Invalid BugHerd API key."
    if response.status_code != 200:
        return False, f"BugHerd API returned an unexpected status ({response.status_code})."

    return True, None


def _resource(
    config: BugherdEndpointConfig,
    should_use_incremental_field: bool,
    incremental_field: str | None,
) -> EndpointResource:
    endpoint_config: Endpoint = {
        "path": config.path,
        "data_selector": config.data_selector,
        "paginator": _list_paginator(config),
    }

    use_merge = should_use_incremental_field and bool(config.incremental_fields)
    if use_merge:
        field_name = incremental_field or config.default_incremental_field or config.incremental_fields[0]["field"]
        query_param = config.incremental_query_params[field_name]
        endpoint_config["incremental"] = _incremental_window(field_name, query_param)

    return {
        "name": config.name,
        "table_name": config.name,
        "write_disposition": {"disposition": "merge", "strategy": "upsert"} if use_merge else "replace",
        "endpoint": endpoint_config,
        "table_format": "delta",
    }


def _make_source_response(config: BugherdEndpointConfig, items_fn: Callable[[], Iterable[Any]]) -> SourceResponse:
    primary_keys = config.primary_key if isinstance(config.primary_key, list) else [config.primary_key]
    return SourceResponse(
        name=config.name,
        items=items_fn,
        primary_keys=primary_keys,
        sort_mode=config.sort_mode,
        partition_count=1 if config.partition_key else None,
        partition_size=1 if config.partition_key else None,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def bugherd_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[BugherdResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = BUGHERD_ENDPOINTS[endpoint]
    client_config = _client_config(api_key)

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = {"page": resume_config.page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state and state.get("page") is not None:
            resumable_source_manager.save_state(BugherdResumeConfig(page=int(state["page"])))

    if config.fanout is not None:
        parent_config = BUGHERD_ENDPOINTS[config.fanout.parent_name]
        resource = cast(
            Any,
            build_dependent_resource(
                endpoint_configs=BUGHERD_ENDPOINTS,
                child_endpoint=endpoint,
                fanout=config.fanout,
                client_config=client_config,
                path_format_values={},
                team_id=team_id,
                job_id=job_id,
                db_incremental_field_last_value=db_incremental_field_last_value,
                should_use_incremental_field=should_use_incremental_field,
                incremental_field=incremental_field,
                incremental_config_factory=lambda field_name: _incremental_window(
                    field_name, config.incremental_query_params[field_name]
                ),
                # BugHerd's list endpoints have no client-configurable page-size param.
                page_size_param=None,
                parent_endpoint_extra={
                    "paginator": _list_paginator(parent_config),
                    "data_selector": parent_config.data_selector,
                },
                child_endpoint_extra={
                    "paginator": _list_paginator(config),
                    "data_selector": config.data_selector,
                },
                resume_hook=save_checkpoint,
                initial_paginator_state=initial_paginator_state,
            ),
        )
        dependent_resource = cast(Iterable[Any], resource)
        return _make_source_response(config, lambda: dependent_resource)

    rest_config: RESTAPIConfig = {
        "client": client_config,
        "resource_defaults": {},
        "resources": [_resource(config, should_use_incremental_field, incremental_field)],
    }
    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    return _make_source_response(config, lambda: resource)


__all__ = ["bugherd_source", "validate_credentials", "BugherdResumeConfig"]
