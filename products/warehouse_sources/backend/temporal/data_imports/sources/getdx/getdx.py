from typing import Any

from requests import RequestException

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    Endpoint,
    ResponseAction,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.getdx import GetdxSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.getdx.settings import (
    BASE_URL,
    ENDPOINTS,
    PRIMARY_KEYS,
)

AUTH_ERROR = "DX authentication failed. Check your organization token in Admin > Organization tokens."
PERMISSION_ERROR = "DX access was denied. Check the token scopes and your DX plan for this table."
API_ERROR = "DX rejected the request. Check the token permissions and your DX plan."
RESPONSE_ACTIONS: list[ResponseAction] = [
    {"status_code": 401, "action": "raise", "message": AUTH_ERROR},
    {"status_code": 403, "action": "raise", "message": PERMISSION_ERROR},
    {"json_field": "error", "json_values": ["not_authed", "invalid_auth"], "action": "raise", "message": AUTH_ERROR},
    {"json_field": "error", "json_values": ["not_authorized"], "action": "raise", "message": PERMISSION_ERROR},
    {"json_field": "ok", "json_values": [False], "action": "raise", "message": API_ERROR},
]


@frozen
class GetdxResumeConfig:
    paginator_state: dict[str, Any]


def resource_config(api_key: str, name: str, endpoint: Endpoint) -> RESTAPIConfig:
    return {
        "client": {
            "base_url": BASE_URL,
            "auth": {"type": "bearer", "token": api_key},
            "headers": {"Accept": "application/json"},
            "request_timeout": (10, 60),
        },
        "resources": [
            {
                "name": name,
                "endpoint": {**endpoint, "response_actions": RESPONSE_ACTIONS, "data_selector_required": True},
            }
        ],
    }


def validate_credentials(api_key: str, team_id: int) -> tuple[bool, str | None]:
    resource = rest_api_resource(
        resource_config(
            api_key,
            "auth",
            {"path": "auth.whoami", "paginator": "single_page", "data_selector": "$"},
        ),
        team_id,
        "getdx_validate_credentials",
        None,
    )
    try:
        pages = list(resource)
    except ValueError as error:
        message = str(error)
        return False, message if message in (
            AUTH_ERROR,
            PERMISSION_ERROR,
            API_ERROR,
        ) else "DX returned an invalid response."
    except (RequestException, RESTClientRetryableError):
        return False, "Could not connect to DX. Try again later."
    if pages and pages[0] and isinstance(pages[0][0], dict) and pages[0][0].get("ok") is True:
        return True, None
    return False, "DX returned an invalid response."


def getdx_source(
    config: GetdxSourceConfig,
    inputs: SourceInputs,
    manager: ResumableSourceManager[GetdxResumeConfig],
) -> SourceResponse:
    if inputs.schema_name not in ENDPOINTS:
        raise ValueError(f"Unknown DX table: {inputs.schema_name}")
    if inputs.should_use_incremental_field:
        raise ValueError("DX tables support full refresh only.")

    endpoint = ENDPOINTS[inputs.schema_name]
    supports_resume = endpoint["paginator"] != "single_page"
    resume = manager.load_state() if supports_resume and manager.can_resume() else None

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state:
            manager.save_state(GetdxResumeConfig(paginator_state=state))

    resource: Resource = rest_api_resource(
        resource_config(config.api_key, inputs.schema_name, endpoint),
        inputs.team_id,
        inputs.job_id,
        None,
        resume_hook=save_checkpoint if supports_resume else None,
        initial_paginator_state=resume.paginator_state if resume else None,
    )
    return SourceResponse(
        name=inputs.schema_name,
        items=lambda: resource,
        primary_keys=PRIMARY_KEYS.copy(),
        sort_mode=None,
        supports_resume=supports_resume,
    )
