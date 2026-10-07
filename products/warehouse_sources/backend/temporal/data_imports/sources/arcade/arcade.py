from datetime import UTC, date, datetime
from typing import Any, cast

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.arcade.settings import (
    AUTH_ERROR,
    BASE_URL,
    ENDPOINTS,
    INSIGHTS_ERROR,
    PAGE_SIZE,
    PERMISSION_ERROR,
    PLAN_ERROR,
    PROVISIONING_ERROR,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    Endpoint,
    EndpointResource,
    PaginatorConfig,
    ResponseAction,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.arcade import ArcadeSourceConfig

ERROR_MESSAGES = (AUTH_ERROR, PLAN_ERROR, PROVISIONING_ERROR, INSIGHTS_ERROR, PERMISSION_ERROR)
RESPONSE_ACTIONS: list[ResponseAction] = [
    {
        "status_code": 401,
        "json_field": "error",
        "json_values": ["Workspace is not growth or above"],
        "action": "raise",
        "message": PLAN_ERROR,
    },
    {
        "status_code": 403,
        "json_field": "error",
        "json_values": ["This operation requires provisioning scope"],
        "action": "raise",
        "message": PROVISIONING_ERROR,
    },
    {
        "status_code": 403,
        "json_field": "error",
        "json_values": ["This operation requires insights scope"],
        "action": "raise",
        "message": INSIGHTS_ERROR,
    },
    {"status_code": 401, "action": "raise", "message": AUTH_ERROR},
    {"status_code": 403, "action": "raise", "message": PERMISSION_ERROR},
]


@frozen
class ArcadeResumeConfig:
    page: int
    period_start: str
    period_end: str
    completed: bool = False


def parse_start_date(value: str) -> str:
    try:
        start = date.fromisoformat(value)
    except ValueError:
        raise ValueError("Enter the Arcade start date as YYYY-MM-DD.") from None
    if start > datetime.now(UTC).date():
        raise ValueError("The Arcade start date must be today or earlier.")
    return datetime.combine(start, datetime.min.time(), tzinfo=UTC).isoformat()


def get_resource(
    config: ArcadeSourceConfig, name: str, period_start: str, period_end: str, *, probe: bool = False
) -> EndpointResource:
    if name not in ENDPOINTS:
        raise ValueError("Unknown Arcade table. Select a table from the source settings.")
    definition = ENDPOINTS[name]
    endpoint: Endpoint = {
        "path": definition.path,
        "data_selector": definition.selector,
        "data_selector_required": True,
        "paginator": "single_page",
        "response_actions": RESPONSE_ACTIONS,
    }
    if definition.insight_type:
        endpoint["method"] = "POST"
        endpoint["json"] = {"type": definition.insight_type, "teamId": config.team_id}
        if name == "flow_engagement":
            endpoint["json"].update({"from": period_start, "to": period_end, "size": 1 if probe else PAGE_SIZE})
            endpoint["paginator"] = cast(
                PaginatorConfig,
                {
                    "type": "page_number",
                    "base_page": 1,
                    "param_location": "json",
                    "maximum_page": 1 if probe else None,
                },
            )

    def add_context(row: dict[str, Any]) -> dict[str, Any]:
        if definition.insight_type:
            row = {**row, "team_id": config.team_id}
        if name == "flow_engagement":
            row = {**row, "period_start": period_start, "period_end": period_end}
        return row

    return {"name": name, "endpoint": endpoint, "write_disposition": "replace", "data_map": add_context}


def rest_config(config: ArcadeSourceConfig, resource: EndpointResource) -> RESTAPIConfig:
    return {
        "client": {
            "base_url": BASE_URL,
            "auth": {"type": "api_key", "api_key": config.api_key, "name": "Authorization", "location": "header"},
            "allow_redirects": False,
            "allowed_hosts": [],
            "request_timeout": 30,
        },
        "resources": [resource],
    }


def validate_credentials(config: ArcadeSourceConfig, team_id: int, schema_name: str | None) -> tuple[bool, str | None]:
    try:
        start = parse_start_date(config.start_date)
        resource_config = get_resource(config, schema_name or "teams", start, datetime.now(UTC).isoformat(), probe=True)
    except ValueError as error:
        return False, str(error)
    resource = rest_api_resource(rest_config(config, resource_config), team_id, "arcade_validate", None)
    try:
        next(iter(resource), None)
    except ValueError as error:
        message = str(error)
        if message not in ERROR_MESSAGES:
            raise
        if schema_name is None and message in (PROVISIONING_ERROR, INSIGHTS_ERROR, PERMISSION_ERROR):
            return True, None
        return False, message
    return True, None


def arcade_source(
    config: ArcadeSourceConfig,
    name: str,
    team_id: int,
    job_id: str,
    manager: ResumableSourceManager[ArcadeResumeConfig],
) -> SourceResponse:
    resume = manager.load_state() if manager.can_resume() else None
    period_start = resume.period_start if resume else parse_start_date(config.start_date)
    period_end = resume.period_end if resume else datetime.now(UTC).isoformat()
    resource_config = get_resource(config, name, period_start, period_end)
    if resume and resume.completed:
        return SourceResponse(name=name, items=lambda: iter(()), primary_keys=list(ENDPOINTS[name].primary_keys))

    def save_state(state: dict[str, Any] | None) -> None:
        manager.save_state(
            ArcadeResumeConfig(
                page=int(state["page"]) if state else 1,
                period_start=period_start,
                period_end=period_end,
                completed=state is None,
            )
        )

    resource = rest_api_resource(
        rest_config(config, resource_config),
        team_id,
        job_id,
        None,
        resume_hook=save_state,
        initial_paginator_state={"page": resume.page} if resume else None,
    )
    return SourceResponse(name=name, items=lambda: resource, primary_keys=list(ENDPOINTS[name].primary_keys))
