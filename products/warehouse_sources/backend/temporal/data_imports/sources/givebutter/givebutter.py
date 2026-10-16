from typing import TYPE_CHECKING, Any

from requests.exceptions import HTTPError

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import BearerTokenAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.givebutter.settings import (
    BASE_URL,
    ENDPOINTS,
    REQUEST_TIMEOUT_SECONDS,
)

if TYPE_CHECKING:
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs

AUTH_ERROR = "Your Givebutter API key is invalid or expired. Generate a new API key and reconnect."
PERMISSION_ERROR = "Your Givebutter API key cannot access this table. Check the key's permissions in Givebutter."


@frozen
class GivebutterResumeConfig:
    paginator_state: dict[str, Any] | None = None
    finished: bool = False


def get_resource(name: str) -> EndpointResource:
    endpoint = schema_for_resource(ENDPOINTS, name)
    params: dict[str, Any] = {"per_page": endpoint.page_size} if endpoint.page_size else {}
    if endpoint.parent:
        params["parent_id"] = {"type": "resolve", "resource": endpoint.parent, "field": "id"}
    resource: EndpointResource = {
        "name": name,
        "endpoint": {
            "path": endpoint.path,
            "params": params,
            "data_selector": endpoint.data_selector,
            "data_selector_required": True,
            "paginator": endpoint.paginator,
        },
    }
    if endpoint.parent:
        resource["include_from_parent"] = ["id"]
    return resource


def validate_credentials(api_key: str, schema_name: str | None) -> tuple[bool, str | None]:
    endpoint = schema_for_resource(ENDPOINTS, schema_name or "campaigns")
    client = RESTClient(
        base_url=BASE_URL,
        auth=BearerTokenAuth(token=api_key),
        headers={"Accept": "application/json"},
        allowed_hosts=["api.givebutter.com"],
        allow_redirects=False,
        request_timeout=REQUEST_TIMEOUT_SECONDS,
    )
    try:
        path = endpoint.path
        if endpoint.parent:
            parents = next(
                client.paginate(
                    path=ENDPOINTS[endpoint.parent].path,
                    params={"per_page": 1},
                    paginator=SinglePagePaginator(),
                    data_selector="data",
                    data_selector_required=True,
                )
            )
            if not parents:
                return True, None
            path = path.format(parent_id=parents[0]["id"])
        next(
            client.paginate(
                path=path,
                params={"per_page": 1} if endpoint.page_size else {"page": 1},
                paginator=SinglePagePaginator(),
                data_selector=endpoint.data_selector,
                data_selector_required=True,
            )
        )
    except HTTPError as error:
        status = error.response.status_code if error.response is not None else None
        if status == 401:
            return False, AUTH_ERROR
        if status == 403:
            return (True, None) if schema_name is None else (False, PERMISSION_ERROR)
        raise
    finally:
        client.session.close()
    return True, None


def givebutter_source(
    api_key: str,
    inputs: "SourceInputs",
    manager: "ResumableSourceManager[GivebutterResumeConfig]",
) -> SourceResponse:
    name = inputs.schema_name
    endpoint = schema_for_resource(ENDPOINTS, name)
    resume = manager.load_state() if manager.can_resume() else None

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        manager.save_state(GivebutterResumeConfig(paginator_state=state, finished=state is None))

    resources: list[str | EndpointResource] = [get_resource(name)]
    if endpoint.parent:
        resources.insert(0, get_resource(endpoint.parent))
    config: RESTAPIConfig = {
        "client": {
            "base_url": BASE_URL,
            "auth": {"type": "bearer", "token": api_key},
            "headers": {"Accept": "application/json"},
            "allowed_hosts": ["api.givebutter.com"],
            "allow_redirects": False,
            "request_timeout": REQUEST_TIMEOUT_SECONDS,
            "paginator": {"type": "json_response", "next_url_path": "links.next"},
        },
        "resource_defaults": {"write_disposition": "replace"},
        "resources": resources,
    }
    resource: Resource | list[dict[str, Any]]
    if resume and resume.finished:
        resource = []
    elif endpoint.parent:
        resource = next(
            resource
            for resource in rest_api_resources(
                config,
                inputs.team_id,
                inputs.job_id,
                None,
                resume_hook=save_checkpoint,
                initial_paginator_state=resume.paginator_state if resume else None,
            )
            if resource.name == name
        )
    else:
        resource = rest_api_resource(
            config,
            inputs.team_id,
            inputs.job_id,
            None,
            resume_hook=save_checkpoint,
            initial_paginator_state=resume.paginator_state if resume else None,
        )
    return SourceResponse(
        name=name,
        items=lambda: resource,
        primary_keys=list(endpoint.primary_keys),
        partition_keys=[endpoint.partition_key] if endpoint.partition_key else None,
        partition_mode="datetime" if endpoint.partition_key else None,
        partition_format="month" if endpoint.partition_key else None,
        sort_mode=None,
    )
