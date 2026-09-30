from typing import Any
from urllib.parse import urlsplit

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import _is_host_safe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.growthbook import (
    GrowthBookSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.growthbook.settings import (
    DEFAULT_BASE_URL,
    ENDPOINTS,
    PAGE_SIZE,
)

INVALID_URL = "Enter a GrowthBook API base URL using HTTPS, without credentials, query parameters, or a fragment."
UNSAFE_HOST = "The GrowthBook API host is not allowed. Use a publicly reachable host."


@frozen
class GrowthBookResumeConfig:
    next_offset: int


def client_config(config: GrowthBookSourceConfig, team_id: int) -> ClientConfig:
    base_url = ((config.base_url or "").strip() or DEFAULT_BASE_URL).rstrip("/")
    try:
        parsed = urlsplit(base_url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.port == 0
            or "\\" in base_url
            or "%" in parsed.netloc
            or any(character.isspace() for character in base_url)
        ):
            raise ValueError(INVALID_URL)
    except ValueError:
        raise ValueError(INVALID_URL) from None
    valid, _ = _is_host_safe(parsed.hostname, team_id)
    if not valid:
        raise ValueError(UNSAFE_HOST)
    return {
        "base_url": base_url,
        "auth": {"type": "bearer", "token": config.api_key},
        "headers": {"Accept": "application/json"},
        "allowed_hosts": [],
        "allow_redirects": False,
        "request_timeout": 30,
    }


def endpoint_config(name: str, api_version: str, *, probe: bool = False) -> Endpoint:
    endpoint = schema_for_resource(ENDPOINTS, name)
    return {
        "path": endpoint.path.format(api_version=api_version),
        "data_selector": endpoint.data_selector,
        "data_selector_required": True,
        "params": {**endpoint.params, "limit": 1 if probe else PAGE_SIZE, "offset": 0} if endpoint.paginated else {},
        "paginator": {"type": "cursor", "cursor_path": "nextOffset", "cursor_param": "offset"}
        if endpoint.paginated and not probe
        else "single_page",
    }


def probe_credentials(config: GrowthBookSourceConfig, team_id: int, schema_name: str, api_version: str) -> None:
    client = client_config(config, team_id)
    client["max_retries"] = 1
    resource = rest_api_resource(
        {
            "client": client,
            "resources": [{"name": schema_name, "endpoint": endpoint_config(schema_name, api_version, probe=True)}],
        },
        team_id,
        "growthbook-credential-validation",
        None,
    )
    list(resource)


def growthbook_source(
    config: GrowthBookSourceConfig,
    inputs: SourceInputs,
    resumable_source_manager: ResumableSourceManager[GrowthBookResumeConfig],
    api_version: str,
) -> SourceResponse:
    endpoint = schema_for_resource(ENDPOINTS, inputs.schema_name)
    rest_config: RESTAPIConfig = {
        "client": client_config(config, inputs.team_id),
        "resources": [
            {
                "name": inputs.schema_name,
                "endpoint": endpoint_config(inputs.schema_name, api_version),
                "write_disposition": "replace",
            }
        ],
    }
    initial_state: dict[str, Any] | None = None
    if endpoint.paginated and resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_state = {"cursor": resume.next_offset}

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state is not None:
            resumable_source_manager.save_state(GrowthBookResumeConfig(next_offset=int(state["cursor"])))

    resource = rest_api_resource(
        rest_config,
        inputs.team_id,
        inputs.job_id,
        None,
        resume_hook=save_checkpoint if endpoint.paginated else None,
        initial_paginator_state=initial_state,
    )
    return SourceResponse(
        name=inputs.schema_name,
        items=lambda: resource,
        primary_keys=list(endpoint.primary_keys),
        partition_keys=[endpoint.partition_key] if endpoint.partition_key else None,
        partition_mode="datetime" if endpoint.partition_key else None,
        partition_format="month" if endpoint.partition_key else None,
        partition_size=1 if endpoint.partition_key else None,
        sort_mode=None,
        supports_resume=endpoint.paginated,
    )
