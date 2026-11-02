import re

from requests import RequestException

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ResponseAction
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.semrush.settings import (
    ACCESS_ERROR,
    AUTH_ERROR,
    BASE_URL,
    ENDPOINTS,
    ERROR_MESSAGES,
    MAX_REQUEST_ATTEMPTS,
    PROJECT_ID_ERROR,
    REQUEST_ERROR,
    UNAVAILABLE_ERROR,
)


def validate_project_id(project_id: str) -> None:
    if re.fullmatch(r"[0-9]+", project_id) is None:
        raise ValueError(PROJECT_ID_ERROR)


def normalize_row(row: dict[str, object], project_id: str, primary_key: str) -> dict[str, object]:
    if row.get(primary_key) is None:
        raise ValueError("Semrush returned a record without its ID.")
    return {**row, "project_id": project_id}


def semrush_resource(api_key: str, project_id: str, endpoint: str, team_id: int, job_id: str) -> Resource:
    validate_project_id(project_id)
    settings = schema_for_resource(ENDPOINTS, endpoint)
    error_actions: list[ResponseAction] = [
        {"json_field": "code", "json_values": [code, str(code)], "action": "raise", "message": message}
        for code, message in ERROR_MESSAGES.items()
    ]
    client_error_actions: list[ResponseAction] = [
        {"status_code": status, "action": "raise", "message": REQUEST_ERROR}
        for status in range(400, 500)
        if status != 429
    ]
    actions: list[ResponseAction] = [
        {"status_code": 401, "action": "raise", "message": AUTH_ERROR},
        {"status_code": 403, "action": "raise", "message": ACCESS_ERROR},
        *error_actions,
        {"json_field": "code", "json_values": [511, "511"], "action": "retry", "message": "Semrush temporary error."},
        *client_error_actions,
    ]
    config: RESTAPIConfig = {
        "client": {
            "base_url": BASE_URL,
            "auth": {"type": "api_key", "name": "key", "api_key": api_key, "location": "query"},
            "paginator": "single_page",
            "max_retries": MAX_REQUEST_ATTEMPTS,
            "allowed_hosts": [],
            "allow_redirects": False,
            "request_timeout": (10, 30),
        },
        "resources": [
            {
                "name": endpoint,
                "write_disposition": "replace",
                "endpoint": {
                    "path": f"{project_id}/siteaudit/{settings['path']}",
                    "data_selector": settings["selector"],
                    "data_selector_required": True,
                    "response_actions": actions,
                },
                "data_map": lambda row: normalize_row(row, project_id, settings["primary_key"]),
            }
        ],
    }
    return rest_api_resource(config, team_id, job_id, None)


def validate_credentials(api_key: str, project_id: str, team_id: int) -> tuple[bool, str | None]:
    try:
        list(semrush_resource(api_key, project_id, "site_audit", team_id, ""))
    except ValueError as error:
        message = str(error)
        if message in {*ERROR_MESSAGES.values(), PROJECT_ID_ERROR, REQUEST_ERROR}:
            return False, message
        raise
    except (RequestException, RESTClientRetryableError):
        return False, UNAVAILABLE_ERROR
    return True, None


def semrush_source(api_key: str, project_id: str, endpoint: str, team_id: int, job_id: str) -> SourceResponse:
    resource = semrush_resource(api_key, project_id, endpoint, team_id, job_id)
    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=["project_id", ENDPOINTS[endpoint]["primary_key"]],
    )
