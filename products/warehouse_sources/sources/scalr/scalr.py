import re
from datetime import datetime
from typing import Any

from products.warehouse_sources.sources.scalr._config import ScalrSourceConfig
from products.warehouse_sources.sources.scalr.settings import ENDPOINTS, ScalrEndpoint
from products.warehouse_sources.sources.sdk import (
    BearerTokenAuth,
    Endpoint,
    EndpointResource,
    JSONResponseCursorPaginatorConfig,
    RESTAPIConfig,
    RESTClient,
    ResumableSourceManager,
    SinglePagePaginator,
    SourceInputs,
    SourceResponse,
    frozen,
    rest_api_resource,
    rest_api_resources,
)

HEADERS = {"Accept": "application/vnd.api+json", "Content-Type": "application/vnd.api+json"}
PAGINATOR: JSONResponseCursorPaginatorConfig = {
    "type": "cursor",
    "cursor_path": "meta.pagination.next-page",
    "cursor_param": "page[number]",
    "raise_on_repeated_cursor": True,
}


@frozen
class ScalrResumeConfig:
    next_page: str | None = None
    fan_out: dict[str, Any] | None = None


def base_url(config: ScalrSourceConfig, team_id: int, api_version: str) -> str:
    from products.warehouse_sources.sources.sdk import (  # noqa: PLC0415 -- Keep Django models off the source registration path.
        ValidateDatabaseHostMixin,
    )

    if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", config.host):
        raise ValueError("Enter the Scalr hostname without a scheme, port, or path. Connections use HTTPS.")
    valid, error = ValidateDatabaseHostMixin().is_database_host_valid(config.host, team_id)
    if not valid:
        raise ValueError(error or "Enter a public Scalr hostname.")
    return f"https://{config.host}/api/iacp/{api_version}/"


def validate_credentials(config: ScalrSourceConfig, team_id: int, api_version: str) -> None:
    client = RESTClient(
        base_url=base_url(config, team_id, api_version),
        auth=BearerTokenAuth(token=config.api_token),
        headers=HEADERS,
        allowed_hosts=[],
        allow_redirects=False,
        request_timeout=30,
    )
    list(
        client.paginate(
            "environments",
            params={"filter[account]": config.account_id, "page[size]": 1},
            paginator=SinglePagePaginator(),
            data_selector="data",
            data_selector_required=True,
            data_selector_empty_ok=True,
        )
    )


def flatten_resource(row: dict[str, Any]) -> dict[str, Any]:
    if not row.get("id") or not row.get("type"):
        raise ValueError("Scalr returned a resource without an ID or type.")
    result = {
        **{key.replace("-", "_"): value for key, value in row.get("attributes", {}).items()},
        "id": row["id"],
        "type": row["type"],
        "relationships": row.get("relationships", {}),
    }
    for key in ("created_at", "updated_at"):
        if isinstance(result.get(key), str):
            result[key] = datetime.fromisoformat(result[key])
    return result


def flatten_state_version(row: dict[str, Any]) -> dict[str, Any]:
    # The base64 state file can hold provider credentials and secret resource attributes.
    result = flatten_resource(row)
    result.pop("state", None)
    outputs = result.get("outputs")
    if isinstance(outputs, list):
        result["outputs"] = [
            {**output, "value": None} if isinstance(output, dict) and output.get("sensitive") else output
            for output in outputs
        ]
    return result


def included_plans(body: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(body.get("data"), list):
        raise ValueError("Scalr returned a run list without a data array.")
    return [flatten_resource(item) for item in body.get("included") or [] if item.get("type") == "plans"]


def _list_params(endpoint: ScalrEndpoint, account_id: str) -> dict[str, Any]:
    params: dict[str, Any] = {"page[size]": 50, "page[number]": 1}
    if endpoint.account_filter:
        params["filter[account]"] = account_id
    if endpoint.sort:
        params["sort"] = endpoint.sort
    if endpoint.include:
        params["include"] = endpoint.include
    return params


def _resource(
    name: str, endpoint: ScalrEndpoint, params: dict[str, Any], should_use_incremental_field: bool
) -> EndpointResource:
    endpoint_config: Endpoint = {"path": endpoint.path, "params": params}
    resource: EndpointResource = {
        "name": name,
        "table_format": "delta",
        "write_disposition": "merge" if should_use_incremental_field else "replace",
        "primary_key": list(endpoint.primary_keys),
        "columns": {"created_at": {"data_type": "timestamp"}, "updated_at": {"data_type": "timestamp"}},
        "endpoint": endpoint_config,
    }
    if endpoint.include:
        # The whole body goes to the map, because the rows sit in `included`, beside `data`.
        resource["data_map"] = included_plans
    else:
        endpoint_config.update(
            {"data_selector": "data", "data_selector_required": True, "data_selector_empty_ok": True}
        )
        resource["data_map"] = flatten_state_version if endpoint.per_workspace else flatten_resource
    if endpoint.per_workspace:
        endpoint_config["path"] = f"{endpoint.path}?filter[workspace]={{workspace_id}}"
        params["workspace_id"] = {"type": "resolve", "resource": "workspaces", "field": "id"}
        # Without an explicit paginator, a fan-out child reads only its first page.
        endpoint_config["paginator"] = PAGINATOR
        # A workspace deleted after the parent page was read returns 404.
        endpoint_config["response_actions"] = [{"status_code": 404, "action": "ignore"}]
    return resource


def scalr_source(
    config: ScalrSourceConfig,
    manager: ResumableSourceManager[ScalrResumeConfig],
    inputs: SourceInputs,
    api_version: str,
) -> SourceResponse:
    endpoint = ENDPOINTS[inputs.schema_name]
    params = _list_params(endpoint, config.account_id)
    if inputs.should_use_incremental_field:
        if inputs.schema_name != "workspaces" or inputs.incremental_field != "updated_at":
            raise ValueError("Scalr supports incremental sync only for the workspace updated_at field.")
        watermark = inputs.db_incremental_field_last_value
        if watermark is not None:
            value = watermark.isoformat() if isinstance(watermark, datetime) else str(watermark)
            params["filter[updated-at]"] = f"gte:{value}"

    resources: list[str | EndpointResource] = [
        _resource(inputs.schema_name, endpoint, params, inputs.should_use_incremental_field)
    ]
    if endpoint.per_workspace:
        resources.insert(
            0,
            {
                "name": "workspaces",
                "endpoint": {
                    "path": ENDPOINTS["workspaces"].path,
                    "params": _list_params(ENDPOINTS["workspaces"], config.account_id),
                    "data_selector": "data",
                    "data_selector_required": True,
                    "data_selector_empty_ok": True,
                },
            },
        )

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": base_url(config, inputs.team_id, api_version),
            "auth": {"type": "bearer", "token": config.api_token},
            "headers": HEADERS,
            "allowed_hosts": [],
            "allow_redirects": False,
            "request_timeout": 30,
            # A sampled response would keep the state file that flatten_state_version removes.
            "capture": not endpoint.per_workspace,
            "paginator": PAGINATOR,
        },
        "resources": resources,
    }

    resume = manager.load_state() if manager.can_resume() else None

    if endpoint.per_workspace:

        def save_fan_out(state: dict[str, Any] | None) -> None:
            if state:
                manager.save_state(ScalrResumeConfig(fan_out=state))

        resource = next(
            item
            for item in rest_api_resources(
                rest_config,
                inputs.team_id,
                inputs.job_id,
                None,
                resume_hook=save_fan_out,
                initial_paginator_state=resume.fan_out if resume else None,
            )
            if item.name == inputs.schema_name
        )
    else:

        def save_checkpoint(state: dict[str, Any] | None) -> None:
            if state and state.get("cursor") is not None:
                manager.save_state(ScalrResumeConfig(next_page=str(state["cursor"])))

        resource = rest_api_resource(
            rest_config,
            inputs.team_id,
            inputs.job_id,
            None,
            resume_hook=save_checkpoint,
            initial_paginator_state={"cursor": resume.next_page} if resume and resume.next_page else None,
        )
    return SourceResponse(
        name=inputs.schema_name,
        items=lambda: resource,
        primary_keys=list(endpoint.primary_keys),
        column_hints=resource.column_hints,
        partition_keys=[endpoint.partition_key] if endpoint.partition_key else None,
        partition_mode="datetime" if endpoint.partition_key else None,
        partition_format="month" if endpoint.partition_key else None,
        sort_mode=None if endpoint.per_workspace else "asc" if endpoint.sort else "desc",
    )
