import re
from datetime import datetime
from typing import Any

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import BearerTokenAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.scalr import ScalrSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.scalr.settings import ENDPOINTS

HEADERS = {"Accept": "application/vnd.api+json", "Content-Type": "application/vnd.api+json"}


@frozen
class ScalrResumeConfig:
    next_page: str


def base_url(config: ScalrSourceConfig, team_id: int, api_version: str) -> str:
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import (  # noqa: PLC0415 -- Keep Django models off the source registration path.
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


def scalr_source(
    config: ScalrSourceConfig,
    manager: ResumableSourceManager[ScalrResumeConfig],
    inputs: SourceInputs,
    api_version: str,
) -> SourceResponse:
    endpoint = ENDPOINTS[inputs.schema_name]
    params: dict[str, Any] = {"filter[account]": config.account_id, "page[size]": 50, "page[number]": 1}
    if endpoint.sort:
        params["sort"] = endpoint.sort
    if inputs.should_use_incremental_field:
        if inputs.schema_name != "workspaces" or inputs.incremental_field != "updated_at":
            raise ValueError("Scalr supports incremental sync only for the workspace updated_at field.")
        watermark = inputs.db_incremental_field_last_value
        if watermark is not None:
            value = watermark.isoformat() if isinstance(watermark, datetime) else str(watermark)
            params["filter[updated-at]"] = f"gte:{value}"

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": base_url(config, inputs.team_id, api_version),
            "auth": {"type": "bearer", "token": config.api_token},
            "headers": HEADERS,
            "allowed_hosts": [],
            "allow_redirects": False,
            "request_timeout": 30,
            "paginator": {
                "type": "cursor",
                "cursor_path": "meta.pagination.next-page",
                "cursor_param": "page[number]",
                "raise_on_repeated_cursor": True,
            },
        },
        "resources": [
            {
                "name": inputs.schema_name,
                "table_format": "delta",
                "write_disposition": "merge" if inputs.should_use_incremental_field else "replace",
                "primary_key": list(endpoint.primary_keys),
                "data_map": flatten_resource,
                "columns": {"created_at": {"data_type": "timestamp"}, "updated_at": {"data_type": "timestamp"}},
                "endpoint": {
                    "path": endpoint.path,
                    "params": params,
                    "data_selector": "data",
                    "data_selector_required": True,
                    "data_selector_empty_ok": True,
                },
            }
        ],
    }
    resume = manager.load_state() if manager.can_resume() else None

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state and state.get("cursor") is not None:
            manager.save_state(ScalrResumeConfig(next_page=str(state["cursor"])))

    resource = rest_api_resource(
        rest_config,
        inputs.team_id,
        inputs.job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state={"cursor": resume.next_page} if resume else None,
    )
    return SourceResponse(
        name=inputs.schema_name,
        items=lambda: resource,
        primary_keys=list(endpoint.primary_keys),
        column_hints=resource.column_hints,
        partition_keys=[endpoint.partition_key],
        partition_mode="datetime",
        partition_format="month",
        sort_mode="asc" if endpoint.sort else "desc",
    )
