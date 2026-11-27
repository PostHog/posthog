from dataclasses import field
from typing import Any, cast
from urllib.parse import quote

from requests import Response

from products.warehouse_sources.sources.sdk import (
    ClientConfig,
    DependentEndpointConfig,
    Endpoint,
    EndpointResource,
    IncrementalConfig,
    JSONResponseCursorPaginator,
    RESTAPIConfig,
    ResumableSourceManager,
    SourceResponse,
    build_dependent_resource,
    format_datetime,
    frozen,
    make_tracked_session,
    rest_api_resource,
    schema_for_resource,
)
from products.warehouse_sources.sources.superwall._config import SuperwallSourceConfig
from products.warehouse_sources.sources.superwall.settings import BASE_URL, ENDPOINTS, PRIMARY_KEYS, SuperwallEndpoint

PAGE_SIZE = 100


@frozen
class SuperwallResumeConfig:
    cursor: str | None = None
    # Entitlement grants: the state `build_dependent_resource` checkpoints over the entitlement listing.
    fanout_state: dict[str, Any] | None = None


@frozen
class _FanoutEndpoint:
    name: str
    path: str
    page_size: int = PAGE_SIZE
    incremental_fields: list[Any] = field(default_factory=list)
    default_incremental_field: str | None = None


class SuperwallPaginator(JSONResponseCursorPaginator):
    def update_state(self, response: Response, data: list[Any] | None = None) -> None:
        body = response.json()
        if body.get("has_more") is False:
            self._has_next_page = False
            return
        if body.get("has_more") is not True:
            raise ValueError("Superwall response has no valid has_more flag")
        super().update_state(response, data)
        if not self.has_next_page:
            raise ValueError("Superwall response has_more is true but has no next cursor")


def _paginator(settings: SuperwallEndpoint) -> SuperwallPaginator:
    iterator = settings.pagination == "iterator"
    return SuperwallPaginator(
        cursor_path="iterator" if iterator else "data[-1].id",
        cursor_param="iterator" if iterator else "starting_after",
        raise_on_repeated_cursor=True,
    )


def _format_start_time(value: Any) -> str | None:
    return None if value is None else format_datetime(value, "iso_z")


def _headers(config: SuperwallSourceConfig) -> dict[str, str]:
    return {"Authorization": f"Bearer {config.api_key}", "Accept": "application/json"}


def _project_url(config: SuperwallSourceConfig, api_version: str) -> str:
    return f"{BASE_URL}/{api_version}/projects/{quote(config.project_id, safe='')}"


def _organization_id_from(response: Response) -> str:
    organization_id = response.json().get("organization_id")
    if organization_id is None:
        raise ValueError("Superwall project response has no organization_id")
    return str(organization_id)


def fetch_organization_id(config: SuperwallSourceConfig, api_version: str) -> str:
    with make_tracked_session(redact_values=(config.api_key,)) as session:
        response = session.get(_project_url(config, api_version), headers=_headers(config), timeout=30)
    response.raise_for_status()
    return _organization_id_from(response)


def get_resource(
    config: SuperwallSourceConfig,
    name: str,
    api_version: str,
    organization_id: str | None = None,
    incremental: IncrementalConfig | None = None,
) -> EndpointResource:
    settings = schema_for_resource(ENDPOINTS, name)
    path = settings.path.replace("{project_id}", quote(config.project_id, safe=""))
    params: dict[str, Any] = dict(settings.params)
    if settings.scope_param == "organization_id":
        params["organization_id"] = organization_id
    elif settings.scope_param is not None and "{project_id}" not in settings.path:
        params[settings.scope_param] = getattr(config, settings.scope_param)
    endpoint: Endpoint = {
        "path": f"/{api_version}/{path}",
        "params": params,
        "data_selector": "data",
        "data_selector_required": True,
    }
    if settings.pagination == "single_page":
        endpoint["paginator"] = "single_page"
    else:
        params["limit"] = PAGE_SIZE
        endpoint["paginator"] = _paginator(settings)
    if incremental is not None:
        endpoint["incremental"] = incremental
    return {
        "name": name,
        "table_name": name,
        "primary_key": PRIMARY_KEYS[name],
        "write_disposition": {"disposition": "merge", "strategy": "upsert"} if incremental else "replace",
        "table_format": "delta",
        "endpoint": endpoint,
    }


def probe_credentials(config: SuperwallSourceConfig, schema_name: str | None, api_version: str) -> Response:
    with make_tracked_session(redact_values=(config.api_key,)) as session:
        if schema_name is None:
            return session.get(f"{BASE_URL}/{api_version}/projects", headers=_headers(config), timeout=10)
        settings = ENDPOINTS[schema_name]
        organization_id = None
        if settings.scope_param == "organization_id":
            project = session.get(_project_url(config, api_version), headers=_headers(config), timeout=10)
            if project.status_code != 200:
                return project
            organization_id = _organization_id_from(project)
        # A fan-out child needs a parent id, and its scope is the parent's, so probe the parent listing.
        resource = get_resource(config, settings.parent or schema_name, api_version, organization_id)
        endpoint = cast(Endpoint, resource["endpoint"])
        params = dict(endpoint.get("params") or {})
        if "limit" in params:
            params["limit"] = 1
        return session.get(f"{BASE_URL}{endpoint['path']}", params=params, headers=_headers(config), timeout=10)


def _client_config(config: SuperwallSourceConfig) -> ClientConfig:
    return {
        "base_url": BASE_URL,
        "auth": {"type": "bearer", "token": config.api_key},
        "headers": {"Accept": "application/json"},
        "request_timeout": 30,
        "retry_budget_seconds": 120,
        "retry_after_max_seconds": 60,
    }


def _grants_source(
    config: SuperwallSourceConfig,
    endpoint: str,
    parent: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[SuperwallResumeConfig],
    api_version: str,
) -> SourceResponse:
    settings = ENDPOINTS[endpoint]
    parent_settings = ENDPOINTS[parent]
    endpoint_configs = {
        parent: _FanoutEndpoint(name=parent, path=f"/{api_version}/{parent_settings.path}"),
        endpoint: _FanoutEndpoint(name=endpoint, path=f"/{api_version}/{settings.path}"),
    }
    fanout = DependentEndpointConfig(
        parent_name=parent,
        resolve_param="id",
        resolve_field="id",
        include_from_parent=[],
        parent_params={**dict(parent_settings.params), "project_id": config.project_id},
        child_params=dict(settings.params),
    )
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state:
            resumable_source_manager.save_state(SuperwallResumeConfig(fanout_state=state))

    child = build_dependent_resource(
        endpoint_configs=endpoint_configs,
        child_endpoint=endpoint,
        fanout=fanout,
        client_config=_client_config(config),
        path_format_values={},
        team_id=team_id,
        job_id=job_id,
        db_incremental_field_last_value=None,
        parent_endpoint_extra={
            "data_selector": "data",
            "data_selector_required": True,
            "paginator": _paginator(parent_settings),
        },
        child_endpoint_extra={
            "data_selector": "data",
            "data_selector_required": True,
            "paginator": _paginator(settings),
        },
        resume_hook=save_checkpoint,
        initial_paginator_state=resume.fanout_state if resume else None,
        resume_parent_pagination=True,
    )
    return SourceResponse(
        name=endpoint,
        items=lambda: child,
        primary_keys=PRIMARY_KEYS[endpoint],
        partition_keys=[settings.partition_key],
        partition_mode="datetime",
        partition_format="month",
        sort_mode=None,
    )


def superwall_source(
    config: SuperwallSourceConfig,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[SuperwallResumeConfig],
    api_version: str,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> SourceResponse:
    settings = schema_for_resource(ENDPOINTS, endpoint)
    if settings.parent is not None:
        return _grants_source(config, endpoint, settings.parent, team_id, job_id, resumable_source_manager, api_version)

    organization_id = fetch_organization_id(config, api_version) if settings.scope_param == "organization_id" else None
    incremental: IncrementalConfig | None = None
    if should_use_incremental_field and endpoint == "audit_logs":
        incremental = {"cursor_path": "timestamp", "start_param": "start_time", "convert": _format_start_time}
    rest_config: RESTAPIConfig = {
        "client": _client_config(config),
        "resources": [get_resource(config, endpoint, api_version, organization_id, incremental)],
    }
    initial_state: dict[str, Any] | None = None
    if settings.pagination != "single_page" and resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.cursor is not None:
            initial_state = {"cursor": resume.cursor}

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state and state.get("cursor") is not None:
            resumable_source_manager.save_state(SuperwallResumeConfig(cursor=str(state["cursor"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value if incremental else None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_state,
    )
    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=PRIMARY_KEYS[endpoint],
        partition_keys=[settings.partition_key],
        partition_mode="datetime",
        partition_format="month",
        # Audit logs come newest first, and the other lists page by id.
        sort_mode=None,
        supports_resume=settings.pagination != "single_page",
    )
