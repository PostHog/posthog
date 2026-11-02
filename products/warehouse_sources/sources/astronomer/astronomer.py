import re
from typing import Any

from requests.exceptions import HTTPError

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.astronomer.settings import (
    AUTH_ERROR,
    BASE_URL,
    ENDPOINTS,
    PAGE_SIZE,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import BearerTokenAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    rename_parent_fields,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.astronomer import (
    AstronomerSourceConfig,
)


@frozen
class AstronomerResumeConfig:
    paginator_state: dict[str, Any]


def organization_path(organization_id: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", organization_id):
        raise ValueError("Enter the Astronomer organization ID, not a URL.")
    return f"organizations/{organization_id}/"


def validate_credentials(config: AstronomerSourceConfig, schema_name: str | None = None) -> tuple[bool, str | None]:
    try:
        prefix = organization_path(config.organization_id)
    except ValueError as error:
        return False, str(error)

    name = schema_name or "deployments"
    endpoint = schema_for_resource(ENDPOINTS, name)
    client = RESTClient(
        base_url=BASE_URL,
        auth=BearerTokenAuth(token=config.api_token),
        paginator=SinglePagePaginator(),
        allow_redirects=False,
        request_timeout=(10, 60),
    )
    permission = endpoint["permission"]
    try:
        if name == "deploys":
            permission = ENDPOINTS["deployments"]["permission"]
            parents = next(
                client.paginate(path=prefix + "deployments", params={"limit": 1}, data_selector="deployments")
            )
            if not parents:
                return True, None
            path = endpoint["path"].format(deployment_id=parents[0]["id"])
            permission = endpoint["permission"]
        else:
            path = endpoint["path"]
        next(client.paginate(path=prefix + path, params={"limit": 1}, data_selector=name))
    except HTTPError as error:
        status = error.response.status_code if error.response is not None else None
        if status == 401:
            return False, AUTH_ERROR
        if status == 403:
            if schema_name is None:
                return True, None
            return False, f"Astronomer denied access. Grant `{permission}` to the API token."
        if status == 404:
            return False, "Astronomer could not find the resource. Check the organization ID and the token permissions."
        raise
    return True, None


def warehouse_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in row.items()
        if key not in {"environmentVariables", "bundleUploadUrl", "dagsUploadUrl"}
    }


def endpoint_resource(name: str, prefix: str) -> EndpointResource:
    endpoint = schema_for_resource(ENDPOINTS, name)
    request: Endpoint = {
        "path": prefix + endpoint["path"],
        "data_selector": name,
        "data_selector_required": True,
        "params": {"sorts": "createdAt:asc"},
    }
    resource: EndpointResource = {
        "name": name,
        "table_name": name,
        "write_disposition": "replace",
        "table_format": "delta",
        "endpoint": request,
        "data_map": warehouse_row,
    }
    if name == "deploys":
        resource["include_from_parent"] = ["id"]
        request["params"] = {"deployment_id": {"type": "resolve", "resource": "deployments", "field": "id"}}
    return resource


def astronomer_source(
    config: AstronomerSourceConfig,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[AstronomerResumeConfig],
) -> SourceResponse:
    settings = schema_for_resource(ENDPOINTS, endpoint)
    prefix = organization_path(config.organization_id)
    resource = endpoint_resource(endpoint, prefix)
    resources: list[str | EndpointResource] = [resource]
    if endpoint == "deploys":
        resources.insert(0, endpoint_resource("deployments", prefix))

    api_config: RESTAPIConfig = {
        "client": {
            "base_url": BASE_URL,
            "auth": {"type": "bearer", "token": config.api_token},
            "allow_redirects": False,
            "request_timeout": (10, 60),
            "paginator": {"type": "offset", "limit": PAGE_SIZE, "total_path": "totalCount"},
        },
        "resources": resources,
    }
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state is not None:
            resumable_source_manager.save_state(AstronomerResumeConfig(paginator_state=state))

    built = rest_api_resources(
        api_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=resume.paginator_state if resume else None,
    )
    result = next(item for item in built if item.name == endpoint)
    if endpoint == "deploys":
        result.add_map(rename_parent_fields("deployments", {"id": "deploymentId"}))
    return SourceResponse(
        name=endpoint,
        items=lambda: result,
        primary_keys=settings["primary_keys"],
        partition_mode="datetime",
        partition_keys=["createdAt"],
        partition_format="month",
        sort_mode=None,
    )
