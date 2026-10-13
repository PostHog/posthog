from typing import Any

from requests.exceptions import HTTPError

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.catchpoint.settings import (
    API_ROOT,
    AUTH_ERROR,
    ENDPOINTS,
    INCOMPLETE_ERROR,
    PAGE_SIZE,
    PERMISSION_ERROR,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ClientConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse


@frozen
class CatchpointResumeConfig:
    next_url: str


def client_config(api_key: str, api_version: str) -> ClientConfig:
    return {
        "base_url": f"{API_ROOT}/{api_version}/",
        "auth": {"type": "bearer", "token": api_key},
        "headers": {"Accept": "application/json"},
        "paginator": {"type": "json_response", "next_url_path": "data.next"},
        "allowed_hosts": [],
        "allow_redirects": False,
        "request_timeout": 30,
    }


def validate_credentials(api_key: str, api_version: str, team_id: int) -> tuple[bool, str | None]:
    config: RESTAPIConfig = {
        "client": client_config(api_key, api_version),
        "resources": [
            {
                "name": "useridentity",
                "endpoint": {
                    "path": "useridentity",
                    "paginator": "single_page",
                    "data_selector": "data",
                    "data_selector_required": True,
                    "response_actions": [
                        {
                            "json_field": "completed",
                            "json_values": [False],
                            "action": "raise",
                            "message": INCOMPLETE_ERROR,
                        }
                    ],
                },
            }
        ],
    }
    try:
        list(rest_api_resource(config, team_id, "catchpoint-validate", None))
    except HTTPError as error:
        if error.response is not None and error.response.status_code in (401, 403):
            return False, AUTH_ERROR if error.response.status_code == 401 else PERMISSION_ERROR
        raise
    return True, None


def catchpoint_source(
    api_key: str,
    api_version: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[CatchpointResumeConfig],
) -> SourceResponse:
    settings = ENDPOINTS[endpoint]
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state is not None and state.get("next_url"):
            resumable_source_manager.save_state(CatchpointResumeConfig(next_url=str(state["next_url"])))

    config: RESTAPIConfig = {
        "client": client_config(api_key, api_version),
        "resources": [
            {
                "name": endpoint,
                "table_name": endpoint,
                "write_disposition": "replace",
                "endpoint": {
                    "path": settings["path"],
                    "params": {"pageNumber": 1, "pageSize": PAGE_SIZE} if settings["paginated"] else {},
                    "data_selector": settings["data_selector"],
                    "data_selector_required": True,
                    "response_actions": [
                        {
                            "json_field": "completed",
                            "json_values": [False],
                            "action": "raise",
                            "message": INCOMPLETE_ERROR,
                        }
                    ],
                },
            }
        ],
    }
    resource = rest_api_resource(
        config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state={"next_url": resume.next_url} if resume is not None else None,
    )
    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=settings["primary_keys"],
        sort_mode=None,
        on_complete=resumable_source_manager.clear_state,
    )
