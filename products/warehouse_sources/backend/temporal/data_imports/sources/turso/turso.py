import re
from collections.abc import Callable, Iterable
from typing import Any
from urllib.parse import quote

from requests.exceptions import HTTPError

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.turso import TursoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.turso.settings import BASE_URL, ENDPOINTS

INVALID_TOKEN_MESSAGE = "Your Turso API token is invalid or expired. Create a new Platform API token and reconnect."
PERMISSION_MESSAGE = (
    "Your Turso token cannot access this resource. Check its organization and permissions. "
    "Audit logs require the Scaler plan or higher."
)
ORGANIZATION_MESSAGE = "Enter your Turso organization slug using letters, numbers, and hyphens, without a URL."


@frozen
class TursoResumeConfig:
    paginator_state: dict[str, Any]


def validate_organization(organization: str) -> None:
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9-]*", organization):
        raise ValueError(ORGANIZATION_MESSAGE)


def _encode_database_name(row: dict[str, Any]) -> dict[str, Any]:
    return {**row, "encoded_name": quote(row["Name"], safe="")}


def get_resource(
    config: TursoSourceConfig,
    endpoint: str,
    team_id: int,
    job_id: str,
    resume_hook: Callable[[dict[str, Any] | None], None] | None = None,
    initial_paginator_state: dict[str, Any] | None = None,
) -> Iterable[list[dict[str, Any]]]:
    validate_organization(config.organization_slug)
    if endpoint not in ENDPOINTS:
        raise ValueError(f"Unknown Turso table: {endpoint}")
    settings = ENDPOINTS[endpoint]
    client: ClientConfig = {
        "base_url": BASE_URL,
        "auth": {"type": "bearer", "token": config.api_token},
        "paginator": "single_page",
    }
    endpoint_config: Endpoint = {
        "path": settings.path.replace("{organization}", config.organization_slug),
        "params": dict(settings.params),
        "data_selector": settings.data_selector,
        "data_selector_required": True,
        "paginator": settings.paginator,
    }
    if settings.fanout:
        parent = ENDPOINTS[settings.fanout.parent_name]
        return build_dependent_resource(
            endpoint_configs=ENDPOINTS,
            child_endpoint=endpoint,
            fanout=settings.fanout,
            client_config=client,
            path_format_values={"organization": config.organization_slug},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=None,
            page_size_param=None,
            parent_data_map=_encode_database_name,
            parent_endpoint_extra={"data_selector": parent.data_selector, "data_selector_required": True},
            child_endpoint_extra={"data_selector": settings.data_selector, "data_selector_required": True},
        )
    rest_config: RESTAPIConfig = {
        "client": client,
        "resources": [{"name": endpoint, "endpoint": endpoint_config, "write_disposition": "replace"}],
    }
    return rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=resume_hook,
        initial_paginator_state=initial_paginator_state,
    )


def validate_credentials(config: TursoSourceConfig, team_id: int, schema_name: str | None) -> tuple[bool, str | None]:
    try:
        validate_organization(config.organization_slug)
    except ValueError:
        return False, ORGANIZATION_MESSAGE
    try:
        next(iter(get_resource(config, schema_name or "databases", team_id, "credential-validation")), None)
    except HTTPError as error:
        status = error.response.status_code if error.response is not None else None
        if status == 401:
            return False, INVALID_TOKEN_MESSAGE
        if status == 403:
            return (True, None) if schema_name is None else (False, PERMISSION_MESSAGE)
        if status == 404:
            return False, "Turso could not find this resource. Check your organization slug and selected table."
        raise
    return True, None


def turso_source(
    config: TursoSourceConfig,
    inputs: SourceInputs,
    manager: ResumableSourceManager[TursoResumeConfig],
) -> SourceResponse:
    if inputs.schema_name not in ENDPOINTS:
        raise ValueError(f"Unknown Turso table: {inputs.schema_name}")
    settings = ENDPOINTS[inputs.schema_name]
    supports_resume = settings.paginator != "single_page"
    resume = manager.load_state() if supports_resume and manager.can_resume() else None

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state is not None:
            manager.save_state(TursoResumeConfig(paginator_state=state))

    return SourceResponse(
        name=inputs.schema_name,
        items=lambda: get_resource(
            config,
            inputs.schema_name,
            inputs.team_id,
            inputs.job_id,
            resume_hook=save_checkpoint if supports_resume else None,
            initial_paginator_state=resume.paginator_state if resume else None,
        ),
        primary_keys=settings.primary_keys,
        partition_keys=[settings.partition_key] if settings.partition_key else None,
        partition_mode="datetime" if settings.partition_key else None,
        partition_format="month" if settings.partition_key else None,
        sort_mode=settings.sort_mode,
        supports_resume=supports_resume,
    )
