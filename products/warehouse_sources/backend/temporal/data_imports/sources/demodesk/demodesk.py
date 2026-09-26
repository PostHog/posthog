import dataclasses
from datetime import UTC, datetime
from typing import Any, Optional, cast

from requests import Request, Response

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
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ApiKeyAuthConfig,
    BearerTokenAuthConfig,
    ClientConfig,
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.demodesk.settings import (
    DEMODESK_ENDPOINTS,
    DemodeskApiVersion,
    DemodeskEndpointConfig,
)

BASE_URL = "https://demodesk.com/api"


@dataclasses.dataclass
class DemodeskResumeConfig:
    # v1 endpoints checkpoint a page number, v2 endpoints an opaque cursor; one field is set.
    page: int | None = None
    cursor: str | None = None


def to_iso8601(value: Any) -> str:
    """Format an incremental watermark for the v2 Ransack datetime filters."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


class DemodeskPagePaginator(BasePaginator):
    """Paginator for v1 list endpoints: 1-based `page` param, `meta.hasNextPage` in the response.

    A response without `meta.hasNextPage` (e.g. an unpaginated collection) stops after its first
    page, so the same paginator is safe on v1 endpoints whose pagination is undocumented.
    """

    def __init__(self) -> None:
        super().__init__()
        self._page = 1

    def init_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["page"] = self._page

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        try:
            meta = response.json().get("meta") or {}
        except Exception:
            self._has_next_page = False
            return

        if meta.get("hasNextPage"):
            self._page += 1
            self._has_next_page = True
        else:
            self._has_next_page = False

    def update_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["page"] = self._page

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {"page": self._page} if self._has_next_page else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        page = state.get("page")
        if page is not None:
            self._page = int(page)
            self._has_next_page = True


def demodesk_client_config(api_key: str, api_version: DemodeskApiVersion) -> ClientConfig:
    # The same user-level API key authenticates both surfaces, but v1 takes it in a custom
    # `api-key` header while v2 takes it as a Bearer token.
    auth: ApiKeyAuthConfig | BearerTokenAuthConfig
    if api_version == "v1":
        auth = {"type": "api_key", "name": "api-key", "api_key": api_key, "location": "header"}
    else:
        auth = {"type": "bearer", "token": api_key}
    return {
        "base_url": BASE_URL,
        "auth": auth,
        "headers": {"Accept": "application/json"},
    }


def _flatten_json_api_item(item: dict[str, Any]) -> dict[str, Any]:
    """Merge a v1 JSON:API item's `attributes` into the row root, keeping `id`/`relationships`."""
    attributes = item.pop("attributes", None)
    if isinstance(attributes, dict):
        for key, value in attributes.items():
            item.setdefault(key, value)
    return item


def _paginator_for(config: DemodeskEndpointConfig) -> BasePaginator:
    if config.api_version == "v1":
        return DemodeskPagePaginator()
    return JSONResponseCursorPaginator(cursor_path="meta.nextCursor", cursor_param="cursor")


def get_resource(
    config: DemodeskEndpointConfig,
    should_use_incremental_field: bool,
    incremental_field_name: str | None,
    db_incremental_field_last_value: Optional[Any],
) -> EndpointResource:
    params: dict[str, Any] = dict(config.params)
    if config.api_version == "v2":
        params["limit"] = config.page_size

    endpoint: Endpoint = {
        "path": config.path,
        "params": params,
        "data_selector": "data",
        "paginator": _paginator_for(config),
    }

    # Only send the server-side floor once a real watermark exists: the first incremental sync must
    # go out unfiltered so it captures the full history, and the pipeline still advances the
    # watermark from the synced rows.
    if should_use_incremental_field and db_incremental_field_last_value is not None:
        field_name = incremental_field_name or config.default_incremental_field
        start_param = config.incremental_param_by_field.get(field_name or "")
        if start_param is not None:
            endpoint["incremental"] = {
                "start_param": start_param,
                "cursor_path": field_name or "",
                "initial_value": None,
                "convert": to_iso8601,
            }

    return {
        "name": config.name,
        "table_name": config.name,
        "write_disposition": {
            "disposition": "merge",
            "strategy": "upsert",
        }
        if should_use_incremental_field
        else "replace",
        "endpoint": endpoint,
        "table_format": "delta",
    }


def _fanout_resource(
    api_key: str,
    config: DemodeskEndpointConfig,
    team_id: int,
    job_id: str,
    db_incremental_field_last_value: Optional[Any],
    should_use_incremental_field: bool,
    incremental_field_name: str | None,
) -> Resource:
    assert config.fanout is not None
    parent = DEMODESK_ENDPOINTS[config.fanout.parent_name]
    return cast(
        Resource,
        build_dependent_resource(
            endpoint_configs={config.name: config, parent.name: parent},
            child_endpoint=config.name,
            fanout=config.fanout,
            client_config=demodesk_client_config(api_key, config.api_version),
            path_format_values={},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=db_incremental_field_last_value,
            should_use_incremental_field=should_use_incremental_field,
            incremental_field=incremental_field_name,
            # The child endpoints take no page-size param, and the parent's `limit` default already
            # matches PAGE_SIZE, so no size param is sent on either request.
            page_size_param=None,
            parent_endpoint_extra={
                "paginator": _paginator_for(parent),
                "data_selector": "data",
            },
            child_endpoint_extra={
                "paginator": SinglePagePaginator(),
                "data_selector": "data",
            },
        ),
    )


def demodesk_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[DemodeskResumeConfig],
    db_incremental_field_last_value: Optional[Any],
    should_use_incremental_field: bool = False,
    incremental_field_name: str | None = None,
) -> Resource:
    config = DEMODESK_ENDPOINTS[endpoint]

    if config.fanout is not None:
        return _fanout_resource(
            api_key,
            config,
            team_id,
            job_id,
            db_incremental_field_last_value,
            should_use_incremental_field,
            incremental_field_name,
        )

    rest_config: RESTAPIConfig = {
        "client": demodesk_client_config(api_key, config.api_version),
        "resource_defaults": {},
        "resources": [
            get_resource(config, should_use_incremental_field, incremental_field_name, db_incremental_field_last_value)
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            if resume_config.page is not None:
                initial_paginator_state = {"page": resume_config.page}
            elif resume_config.cursor is not None:
                initial_paginator_state = {"cursor": resume_config.cursor}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if not state:
            return
        if state.get("page") is not None:
            resumable_source_manager.save_state(DemodeskResumeConfig(page=int(state["page"])))
        elif state.get("cursor"):
            resumable_source_manager.save_state(DemodeskResumeConfig(cursor=str(state["cursor"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    if config.flatten_json_api:
        resource = resource.add_map(_flatten_json_api_item)
    return resource


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    # `/v2/me` is the cheapest authenticated probe: it only confirms the key is genuine, without
    # touching a resource the key may lack visibility into.
    res = make_tracked_session().get(
        f"{BASE_URL}/v2/me",
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        timeout=10,
    )
    if res.status_code == 200:
        return True, None
    if res.status_code in (401, 403):
        return False, "Demodesk rejected the API key. Check the key in your Demodesk integration settings."
    return False, f"Could not reach the Demodesk API (HTTP {res.status_code}). Try again shortly."
