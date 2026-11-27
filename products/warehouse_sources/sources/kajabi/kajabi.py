import functools
from dataclasses import replace
from typing import Any, cast
from urllib.parse import quote

from products.warehouse_sources.sources.kajabi._config import KajabiSourceConfig
from products.warehouse_sources.sources.kajabi.settings import BASE_URL, ENDPOINTS, KajabiEndpoint
from products.warehouse_sources.sources.sdk import (
    ClientConfig,
    OAuth2Auth,
    PageNumberPaginator,
    Resource,
    RESTAPIConfig,
    ResumableSourceManager,
    SourceInputs,
    SourceResponse,
    build_dependent_resource,
    flatten_jsonapi,
    frozen,
    make_tracked_session,
    rest_api_resource,
    schema_for_resource,
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


def list_params(config: KajabiSourceConfig, endpoint: KajabiEndpoint) -> dict[str, Any]:
    params: dict[str, Any] = {"filter[site_id]": config.site_id}
    if endpoint.page_size_param is not None:
        params[endpoint.page_size_param] = endpoint.page_size
    if endpoint.sort_field is not None:
        params["sort"] = endpoint.sort_field
    return params


def probe_params(config: KajabiSourceConfig, endpoint: KajabiEndpoint) -> dict[str, Any]:
    params = {**list_params(config, endpoint), "page[number]": 1}
    if endpoint.page_size_param is not None:
        params[endpoint.page_size_param] = 1
    return params


def probe_credentials(config: KajabiSourceConfig, schema_name: str | None) -> int:
    auth = kajabi_auth(config)
    with make_tracked_session(redact_values=auth.secret_values(), capture=False) as session:
        if schema_name is None:
            return session.get(f"{BASE_URL}/me", auth=auth, timeout=(10, 30), allow_redirects=False).status_code

        endpoint = schema_for_resource(ENDPOINTS, schema_name)
        if endpoint.fanout is not None:
            parent = ENDPOINTS[endpoint.fanout.parent_name]
            response = session.get(
                f"{BASE_URL}/{parent.path}",
                params=probe_params(config, parent),
                auth=auth,
                timeout=(10, 30),
                allow_redirects=False,
            )
            if response.status_code != 200:
                return response.status_code
            parents = response.json()["data"]
            if not parents:
                return 200
            path = endpoint.path.format(**{endpoint.fanout.resolve_param: quote(str(parents[0]["id"]), safe="")})
            params: dict[str, Any] = {}
        else:
            path = endpoint.path
            params = probe_params(config, endpoint)
        return session.get(
            f"{BASE_URL}/{path}", params=params, auth=auth, timeout=(10, 30), allow_redirects=False
        ).status_code


def encode_path_id(row: dict[str, Any]) -> dict[str, Any]:
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
        "paginator": PageNumberPaginator(base_page=1, page_param="page[number]", total_path=endpoint.total_pages_path),
    }
    resume = manager.load_state() if manager.can_resume() else None

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state is not None:
            manager.save_state(KajabiResumeConfig(paginator_state=state))

    resource: Resource
    if endpoint.fanout is not None:
        fanout = replace(
            endpoint.fanout,
            parent_params=list_params(config, ENDPOINTS[endpoint.fanout.parent_name]),
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
                parent_data_map=encode_path_id,
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
                        "params": list_params(config, endpoint),
                        "data_selector": "data",
                        "data_selector_required": True,
                    },
                    "write_disposition": "replace",
                    "table_format": "delta",
                    "data_map": functools.partial(flatten_jsonapi, relationships_as_ids=False),
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
