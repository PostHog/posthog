from typing import Any, Optional, cast

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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.jsonpath_utils import (
    find_values,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    EndpointResource,
    IncrementalConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.livestorm.settings import (
    LIVESTORM_BASE_URL,
    LIVESTORM_ENDPOINTS,
    PAGE_SIZE,
    LivestormEndpointConfig,
)

_JSON_API_ENVELOPE_KEYS = ("attributes", "relationships", "links", "type")


@frozen
class LivestormResumeConfig:
    # Next page of a top-level list.
    next_page: Optional[int] = None
    # `build_dependent_resource` checkpoint for the per-session people walk.
    fanout_state: Optional[dict[str, Any]] = None


class LivestormPaginator(PageNumberPaginator):
    """Follows `meta.next_page`. Livestorm answers a page past the last one with a 400, so the walk
    must stop on the server's signal instead of probing for an empty page."""

    def __init__(self) -> None:
        super().__init__(base_page=0, page_param="page[number]")

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        try:
            values = find_values("meta.next_page", response.json())
        except Exception:
            values = []
        next_page = values[0] if values else None
        if next_page is None:
            self._has_next_page = False
            return
        self.page = int(next_page)
        self._has_next_page = True


def flatten_json_api(item: dict[str, Any]) -> dict[str, Any]:
    row = {key: value for key, value in item.items() if key not in _JSON_API_ENVELOPE_KEYS}
    row.update(item.get("attributes") or {})
    return row


def _client_config(api_token: str) -> ClientConfig:
    return {
        "base_url": LIVESTORM_BASE_URL,
        "headers": {"Accept": "application/vnd.api+json"},
        # Livestorm takes the bare token, without a `Bearer` prefix.
        "auth": {"type": "api_key", "name": "Authorization", "api_key": api_token, "location": "header"},
        "paginator": LivestormPaginator(),
    }


def _incremental_config(cursor: str) -> IncrementalConfig:
    return {"cursor_path": cursor, "start_param": "filter[updated_since]", "initial_value": "0"}


def get_resource(config: LivestormEndpointConfig, is_incremental: bool) -> EndpointResource:
    params: dict[str, Any] = {"page[size]": PAGE_SIZE}
    if is_incremental:
        params["filter[updated_since]"] = {"type": "incremental", "cursor_path": "updated_at", "initial_value": "0"}
    return {
        "name": config.name,
        "table_name": config.name,
        "primary_key": config.primary_keys,
        "write_disposition": {"disposition": "merge", "strategy": "upsert"} if is_incremental else "replace",
        "endpoint": {"path": config.path, "params": params, "data_selector": "data"},
        "data_map": flatten_json_api,
        "table_format": "delta",
    }


def _source_response(config: LivestormEndpointConfig, resource: Any, is_incremental: bool) -> SourceResponse:
    return SourceResponse(
        name=config.name,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        # Livestorm documents no order for its lists, so the watermark may only move once the
        # whole run has been read.
        sort_mode="desc" if is_incremental else "asc",
    )


def livestorm_source(
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[LivestormResumeConfig],
    db_incremental_field_last_value: Optional[Any],
    should_use_incremental_field: bool = False,
) -> SourceResponse:
    config = LIVESTORM_ENDPOINTS[endpoint]
    is_incremental = should_use_incremental_field and bool(config.incremental_fields)
    client_config = _client_config(api_token)
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    if config.fanout is not None:

        def save_fanout_checkpoint(state: Optional[dict[str, Any]]) -> None:
            if state:
                resumable_source_manager.save_state(LivestormResumeConfig(fanout_state=state))

        child = cast(
            Resource,
            build_dependent_resource(
                endpoint_configs=LIVESTORM_ENDPOINTS,
                child_endpoint=endpoint,
                fanout=config.fanout,
                client_config=client_config,
                path_format_values={},
                team_id=team_id,
                job_id=job_id,
                db_incremental_field_last_value=db_incremental_field_last_value,
                should_use_incremental_field=is_incremental,
                incremental_field="updated_at",
                incremental_config_factory=_incremental_config,
                parent_endpoint_extra={"data_selector": "data"},
                child_endpoint_extra={"data_selector": "data"},
                parent_data_map=flatten_json_api,
                page_size_param="page[size]",
                resume_hook=save_fanout_checkpoint,
                initial_paginator_state=resume.fanout_state if resume else None,
            ),
        ).add_map(flatten_json_api)
        return _source_response(config, child, is_incremental)

    rest_config: RESTAPIConfig = {
        "client": client_config,
        "resource_defaults": {},
        "resources": [get_resource(config, is_incremental)],
    }

    initial_paginator_state = {"page": resume.next_page} if resume and resume.next_page is not None else None

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state and state.get("page") is not None:
            resumable_source_manager.save_state(LivestormResumeConfig(next_page=int(state["page"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    return _source_response(config, resource, is_incremental)


def probe_credentials(api_token: str) -> tuple[bool, int | None]:
    return validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_token,)),
        f"{LIVESTORM_BASE_URL}/events?page[size]=1",
        headers={"Authorization": api_token, "Accept": "application/vnd.api+json"},
    )
