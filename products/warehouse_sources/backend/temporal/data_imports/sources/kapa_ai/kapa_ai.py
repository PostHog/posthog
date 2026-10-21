from collections.abc import Iterator
from typing import Any
from uuid import UUID

from requests.exceptions import HTTPError

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.kapa_ai.settings import BASE_URL, ENDPOINTS

AUTH_ERRORS = {
    401: "Your kapa.ai API key is invalid or expired. Create a new key and reconnect.",
    403: "Your kapa.ai API key cannot access this data. Check the key's project access and permissions.",
    404: "The kapa.ai project was not found. Check your project ID and the key's project access.",
}


@frozen
class KapaResumeConfig:
    paginator_state: dict[str, Any] | None = None


def get_resource(name: str, project_id: str, page_size: int = 100) -> EndpointResource:
    definition = schema_for_resource(ENDPOINTS, name)
    endpoint = definition.endpoint.copy()
    endpoint["path"] = str(endpoint["path"]).replace("{project_id}", str(UUID(project_id)))
    params = dict(endpoint.get("params") or {})
    if endpoint["paginator"] != "single_page":
        params["page_size"] = page_size
    endpoint["params"] = params
    resource: EndpointResource = {"name": name, "endpoint": endpoint, "write_disposition": "replace"}

    if definition.parent:
        parent = definition.parent
        params["period_id"] = {"type": "resolve", "resource": parent, "field": "id"}
        resource["include_from_parent"] = ["id", "start_date", "end_date", "interval"]

        def map_period(row: dict[str, Any]) -> dict[str, Any]:
            for key in ("id", "start_date", "end_date", "interval"):
                row[f"period_{key}"] = row.pop(f"_{parent}_{key}")
            return row

        resource["data_map"] = map_period
    elif name == "activity":
        resource["data_map"] = lambda row: {**row, "project_id": str(UUID(project_id))}
    return resource


def build_resource(
    api_key: str,
    project_id: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    manager: ResumableSourceManager[KapaResumeConfig] | None = None,
    resume: KapaResumeConfig | None = None,
    page_size: int = 100,
) -> Resource:
    definition = schema_for_resource(ENDPOINTS, endpoint)
    resources: list[str | EndpointResource] = [get_resource(endpoint, project_id, page_size)]
    if definition.parent:
        resources.insert(0, get_resource(definition.parent, project_id, page_size))
    config: RESTAPIConfig = {
        "client": {
            "base_url": BASE_URL,
            "auth": {"type": "api_key", "name": "X-API-KEY", "api_key": api_key, "location": "header"},
            "headers": {"Accept": "application/json"},
            "allowed_hosts": ["api.kapa.ai"],
            "allow_redirects": False,
            "request_timeout": (10, 60),
        },
        "resources": resources,
    }

    def save_state(state: dict[str, Any] | None) -> None:
        if manager is not None:
            manager.save_state(KapaResumeConfig(paginator_state=state))

    factory = rest_api_resources if definition.parent else rest_api_resource
    result = factory(
        config,
        team_id=team_id,
        job_id=job_id,
        db_incremental_field_last_value=None,
        resume_hook=save_state if manager else None,
        initial_paginator_state=resume.paginator_state if resume else None,
    )
    return result[-1] if isinstance(result, list) else result


def validate_credentials(
    api_key: str, project_id: str, team_id: int, schema_name: str | None = None
) -> tuple[bool, str | None]:
    try:
        UUID(project_id)
    except ValueError:
        return False, "Enter a valid kapa.ai project ID in UUID format."
    if (
        not api_key
        or not api_key.isascii()
        or any(character.isspace() for character in api_key)
        or not api_key.isprintable()
    ):
        return False, "Enter a valid kapa.ai API key without whitespace or unsupported characters."
    if schema_name is not None and schema_name not in ENDPOINTS:
        return False, "Unknown kapa.ai table. Refresh the table list and try again."
    try:
        for _ in build_resource(api_key, project_id, schema_name or "threads", team_id, "", page_size=1):
            break
    except HTTPError as error:
        status = error.response.status_code if error.response is not None else None
        if status is not None and status in AUTH_ERRORS:
            return False, AUTH_ERRORS[status]
        raise
    return True, None


def kapa_ai_source(
    api_key: str,
    project_id: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[KapaResumeConfig],
) -> SourceResponse:
    definition = schema_for_resource(ENDPOINTS, endpoint)

    def get_rows() -> Iterator[list[dict[str, Any]]]:
        resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
        resource = build_resource(api_key, project_id, endpoint, team_id, job_id, resumable_source_manager, resume)
        yield from resource
        resumable_source_manager.clear_state()

    return SourceResponse(
        name=endpoint,
        items=get_rows,
        primary_keys=list(definition.primary_keys),
        partition_keys=[definition.partition_key] if definition.partition_key else None,
        partition_mode="datetime" if definition.partition_key else None,
        partition_format="month" if definition.partition_key else None,
        sort_mode=None,
    )
