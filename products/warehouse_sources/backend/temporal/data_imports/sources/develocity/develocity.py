from typing import Any
from urllib.parse import urlsplit

from requests import HTTPError

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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.develocity.settings import (
    ENDPOINTS,
    INVALID_KEY,
    INVALID_URL,
    MISSING_PERMISSION,
    PAGE_SIZE,
    PRIMARY_KEYS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.develocity import (
    DevelocitySourceConfig,
)


@frozen
class DevelocityResumeConfig:
    cursor: str


def validated_api_url(instance_url: str, team_id: int) -> str:
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import (  # noqa: PLC0415 -- avoids loading Django models during source discovery
        ValidateDatabaseHostMixin,
    )

    try:
        parts = urlsplit(instance_url)
        if (
            parts.scheme != "https"
            or not parts.hostname
            or parts.username is not None
            or parts.password is not None
            or parts.path not in ("", "/")
            or parts.query
            or parts.fragment
            or parts.port == 0
            or any(character.isspace() for character in instance_url)
            or "\\" in instance_url
        ):
            raise ValueError(INVALID_URL)
    except ValueError:
        raise ValueError(INVALID_URL) from None

    valid, error = ValidateDatabaseHostMixin().is_database_host_valid(parts.hostname, team_id)
    if not valid:
        raise ValueError(error or "The Develocity host is not publicly reachable. Check the instance URL.")
    return f"https://{parts.netloc}/api/"


def get_resource(name: str, incremental: bool, last_value: int | str | None) -> EndpointResource:
    endpoint = schema_for_resource(ENDPOINTS, name)
    # The API excludes the starting instant. Re-read one millisecond to retain builds with equal timestamps.
    start = max(0, int(last_value) - 1) if incremental and last_value is not None else 0
    params: dict[str, Any] = {
        "fromInstant": start,
        "reverse": "false",
        "maxBuilds": PAGE_SIZE,
        "maxWaitSecs": 1,
    }
    if endpoint.build_tool:
        params["query"] = f"buildTool:{endpoint.build_tool}"
        params["models"] = list(endpoint.models)

    return {
        "name": name,
        "endpoint": {
            "path": "builds",
            "params": params,
            "data_selector": "$",
            "data_selector_required": True,
            "paginator": {
                "type": "cursor",
                "cursor_path": "$[-1].id",
                "cursor_param": "fromBuild",
                "raise_on_repeated_cursor": True,
            },
        },
    }


def validate_credentials(
    config: DevelocitySourceConfig, team_id: int, schema_name: str | None = None
) -> tuple[bool, str | None]:
    try:
        base_url = validated_api_url(config.instance_url, team_id)
    except ValueError as error:
        return False, str(error)

    if schema_name is not None:
        schema_for_resource(ENDPOINTS, schema_name)

    client = RESTClient(
        base_url=base_url,
        auth=BearerTokenAuth(config.access_key),
        allowed_hosts=[],
        allow_redirects=False,
        request_timeout=30,
        max_retry_attempts=1,
    )
    try:
        next(
            client.paginate(
                path="builds",
                params={"maxBuilds": 1, "maxWaitSecs": 1, "reverse": "true"},
                paginator=SinglePagePaginator(),
                data_selector="$",
                data_selector_required=True,
            )
        )
    except HTTPError as error:
        status = error.response.status_code if error.response is not None else None
        if status == 401:
            return False, INVALID_KEY
        if status == 403:
            return (True, None) if schema_name is None else (False, MISSING_PERMISSION)
        raise
    return True, None


def develocity_source(
    config: DevelocitySourceConfig,
    inputs: SourceInputs,
    manager: ResumableSourceManager[DevelocityResumeConfig],
) -> SourceResponse:
    resource_config = get_resource(
        inputs.schema_name, inputs.should_use_incremental_field, inputs.db_incremental_field_last_value
    )
    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": validated_api_url(config.instance_url, inputs.team_id),
            "auth": {"type": "bearer", "token": config.access_key},
            "allowed_hosts": [],
            "allow_redirects": False,
            "request_timeout": 60,
        },
        "resources": [resource_config],
    }
    saved = manager.load_state() if manager.can_resume() else None

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state and state.get("cursor"):
            manager.save_state(DevelocityResumeConfig(cursor=str(state["cursor"])))

    resource = rest_api_resource(
        rest_config,
        inputs.team_id,
        inputs.job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state={"cursor": saved.cursor} if saved else None,
    )
    return SourceResponse(
        name=inputs.schema_name,
        items=lambda: resource,
        primary_keys=PRIMARY_KEYS,
        sort_mode="asc",
    )
