from typing import Any, cast

from requests.exceptions import HTTPError

from sources.sdk import (
    ClientConfig,
    Endpoint,
    EndpointResource,
    RESTAPIConfig,
    RESTClient,
    ResumableSourceManager,
    SourceInputs,
    SourceResponse,
    create_auth,
    frozen,
    rest_api_resource,
    schema_for_resource,
)
from sources.sim._config import SimSourceConfig
from sources.sim.settings import ENDPOINTS, PAGE_SIZE

AUTH_ERROR = "Your Sim API key is invalid or expired. Create a new key in Sim settings and reconnect."
PERMISSION_ERROR = "Your Sim API key cannot read this workspace. Check the key's workspace access and permissions."
WORKSPACE_ERROR = "Sim could not find this workspace. Check the workspace ID and your API key's access."


@frozen
class SimResumeConfig:
    cursor: str


def client_config(config: SimSourceConfig, api_version: str) -> ClientConfig:
    return {
        "base_url": f"https://www.sim.ai/api/{api_version}/",
        "auth": {"type": "api_key", "name": "X-API-Key", "api_key": config.api_key, "location": "header"},
        "headers": {"Accept": "application/json"},
        "request_timeout": (10, 60),
        "allowed_hosts": [],
        "allow_redirects": False,
    }


def get_endpoint(config: SimSourceConfig, name: str, page_size: int = PAGE_SIZE) -> Endpoint:
    endpoint = schema_for_resource(ENDPOINTS, name)
    return {
        "path": endpoint.path,
        "params": {
            "workspaceId": config.workspace_id,
            "limit": page_size,
            "sortBy": endpoint.sort_field,
            "sortOrder": "asc",
        },
        "data_selector": "data",
        "data_selector_required": True,
        "paginator": {"type": "cursor", "cursor_path": "nextCursor", "cursor_param": "cursor"},
    }


def get_resource(config: SimSourceConfig, name: str) -> EndpointResource:
    return {
        "name": name,
        "table_format": "delta",
        "write_disposition": "replace",
        "endpoint": get_endpoint(config, name),
    }


def validate_credentials(
    config: SimSourceConfig, api_version: str, schema_name: str | None = None
) -> tuple[bool, str | None]:
    endpoint = get_endpoint(config, schema_name or "workflows", page_size=1)
    client_settings = client_config(config, api_version)
    client = RESTClient(
        base_url=client_settings["base_url"],
        auth=create_auth(client_settings["auth"]),
        headers=client_settings["headers"],
        request_timeout=client_settings["request_timeout"],
        allowed_hosts=[],
        allow_redirects=False,
    )
    try:
        next(
            client.paginate(
                path=cast(str, endpoint["path"]),
                params=endpoint["params"],
                data_selector="data",
                data_selector_required=True,
            )
        )
    except HTTPError as error:
        status = error.response.status_code if error.response is not None else None
        if status == 401:
            return False, AUTH_ERROR
        if status == 403:
            return (True, None) if schema_name is None else (False, PERMISSION_ERROR)
        if status == 404:
            return False, WORKSPACE_ERROR
        raise
    finally:
        client.session.close()
    return True, None


def sim_source(
    config: SimSourceConfig,
    inputs: SourceInputs,
    manager: ResumableSourceManager[SimResumeConfig],
    api_version: str,
) -> SourceResponse:
    endpoint = schema_for_resource(ENDPOINTS, inputs.schema_name)
    resource_config: RESTAPIConfig = {
        "client": client_config(config, api_version),
        "resources": [get_resource(config, inputs.schema_name)],
    }
    initial_state: dict[str, Any] | None = None
    if manager.can_resume():
        resume = manager.load_state()
        if resume is not None:
            initial_state = {"cursor": resume.cursor}

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state and state.get("cursor"):
            manager.save_state(SimResumeConfig(cursor=str(state["cursor"])))

    resource = rest_api_resource(
        resource_config,
        inputs.team_id,
        inputs.job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_state,
    )
    return SourceResponse(
        name=inputs.schema_name,
        items=lambda: resource,
        primary_keys=[endpoint.primary_key],
        partition_keys=[endpoint.partition_key],
        partition_mode="datetime",
        partition_format="month",
        sort_mode="asc",
    )
