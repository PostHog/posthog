from dataclasses import replace
from typing import Any, cast
from urllib.parse import quote

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import OAuth2Auth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ClientConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.kajabi import KajabiSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.kajabi.settings import (
    BASE_URL,
    ENDPOINTS,
    PAGE_SIZE,
)


@frozen
class KajabiResumeConfig:
    paginator_state: dict[str, Any]


def kajabi_auth(config: KajabiSourceConfig) -> OAuth2Auth:
    return OAuth2Auth(
        token_url=f"{BASE_URL}/oauth/token",
        client_id=config.client_id,
        client_secret=config.client_secret,
    )


def probe_credentials(config: KajabiSourceConfig, schema_name: str | None) -> int:
    auth = kajabi_auth(config)
    with make_tracked_session(redact_values=auth.secret_values(), capture=False) as session:
        if schema_name is None:
            return session.get(f"{BASE_URL}/me", auth=auth, timeout=(10, 30), allow_redirects=False).status_code

        endpoint = schema_for_resource(ENDPOINTS, schema_name)
        params: dict[str, Any] = {"filter[site_id]": config.site_id, "page[size]": 1, "page[number]": 1}
        if endpoint.fanout is not None:
            response = session.get(
                f"{BASE_URL}/contacts", params=params, auth=auth, timeout=(10, 30), allow_redirects=False
            )
            if response.status_code != 200:
                return response.status_code
            contacts = response.json()["data"]
            if not contacts:
                return 200
            path = endpoint.path.format(contact_id=quote(str(contacts[0]["id"]), safe=""))
            params = {}
        else:
            path = endpoint.path
        return session.get(
            f"{BASE_URL}/{path}", params=params, auth=auth, timeout=(10, 30), allow_redirects=False
        ).status_code


def flatten_resource(row: dict[str, Any]) -> dict[str, Any]:
    attributes = row.get("attributes") or {}
    return {**attributes, **{key: value for key, value in row.items() if key != "attributes"}}


def encode_contact_id(row: dict[str, Any]) -> dict[str, Any]:
    return {**row, "path_id": quote(str(row["id"]), safe="")}


def kajabi_source(
    config: KajabiSourceConfig,
    manager: ResumableSourceManager[KajabiResumeConfig],
    inputs: SourceInputs,
) -> SourceResponse:
    endpoint = schema_for_resource(ENDPOINTS, inputs.schema_name)
    client: ClientConfig = {
        "base_url": BASE_URL,
        "auth": kajabi_auth(config),
        "headers": {"Accept": "application/vnd.api+json"},
        "allowed_hosts": ["api.kajabi.com"],
        "allow_redirects": False,
        "request_timeout": (10, 30),
        "retry_budget_seconds": 240,
        "paginator": PageNumberPaginator(base_page=1, page_param="page[number]", total_path="meta.total_pages"),
    }
    resume = manager.load_state() if manager.can_resume() else None

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state is not None:
            manager.save_state(KajabiResumeConfig(paginator_state=state))

    params: dict[str, Any] = {"filter[site_id]": config.site_id, "page[size]": PAGE_SIZE}
    if endpoint.sort_field is not None:
        params["sort"] = endpoint.sort_field
    resource: Resource
    if endpoint.fanout is not None:
        fanout = replace(
            endpoint.fanout,
            parent_params=params,
        )
        resource = cast(
            Resource,
            build_dependent_resource(
                endpoint_configs=ENDPOINTS,
                child_endpoint=endpoint.name,
                fanout=fanout,
                client_config=client,
                path_format_values={},
                team_id=inputs.team_id,
                job_id=inputs.job_id,
                db_incremental_field_last_value=None,
                page_size_param=None,
                parent_endpoint_extra={"data_selector": "data", "data_selector_required": True},
                parent_data_map=encode_contact_id,
                child_endpoint_extra={
                    "data_selector": "data",
                    "data_selector_required": True,
                    "paginator": "single_page",
                },
                resume_hook=save_checkpoint,
                initial_paginator_state=resume.paginator_state if resume else None,
            ),
        )
    else:
        rest_config: RESTAPIConfig = {
            "client": client,
            "resources": [
                {
                    "name": endpoint.name,
                    "endpoint": {
                        "path": endpoint.path,
                        "params": params,
                        "data_selector": "data",
                        "data_selector_required": True,
                    },
                    "write_disposition": "replace",
                    "table_format": "delta",
                    "data_map": flatten_resource,
                }
            ],
        }
        resource = rest_api_resource(
            rest_config,
            inputs.team_id,
            inputs.job_id,
            None,
            resume_hook=save_checkpoint,
            initial_paginator_state=resume.paginator_state if resume else None,
        )

    return SourceResponse(
        name=endpoint.name,
        items=lambda: resource,
        primary_keys=list(endpoint.primary_keys),
        partition_keys=[endpoint.partition_key] if endpoint.partition_key else list(endpoint.primary_keys),
        partition_mode="datetime" if endpoint.partition_key else "md5",
        partition_format="month" if endpoint.partition_key else None,
        sort_mode=None,
    )
