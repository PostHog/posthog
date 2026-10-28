from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from requests.exceptions import HTTPError

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import APIKeyAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.config_setup import (
    make_parent_key_name,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.harness.settings import (
    AUTH_ERROR,
    ENDPOINTS,
    PERMISSION_ERROR,
    REGION_ERROR,
    REGIONS,
)

if TYPE_CHECKING:
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
    from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.harness import (
        HarnessSourceConfig,
    )


@frozen
class HarnessResumeConfig:
    page: int | None = None
    # Fan-out tables resume by parent, see `common.rest_source.__init__._make_paginate_dependent_resource`.
    completed: list[str] | None = None
    current: str | None = None
    child_state: dict[str, Any] | None = None


def base_url(config: "HarnessSourceConfig") -> str:
    if config.region not in REGIONS:
        raise ValueError(REGION_ERROR)
    return REGIONS[config.region]


def endpoint_config(config: "HarnessSourceConfig", name: str, size: int = 100) -> Endpoint:
    endpoint = schema_for_resource(ENDPOINTS, name)
    params: dict[str, Any] = {"accountIdentifier": config.account_id}
    if endpoint.scope == "project":
        params["orgIdentifier"] = config.organization_id
        params["projectIdentifier"] = config.project_id
    params[endpoint.size_param] = size
    path = endpoint.path
    if endpoint.parent is not None:
        params["parent_identifier"] = {"type": "resolve", "resource": endpoint.parent.name, "field": "identifier"}
        path = f"{path}?{endpoint.parent.param}={{parent_identifier}}"
    request: Endpoint = {
        "path": path,
        "method": endpoint.method,
        "params": params,
        "paginator": {"type": "page_number", "page_param": endpoint.page_param, "total_path": "data.totalPages"},
        "data_selector": "data.content",
        "data_selector_required": True,
    }
    if endpoint.filter_type is not None:
        request["json"] = {"filterType": endpoint.filter_type}
    return request


def validate_credentials(config: "HarnessSourceConfig", schema_name: str | None = None) -> tuple[bool, str | None]:
    try:
        url = base_url(config)
    except ValueError as error:
        return False, str(error)

    probe_name = schema_name or "pipelines"
    parent = schema_for_resource(ENDPOINTS, probe_name).parent
    # Harness governs a fan-out table with its parent's permission, and its list needs a parent id.
    if parent is not None:
        probe_name = parent.name
    endpoint = endpoint_config(config, probe_name, size=1)
    page_param = schema_for_resource(ENDPOINTS, probe_name).page_param
    client = RESTClient(
        base_url=url,
        auth=APIKeyAuth(api_key=config.api_key, name="x-api-key"),
        paginator=SinglePagePaginator(),
        allowed_hosts=[],
        allow_redirects=False,
        request_timeout=60,
    )
    try:
        next(
            client.paginate(
                path=endpoint["path"] or "",
                method=endpoint["method"] or "GET",
                params={**(endpoint["params"] or {}), page_param: 0},
                json=endpoint.get("json"),
                data_selector="data.content",
                data_selector_required=True,
            ),
            None,
        )
    except HTTPError as error:
        status = error.response.status_code if error.response is not None else None
        if status == 401:
            return False, AUTH_ERROR
        if status == 403:
            return (True, None) if schema_name is None else (False, PERMISSION_ERROR)
        if status in (400, 404):
            return False, "Check your Harness account, organization, project, and region."
        raise
    return True, None


def row_normalizer(name: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
    endpoint = schema_for_resource(ENDPOINTS, name)

    def normalize_row(row: dict[str, Any]) -> dict[str, Any]:
        if endpoint.wrapper is not None:
            details = row.get(endpoint.wrapper)
            if not isinstance(details, dict):
                raise ValueError(f"Harness returned a {name} row without an identifier.")
            row = {**details, **{key: value for key, value in row.items() if key != endpoint.wrapper}}
        if endpoint.parent is not None:
            row[endpoint.parent.column] = row.pop(make_parent_key_name(endpoint.parent.name, "identifier"))
        if not all(row.get(key) for key in endpoint.primary_keys):
            raise ValueError(f"Harness returned a {name} row without an identifier.")
        return row

    return normalize_row


def harness_source(
    config: "HarnessSourceConfig",
    name: str,
    team_id: int,
    job_id: str,
    manager: "ResumableSourceManager[HarnessResumeConfig]",
) -> SourceResponse:
    endpoint = schema_for_resource(ENDPOINTS, name)
    resource_config: EndpointResource = {
        "name": name,
        "endpoint": endpoint_config(config, name),
        "write_disposition": "replace",
    }
    resources: list[str | EndpointResource] = [resource_config]
    if endpoint.parent is not None:
        resource_config["include_from_parent"] = ["identifier"]
        resources.insert(
            0,
            {
                "name": endpoint.parent.name,
                "endpoint": endpoint_config(config, endpoint.parent.name),
                "write_disposition": "replace",
                "data_map": row_normalizer(endpoint.parent.name),
            },
        )
    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": base_url(config),
            "auth": {"type": "api_key", "name": "x-api-key", "api_key": config.api_key, "location": "header"},
            "allowed_hosts": [],
            "allow_redirects": False,
            "request_timeout": 60,
        },
        "resources": resources,
    }
    state = manager.load_state() if manager.can_resume() else None

    if endpoint.parent is None:

        def save_checkpoint(paginator_state: dict[str, Any] | None) -> None:
            if paginator_state is not None:
                manager.save_state(HarnessResumeConfig(page=int(paginator_state["page"])))

        resource = rest_api_resource(
            rest_config,
            team_id,
            job_id,
            None,
            resume_hook=save_checkpoint,
            initial_paginator_state={"page": state.page} if state is not None and state.page is not None else None,
        )
    else:

        def save_fanout_checkpoint(fanout_state: dict[str, Any] | None) -> None:
            if fanout_state is not None:
                manager.save_state(
                    HarnessResumeConfig(
                        completed=fanout_state.get("completed"),
                        current=fanout_state.get("current"),
                        child_state=fanout_state.get("child_state"),
                    )
                )

        initial_state = (
            {"completed": state.completed or [], "current": state.current, "child_state": state.child_state}
            if state is not None and (state.completed or state.current)
            else None
        )
        resource = next(
            item
            for item in rest_api_resources(
                rest_config,
                team_id,
                job_id,
                None,
                resume_hook=save_fanout_checkpoint,
                initial_paginator_state=initial_state,
            )
            if getattr(item, "name", None) == name
        )

    resource.add_map(row_normalizer(name))
    return SourceResponse(
        name=name,
        items=lambda: resource,
        primary_keys=list(endpoint.primary_keys),
        sort_mode=None,
        on_complete=manager.clear_state,
    )
