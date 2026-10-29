from collections.abc import Callable
from typing import Any

from requests import HTTPError

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import BearerTokenAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    rename_parent_fields,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.vimeo.settings import (
    AUTH_ERROR,
    BASE_URL,
    ENDPOINTS,
    FANOUT_ENDPOINTS,
    PAGE_SIZE,
    PERMISSION_ERROR,
    PRIMARY_KEYS,
)


@frozen
class VimeoResumeConfig:
    # Top-level endpoints resume from the `paging.next` URL of the last page.
    next_url: str | None = None
    # Fan-out endpoints resume by parent, in the shape of
    # `common.rest_source.__init__._make_paginate_dependent_resource`.
    completed: list[str] | None = None
    current: str | None = None
    child_state: dict[str, Any] | None = None


def vimeo_headers(api_version: str) -> dict[str, str]:
    return {"Accept": f"application/vnd.vimeo.*+json;version={api_version}"}


def _top_level_endpoint(endpoint: str) -> str:
    while endpoint in FANOUT_ENDPOINTS:
        endpoint = FANOUT_ENDPOINTS[endpoint].parent
    return endpoint


def validate_credentials(access_token: str, api_version: str, schema_name: str | None) -> tuple[bool, str | None]:
    path = schema_for_resource(ENDPOINTS, _top_level_endpoint(schema_name)) if schema_name else "/me"
    params: dict[str, str | int] = {"per_page": 1} if schema_name else {"fields": "uri"}
    with make_tracked_session() as session:
        response = session.get(
            f"{BASE_URL}{path}",
            auth=BearerTokenAuth(access_token),
            headers=vimeo_headers(api_version),
            params=params,
            timeout=30,
        )
    try:
        response.raise_for_status()
    except HTTPError:
        if response.status_code == 401:
            return False, AUTH_ERROR
        if response.status_code == 403:
            return (False, PERMISSION_ERROR) if schema_name else (True, None)
        raise
    return True, None


def _connection_link(connection: str) -> Callable[[dict[str, Any]], dict[str, Any] | list[dict[str, Any]]]:
    def _link(row: dict[str, Any]) -> dict[str, Any] | list[dict[str, Any]]:
        link = ((row.get("metadata") or {}).get("connections") or {}).get(connection) or {}
        if not link.get("uri") or link.get("total") == 0:
            return []
        return {"uri": row["uri"], "connection_uri": link["uri"]}

    return _link


def _resource_chain(endpoint: str, connection: str | None = None) -> list[EndpointResource]:
    """Resources from a top-level list down to `endpoint`.

    When `connection` is set, `endpoint` is a parent: it reads only the fields the next level needs.
    """
    params: dict[str, Any] = {"page": 1, "per_page": PAGE_SIZE}
    resource: EndpointResource = {"name": endpoint, "write_disposition": "replace", "endpoint": {}}
    chain: list[EndpointResource] = []
    fanout = FANOUT_ENDPOINTS.get(endpoint)
    if fanout is None:
        path = schema_for_resource(ENDPOINTS, endpoint)
        params.update({"sort": "date", "direction": "asc"})
    else:
        chain = _resource_chain(fanout.parent, fanout.connection)
        path = "{connection_uri}"
        params.update(fanout.params)
        params["connection_uri"] = {"type": "resolve", "resource": fanout.parent, "field": "connection_uri"}
        resource["include_from_parent"] = ["uri"]
    if connection is not None:
        params["fields"] = f"uri,metadata.connections.{connection}.uri,metadata.connections.{connection}.total"
        resource["data_map"] = _connection_link(connection)
    endpoint_config: Endpoint = {
        "path": path,
        "params": params,
        "paginator": {"type": "json_response", "next_url_path": "paging.next"},
        "data_selector": "data",
        "data_selector_required": True,
    }
    if fanout is not None:
        # A parent deleted between its listing and this request must not fail the sync.
        endpoint_config["response_actions"] = [{"status_code": 404, "action": "ignore"}]
    resource["endpoint"] = endpoint_config
    return [*chain, resource]


def vimeo_source(
    access_token: str,
    endpoint: str,
    api_version: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[VimeoResumeConfig],
) -> SourceResponse:
    config: RESTAPIConfig = {
        "client": {
            "base_url": BASE_URL,
            "auth": {"type": "bearer", "token": access_token},
            "headers": vimeo_headers(api_version),
            "allowed_hosts": ["api.vimeo.com"],
            "allow_redirects": False,
            "request_timeout": 30,
        },
        "resources": [*_resource_chain(endpoint)],
    }
    initial_state: dict[str, Any] | None = None
    if resumable_source_manager.can_resume():
        state = resumable_source_manager.load_state()
        if state is not None and state.next_url:
            initial_state = {"next_url": state.next_url}
        elif state is not None and (state.completed or state.current):
            initial_state = {
                "completed": state.completed or [],
                "current": state.current,
                "child_state": state.child_state,
            }

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if not state:
            return
        if state.get("next_url"):
            resumable_source_manager.save_state(VimeoResumeConfig(next_url=state["next_url"]))
        elif "completed" in state:
            resumable_source_manager.save_state(
                VimeoResumeConfig(
                    completed=state["completed"], current=state.get("current"), child_state=state.get("child_state")
                )
            )

    resources = rest_api_resources(
        config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_state,
    )
    resource = next(r for r in resources if r.name == endpoint)
    fanout = FANOUT_ENDPOINTS.get(endpoint)
    if fanout is not None:
        resource.add_map(rename_parent_fields(fanout.parent, {"uri": fanout.parent_uri_column}))
    primary_keys = fanout.primary_keys if fanout is not None else PRIMARY_KEYS
    return SourceResponse(name=endpoint, items=lambda: resource, primary_keys=primary_keys)
