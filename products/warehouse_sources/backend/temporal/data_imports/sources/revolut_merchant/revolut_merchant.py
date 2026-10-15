from typing import Any
from urllib.parse import quote

from requests import HTTPError

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    RESTClient,
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import BearerTokenAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    rename_parent_fields,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.revolut_merchant.settings import (
    BASE_URLS,
    ENDPOINTS,
)

AUTH_ERROR = (
    "Revolut Merchant rejected the Secret API key. Check that it is valid and matches the selected environment."
)
PERMISSION_ERROR = (
    "Your Secret API key cannot access this Revolut Merchant table. Check your Merchant account permissions."
)
VERSION_ERROR = "Revolut Merchant rejected the request. Check the selected API version and reconnect."


@frozen
class RevolutMerchantResumeConfig:
    paginator_state: dict[str, Any]


def client_config(api_key: str, environment: str, api_version: str) -> ClientConfig:
    if environment not in BASE_URLS:
        raise ValueError("Select Production or Sandbox for the Revolut Merchant environment.")
    return {
        "base_url": BASE_URLS[environment],
        "auth": {"type": "bearer", "token": api_key},
        "headers": {"Revolut-Api-Version": api_version, "Accept": "application/json"},
        "allowed_hosts": [],
        "allow_redirects": False,
        "request_timeout": 30,
    }


def get_resource(name: str) -> EndpointResource:
    endpoint = schema_for_resource(ENDPOINTS, name)
    resource: EndpointResource = {
        "name": name,
        "table_name": name,
        "table_format": "delta",
        "write_disposition": "replace",
        "endpoint": endpoint.endpoint,
    }
    if endpoint.parent:
        resource["include_from_parent"] = ["id"]
        resource["data_map"] = rename_parent_fields(endpoint.parent, {"id": "order_id"})
    return resource


def revolut_merchant_source(
    api_key: str,
    environment: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    api_version: str,
    resumable_source_manager: ResumableSourceManager[RevolutMerchantResumeConfig],
) -> SourceResponse:
    endpoint_config = schema_for_resource(ENDPOINTS, endpoint)
    resources: list[str | EndpointResource] = [get_resource(endpoint)]
    if endpoint_config.parent:
        resources.insert(0, get_resource(endpoint_config.parent))
    config: RESTAPIConfig = {
        "client": client_config(api_key, environment, api_version),
        "resources": resources,
    }

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state is not None:
            resumable_source_manager.save_state(RevolutMerchantResumeConfig(paginator_state=state))

    if endpoint_config.parent:
        resource = rest_api_resources(
            config,
            team_id,
            job_id,
            None,
            resume_hook=save_checkpoint,
            initial_paginator_state=resume.paginator_state if resume else None,
        )[-1]
    else:
        resource = rest_api_resource(
            config,
            team_id,
            job_id,
            None,
            resume_hook=save_checkpoint,
            initial_paginator_state=resume.paginator_state if resume else None,
        )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=endpoint_config.primary_keys,
        column_hints=resource.column_hints,
        partition_mode="datetime",
        partition_keys=[endpoint_config.partition_key],
        partition_format="month",
        sort_mode=endpoint_config.sort_mode,
    )


def validate_credentials(
    api_key: str, environment: str, api_version: str, schema_name: str | None = None
) -> tuple[bool, str | None]:
    if not api_key or any(not 33 <= ord(char) <= 126 for char in api_key):
        return False, "Enter a Revolut Merchant Secret API key without spaces or unsupported characters."
    selected_endpoint = schema_for_resource(ENDPOINTS, schema_name or "customers")
    endpoint = ENDPOINTS[selected_endpoint.parent] if selected_endpoint.parent else selected_endpoint
    path = endpoint.endpoint.get("path")
    if path is None:
        raise ValueError("Revolut Merchant endpoint is missing a path.")
    config = client_config(api_key, environment, api_version)
    client = RESTClient(
        base_url=config["base_url"],
        auth=BearerTokenAuth(api_key),
        headers=config["headers"],
        allowed_hosts=[],
        allow_redirects=False,
        request_timeout=15,
    )
    try:
        page = next(
            client.paginate(
                path=path,
                params={"limit": 1},
                paginator=SinglePagePaginator(),
                data_selector=endpoint.endpoint["data_selector"],
                data_selector_required=True,
            )
        )
        if selected_endpoint.parent and page:
            next(
                client.paginate(
                    path=f"/orders/{quote(str(page[0]['id']), safe='')}/payments",
                    paginator=SinglePagePaginator(),
                    data_selector_required=True,
                )
            )
    except HTTPError as error:
        status = error.response.status_code if error.response is not None else None
        if status == 401:
            return False, AUTH_ERROR
        if status == 403:
            return (True, None) if schema_name is None else (False, PERMISSION_ERROR)
        if status == 400:
            return False, VERSION_ERROR
        raise
    return True, None
