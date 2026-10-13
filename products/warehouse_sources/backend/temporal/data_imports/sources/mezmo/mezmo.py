from typing import Any

from requests import HTTPError

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import rest_api_resources
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    rename_parent_fields,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.mezmo import MezmoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.mezmo.settings import (
    ENDPOINTS,
    INVALID_KEY_MESSAGE,
    PERMISSION_MESSAGE,
)


@frozen
class MezmoResumeConfig:
    paginator_state: dict[str, Any]


def client_config(config: MezmoSourceConfig, api_version: str) -> ClientConfig:
    return {
        "base_url": f"https://api.mezmo.com/{api_version}/",
        "auth": {"type": "api_key", "name": "Authorization", "api_key": f"Token {config.api_key}"},
        "headers": {"x-delegate-account-id": config.account_id} if config.account_id else {},
        "paginator": "single_page",
        "allowed_hosts": ["api.mezmo.com"],
        "allow_redirects": False,
        "request_timeout": (10, 60),
    }


def resource_config(name: str) -> EndpointResource:
    endpoint = schema_for_resource(ENDPOINTS, name)
    endpoint_config: Endpoint = {
        "path": endpoint.path,
        "data_selector": endpoint.data_selector,
        "data_selector_required": True,
    }
    resource: EndpointResource = {
        "name": name,
        "table_name": name,
        "write_disposition": "replace",
        "endpoint": endpoint_config,
    }
    if name == "alerts":
        resource["include_from_parent"] = ["id"]
        endpoint_config["params"] = {"pipeline_id": {"type": "resolve", "resource": "pipelines", "field": "id"}}
    return resource


def get_resource(
    config: MezmoSourceConfig,
    name: str,
    api_version: str,
    team_id: int,
    job_id: str,
    manager: ResumableSourceManager[MezmoResumeConfig] | None = None,
) -> Resource:
    resources: list[str | EndpointResource] = [resource_config(name)]
    resume = None
    if name == "alerts":
        resources.insert(0, resource_config("pipelines"))
        if manager is not None and manager.can_resume():
            resume = manager.load_state()

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if manager is not None and state is not None:
            manager.save_state(MezmoResumeConfig(paginator_state=state))

    built = rest_api_resources(
        {"client": client_config(config, api_version), "resources": resources},
        team_id=team_id,
        job_id=job_id,
        db_incremental_field_last_value=None,
        resume_hook=save_checkpoint if name == "alerts" and manager is not None else None,
        initial_paginator_state=resume.paginator_state if resume is not None else None,
    )
    resource = next(resource for resource in built if resource.name == name)
    if name == "alerts":
        resource.add_map(rename_parent_fields("pipelines", {"id": "pipeline_id"}))
    return resource


def validate_credentials(
    config: MezmoSourceConfig, team_id: int, api_version: str, schema_name: str | None
) -> tuple[bool, str | None]:
    if schema_name is not None and schema_name not in ENDPOINTS:
        return False, "Unknown Mezmo table. Select a table from the source settings."
    if config.api_key.startswith("ste_") and not config.account_id:
        return False, "Enter the delegated account ID for your Mezmo enterprise key."
    probe = schema_name or "pipelines"
    try:
        next(iter(get_resource(config, probe, api_version, team_id, "")), None)
    except HTTPError as error:
        status = error.response.status_code if error.response is not None else None
        if status == 401:
            return False, INVALID_KEY_MESSAGE
        if status == 403:
            return (True, None) if schema_name is None else (False, PERMISSION_MESSAGE)
        raise
    return True, None


def mezmo_source(
    config: MezmoSourceConfig,
    name: str,
    api_version: str,
    team_id: int,
    job_id: str,
    manager: ResumableSourceManager[MezmoResumeConfig],
) -> SourceResponse:
    endpoint = schema_for_resource(ENDPOINTS, name)
    resource = get_resource(config, name, api_version, team_id, job_id, manager)
    return SourceResponse(
        name=name,
        items=lambda: resource,
        primary_keys=list(endpoint.primary_keys),
        supports_resume=name == "alerts",
    )
