from datetime import UTC, date, datetime
from typing import Any

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import rest_api_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import APIKeyAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    Endpoint,
    EndpointResource,
    PaginatorConfig,
    RESTAPIConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.peecai import PeecAISourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.peec_ai.settings import (
    AUTH_ERRORS,
    BASE_URL,
    ENDPOINTS,
    PAGE_SIZE,
)


@frozen
class PeecAIResumeConfig:
    offset: int
    start_date: str | None = None
    end_date: str | None = None


def validate_credentials(config: PeecAISourceConfig, api_version: str) -> tuple[bool, str | None]:
    try:
        start = date.fromisoformat(config.start_date)
    except ValueError:
        return False, "Enter a valid start date in YYYY-MM-DD format."
    if start.isoformat() != config.start_date:
        return False, "Enter a valid start date in YYYY-MM-DD format."
    if start > datetime.now(UTC).date():
        return False, "The start date must be today or earlier."

    params: dict[str, str | int] = {"limit": 1}
    if config.project_id:
        params["project_id"] = config.project_id

    with make_tracked_session() as session:
        response = session.get(
            f"{BASE_URL}/{api_version}/brands",
            params=params,
            auth=APIKeyAuth(api_key=config.api_key, name="x-api-key", location="header"),
            timeout=30,
        )
        if response.status_code in AUTH_ERRORS:
            return False, AUTH_ERRORS[response.status_code]
        response.raise_for_status()
    return True, None


def peec_ai_source(
    config: PeecAISourceConfig,
    endpoint: str,
    api_version: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[PeecAIResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: str | date | datetime | None,
) -> SourceResponse:
    definition = schema_for_resource(ENDPOINTS, endpoint)
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    params: dict[str, Any] = dict(definition["params"])
    if config.project_id:
        params["project_id"] = config.project_id

    start_date: str | None = None
    end_date: str | None = None
    if endpoint == "chats":
        start_date = config.start_date
        if should_use_incremental_field and db_incremental_field_last_value is not None:
            watermark = db_incremental_field_last_value
            if isinstance(watermark, datetime):
                watermark = watermark.date()
            start_date = max(start_date, str(watermark)[:10])
        end_date = datetime.now(UTC).date().isoformat()
        if resume is not None:
            # Offset pagination must keep the original date range when a retry advances the watermark.
            start_date = resume.start_date or start_date
            end_date = resume.end_date or end_date
        params.update(start_date=start_date, end_date=end_date)

    method = definition.get("method", "GET")
    endpoint_config: Endpoint = {"path": definition["path"], "method": method, "data_selector": "data"}
    if method == "POST":
        endpoint_config["json"] = params
    else:
        endpoint_config["params"] = params

    paginator: PaginatorConfig = "single_page"
    if definition.get("paginated", True):
        paginator = {
            "type": "offset",
            "limit": PAGE_SIZE,
            "total_path": definition["total_path"],
            "param_location": "json" if method == "POST" else "query",
        }

    resource_config: EndpointResource = {"name": endpoint, "endpoint": endpoint_config}
    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": f"{BASE_URL}/{api_version}/",
            "auth": {"type": "api_key", "api_key": config.api_key, "name": "x-api-key", "location": "header"},
            "paginator": paginator,
            "request_timeout": 30,
        },
        "resources": [resource_config],
    }

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state is not None:
            resumable_source_manager.save_state(
                PeecAIResumeConfig(offset=int(state["offset"]), start_date=start_date, end_date=end_date)
            )

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state={"offset": resume.offset} if resume is not None else None,
    )
    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=definition.get("primary_keys", ["id"]),
        sort_mode="asc" if endpoint == "chats" else None,
        on_complete=resumable_source_manager.clear_state,
    )
