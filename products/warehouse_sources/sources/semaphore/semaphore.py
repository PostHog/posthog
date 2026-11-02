import re
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID

from requests.exceptions import HTTPError

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.datetime_utils import parse_datetime_value
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import APIKeyAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.semaphore import (
    SemaphoreSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.semaphore.settings import (
    AUTH_ERROR,
    ENDPOINTS,
    NOT_FOUND_ERROR,
    PERMISSION_ERROR,
)


@frozen
class SemaphoreResumeConfig:
    next_url: str | None = None
    completed: bool = False


def client_config(config: SemaphoreSourceConfig, api_version: str) -> ClientConfig:
    if not re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?", config.organization):
        raise ValueError("Enter the Semaphore organization subdomain, such as 'example', without a URL.")
    try:
        UUID(config.project_id)
    except ValueError:
        raise ValueError("Enter a valid Semaphore project ID (UUID).") from None
    return {
        "base_url": f"https://{config.organization}.semaphoreci.com/api/{api_version}/",
        "auth": APIKeyAuth(api_key=f"Token {config.api_token}", name="Authorization", location="header"),
        "headers": {"User-Agent": "SemaphoreCI v2.0 Client"},
        "paginator": "header_link",
        "allowed_hosts": [],
        "allow_redirects": False,
        "request_timeout": (10, 60),
    }


def validate_credentials(config: SemaphoreSourceConfig, api_version: str) -> tuple[bool, str | None]:
    settings = client_config(config, api_version)
    client = RESTClient(
        base_url=settings["base_url"],
        auth=APIKeyAuth(api_key=f"Token {config.api_token}"),
        headers=settings["headers"],
        allowed_hosts=[],
        allow_redirects=False,
        request_timeout=(10, 30),
    )
    try:
        next(
            client.paginate(
                "plumber-workflows",
                params={"project_id": config.project_id},
                paginator=SinglePagePaginator(),
                data_selector_required=True,
            )
        )
    except HTTPError as error:
        status = error.response.status_code if error.response is not None else None
        if status in (401, 403, 404):
            return False, {401: AUTH_ERROR, 403: PERMISSION_ERROR, 404: NOT_FOUND_ERROR}[status]
        raise
    return True, None


def normalize_created_at(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("created_at")
    if isinstance(value, dict):
        row["created_at"] = datetime.fromtimestamp(int(value["seconds"]), UTC) + timedelta(
            microseconds=int(value.get("nanos", 0)) // 1000
        )
    elif value is not None:
        parsed = parse_datetime_value(value)
        if parsed is None:
            raise ValueError("Semaphore returned an invalid creation time.")
        row["created_at"] = parsed
    return row


def semaphore_source(
    config: SemaphoreSourceConfig,
    inputs: SourceInputs,
    manager: ResumableSourceManager[SemaphoreResumeConfig],
    api_version: str,
) -> SourceResponse:
    endpoint = schema_for_resource(ENDPOINTS, inputs.schema_name)
    client = client_config(config, api_version)
    resume = manager.load_state() if manager.can_resume() else None
    if resume is not None and resume.completed:
        return SourceResponse(
            name=inputs.schema_name, items=list, primary_keys=[endpoint.primary_key], sort_mode="desc"
        )

    params: dict[str, Any] = {"project_id": config.project_id}
    incremental = inputs.schema_name == "workflows" and inputs.should_use_incremental_field
    if incremental and inputs.db_incremental_field_last_value is not None:
        watermark = parse_datetime_value(inputs.db_incremental_field_last_value)
        if watermark is None:
            raise ValueError("The Semaphore workflow sync position is invalid. Reset this table and try again.")
        # The API uses exclusive whole seconds; overlap one second to preserve records at the boundary.
        params["created_after"] = int(watermark.timestamp()) - 1

    endpoint_config: Endpoint = cast(
        Endpoint, {"path": endpoint.path, "params": params, "data_selector_required": True}
    )
    resource_config: EndpointResource = {
        "name": inputs.schema_name,
        "endpoint": endpoint_config,
        "data_map": normalize_created_at,
    }
    rest_config: RESTAPIConfig = {"client": client, "resources": [resource_config]}

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        manager.save_state(
            SemaphoreResumeConfig(next_url=state["next_url"]) if state else SemaphoreResumeConfig(completed=True)
        )

    resource = rest_api_resource(
        rest_config,
        inputs.team_id,
        inputs.job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state={"next_url": resume.next_url} if resume and resume.next_url else None,
    )
    return SourceResponse(
        name=inputs.schema_name,
        items=lambda: resource,
        primary_keys=[endpoint.primary_key],
        sort_mode="desc",
    )
