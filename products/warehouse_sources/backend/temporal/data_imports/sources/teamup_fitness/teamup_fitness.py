from typing import Any

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    Endpoint,
    EndpointResource,
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.teamupfitness import (
    TeamupFitnessSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.teamup_fitness.settings import ENDPOINTS


@frozen
class TeamupFitnessResumeConfig:
    next_url: str


def build_config(
    config: TeamupFitnessSourceConfig, endpoint: str, api_version: str, *, validation: bool = False
) -> RESTAPIConfig:
    settings = schema_for_resource(ENDPOINTS, endpoint)
    params: dict[str, Any] = {"page_size": 1 if validation else 100}
    if settings.sort:
        params["sort"] = settings.sort

    endpoint_config: Endpoint = {
        "path": settings.path,
        "params": params,
        "data_selector": "results",
        "data_selector_required": True,
    }
    resource: EndpointResource = {
        "name": endpoint,
        "table_name": endpoint,
        "primary_key": settings.primary_key,
        "write_disposition": "replace",
        "table_format": "delta",
        "endpoint": endpoint_config,
    }
    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": f"https://goteamup.com/api/{api_version}/",
            "auth": {"type": "bearer", "token": config.m2m_token},
            "headers": {
                "Accept": "application/json",
                "TeamUp-Request-Mode": "provider",
                "TeamUp-Provider-ID": config.provider_id,
            },
            "paginator": "single_page" if validation else {"type": "json_response", "next_url_path": "next"},
            "allowed_hosts": [],
            "allow_redirects": False,
            "request_timeout": 60,
        },
        "resources": [resource],
    }
    return rest_config


def validate_credentials(config: TeamupFitnessSourceConfig, team_id: int, api_version: str) -> None:
    resource = rest_api_resource(build_config(config, "customers", api_version, validation=True), team_id, "", None)
    next(iter(resource), None)


def teamup_fitness_source(
    config: TeamupFitnessSourceConfig,
    inputs: SourceInputs,
    manager: ResumableSourceManager[TeamupFitnessResumeConfig],
    api_version: str,
) -> SourceResponse:
    endpoint = schema_for_resource(ENDPOINTS, inputs.schema_name)
    resume = manager.load_state() if manager.can_resume() else None

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state and state.get("next_url"):
            manager.save_state(TeamupFitnessResumeConfig(next_url=str(state["next_url"])))

    resource = rest_api_resource(
        build_config(config, inputs.schema_name, api_version),
        inputs.team_id,
        inputs.job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state={"next_url": resume.next_url} if resume else None,
    )
    return SourceResponse(
        name=inputs.schema_name,
        items=lambda: resource,
        primary_keys=[endpoint.primary_key],
        partition_keys=[endpoint.partition_key] if endpoint.partition_key else None,
        partition_mode="datetime" if endpoint.partition_key else None,
        partition_format="month" if endpoint.partition_key else None,
        sort_mode=None,
    )
