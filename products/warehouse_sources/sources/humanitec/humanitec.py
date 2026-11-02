import re
from typing import Any

from requests.exceptions import HTTPError

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    rename_parent_fields,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.humanitec import (
    HumanitecSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.humanitec.settings import (
    API_BASE_URL,
    AUTH_ERROR,
    ENDPOINTS,
    INVALID_ORGANIZATION_ERROR,
    ORGANIZATION_ERROR,
    PERMISSION_ERROR,
)


@frozen
class HumanitecResumeConfig:
    paginator_state: dict[str, Any]


def client_config(config: HumanitecSourceConfig) -> ClientConfig:
    if len(config.organization_id) > 50 or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", config.organization_id):
        raise ValueError(INVALID_ORGANIZATION_ERROR)
    return {
        "base_url": API_BASE_URL,
        "auth": {"type": "bearer", "token": config.api_token},
        "paginator": "single_page",
        "allowed_hosts": [],
        "allow_redirects": False,
        "request_timeout": (10, 60),
    }


def application_environments(row: dict[str, Any]) -> list[dict[str, Any]]:
    # The application list includes environment IDs, so child syncs need no separate environment lookup.
    return [{"app_id": row["id"], "env_id": environment["id"]} for environment in row["envs"]]


def validate_credentials(config: HumanitecSourceConfig) -> tuple[bool, str | None]:
    try:
        client = client_config(config)
    except ValueError as error:
        return False, str(error)

    resource = rest_api_resource(
        {
            "client": client,
            "resources": [
                {"name": "organization", "endpoint": {"path": f"orgs/{config.organization_id}", "data_selector": "$"}}
            ],
        },
        team_id=0,
        job_id="",
        db_incremental_field_last_value=None,
    )
    try:
        next(iter(resource))
    except HTTPError as error:
        if error.response is None:
            raise
        message = {401: AUTH_ERROR, 403: PERMISSION_ERROR, 404: ORGANIZATION_ERROR}.get(error.response.status_code)
        if message:
            return False, message
        raise
    return True, None


def humanitec_source(
    config: HumanitecSourceConfig,
    endpoint: str,
    team_id: int,
    job_id: str,
    manager: ResumableSourceManager[HumanitecResumeConfig],
) -> SourceResponse:
    settings = schema_for_resource(ENDPOINTS, endpoint)
    client = client_config(config)
    prefix = f"orgs/{config.organization_id}/"
    params: dict[str, Any] = {"per_page": 100} if settings.paginated else {}
    target_endpoint: Endpoint = {
        "path": prefix + settings.path,
        "data_selector": "$",
        "paginator": "header_link" if settings.paginated else "single_page",
        "params": params,
    }
    target: EndpointResource = {"name": endpoint, "endpoint": target_endpoint}
    resources: list[str | EndpointResource] = []
    if settings.parent:
        parent: EndpointResource = {
            "name": settings.parent,
            "endpoint": {"path": prefix + "apps", "data_selector": "$"},
        }
        fields = {"id": "app_id"}
        if settings.parent == "application_environments":
            parent["data_map"] = application_environments
            fields = {"app_id": "app_id", "env_id": "env_id"}
        for field, param in fields.items():
            params[param] = {"type": "resolve", "resource": settings.parent, "field": field}
        target["include_from_parent"] = list(fields)
        target["data_map"] = rename_parent_fields(settings.parent, fields)
        resources.append(parent)
    resources.append(target)

    resume = manager.load_state() if manager.can_resume() else None

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state is not None:
            manager.save_state(HumanitecResumeConfig(paginator_state=state))

    rest_config: RESTAPIConfig = {
        "client": client,
        "resource_defaults": {"write_disposition": "replace"},
        "resources": resources,
    }
    resource = next(
        resource
        for resource in rest_api_resources(
            rest_config,
            team_id,
            job_id,
            db_incremental_field_last_value=None,
            resume_hook=save_checkpoint,
            initial_paginator_state=resume.paginator_state if resume else None,
        )
        if resource.name == endpoint
    )
    return SourceResponse(
        name=endpoint, items=lambda: resource, primary_keys=list(settings.primary_keys), sort_mode=None
    )
