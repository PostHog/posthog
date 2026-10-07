from typing import Any

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import APIKeyAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.synthesia.settings import (
    AUTH_ERROR,
    BASE_URL,
    ENDPOINTS,
    PAGE_SIZE,
)


@frozen
class SynthesiaResumeConfig:
    next_offset: int


def remove_webhook_secret(row: dict[str, Any]) -> dict[str, Any]:
    # Signing secrets must not become queryable warehouse columns.
    return {key: value for key, value in row.items() if key != "secret"}


def validate_credentials(api_key: str, api_version: str, endpoint: str = "videos") -> tuple[bool, str | None]:
    path = schema_for_resource(ENDPOINTS, endpoint)
    with make_tracked_session() as session:
        response = session.get(
            f"{BASE_URL}/{api_version}/{path}",
            params={"limit": 1},
            auth=APIKeyAuth(api_key=api_key),
            timeout=30,
        )
    if response.status_code in (401, 403):
        return False, AUTH_ERROR
    response.raise_for_status()
    return True, None


def synthesia_source(
    api_key: str,
    api_version: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[SynthesiaResumeConfig],
) -> SourceResponse:
    path = schema_for_resource(ENDPOINTS, endpoint)
    resource_config: EndpointResource = {
        "name": endpoint,
        "table_name": endpoint,
        "write_disposition": "replace",
        "endpoint": {
            "path": path,
            "data_selector": endpoint,
            "data_selector_required": True,
            "params": {"limit": PAGE_SIZE, "offset": 0},
        },
    }
    if endpoint == "webhooks":
        resource_config["data_map"] = remove_webhook_secret

    config: RESTAPIConfig = {
        "client": {
            "base_url": f"{BASE_URL}/{api_version}/",
            "request_timeout": (10.0, 60.0),
            "auth": {"type": "api_key", "name": "Authorization", "api_key": api_key, "location": "header"},
            "paginator": {
                "type": "cursor",
                "cursor_path": "nextOffset",
                "cursor_param": "offset",
                "raise_on_repeated_cursor": True,
            },
        },
        "resources": [resource_config],
    }
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state is not None and state.get("cursor") is not None:
            resumable_source_manager.save_state(SynthesiaResumeConfig(next_offset=int(state["cursor"])))

    resource = rest_api_resource(
        config,
        team_id,
        job_id,
        db_incremental_field_last_value=None,
        resume_hook=save_checkpoint,
        initial_paginator_state={"cursor": resume.next_offset} if resume else None,
    )
    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=["id"],
        sort_mode=None,
        on_complete=resumable_source_manager.clear_state,
    )
