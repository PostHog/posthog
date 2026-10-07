from collections.abc import Callable, Iterable, Iterator
from dataclasses import replace
from typing import Any, cast

from requests import HTTPError

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
    PaginatorConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.lexware_office.settings import (
    BASE_URL,
    ENDPOINTS,
    SEARCH_WINDOW_LIMIT,
)

AUTH_ERROR = "Your Lexware Office API key is invalid or expired. Create a new key and reconnect."
PERMISSION_ERROR = "Your Lexware Office API key cannot read this resource. Enable read access for the selected tables."
WINDOW_ERROR = (
    "Lexware Office's 10,000-record search limit was reached. This source cannot safely import this collection."
)


@frozen
class LexwareOfficeResumeConfig:
    paginator_state: dict[str, Any] | None = None
    completed: bool = False


def client_config(api_key: str) -> ClientConfig:
    return {
        "base_url": BASE_URL,
        "auth": {"type": "bearer", "token": api_key},
        "headers": {"Accept": "application/json"},
        "request_timeout": (10, 60),
        "allow_redirects": False,
    }


def list_endpoint(path: str, params: dict[str, Any]) -> Endpoint:
    endpoint: Endpoint = {
        "path": path,
        "params": params,
        "data_selector": "content",
        "data_selector_required": True,
        "paginator": cast(PaginatorConfig, {"type": "page_number", "base_page": 0, "total_path": "totalPages"}),
        # totalElements is capped, so a full search window cannot prove the collection is complete.
        "response_actions": [
            {
                "status_code": 200,
                "json_field": "totalElements",
                "json_values": [SEARCH_WINDOW_LIMIT],
                "action": "raise",
                "message": WINDOW_ERROR,
            }
        ],
    }
    return endpoint


def get_resource(
    api_key: str,
    endpoint_name: str,
    team_id: int,
    job_id: str,
    resume_hook: Callable[[dict[str, Any] | None], None] | None = None,
    initial_state: dict[str, Any] | None = None,
    probe: bool = False,
) -> Iterable[list[dict[str, Any]]]:
    endpoint = schema_for_resource(ENDPOINTS, endpoint_name)
    if endpoint.fanout:
        parent_endpoint = list_endpoint(ENDPOINTS[endpoint.fanout.parent_name].path, {})
        del parent_endpoint["params"]
        fanout = endpoint.fanout
        if probe:
            parent_endpoint["paginator"] = "single_page"
            parent_endpoint.pop("response_actions")
            fanout = replace(fanout, parent_params={**fanout.parent_params, "size": 1})
        return build_dependent_resource(
            endpoint_configs=ENDPOINTS,
            child_endpoint=endpoint_name,
            fanout=fanout,
            client_config=client_config(api_key),
            path_format_values={},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=None,
            parent_endpoint_extra=parent_endpoint,
            child_endpoint_extra={"paginator": "single_page", "data_selector": "$"},
            page_size_param=None,
            resume_hook=resume_hook,
            initial_paginator_state=initial_state,
        )
    request = list_endpoint(endpoint.path, {**endpoint.params, "size": 1 if probe else endpoint.page_size})
    if probe:
        request["paginator"] = "single_page"
        request.pop("response_actions")
    config: RESTAPIConfig = {
        "client": client_config(api_key),
        "resources": [
            {
                "name": endpoint_name,
                "table_name": endpoint_name,
                "write_disposition": "replace",
                "table_format": "delta",
                "endpoint": request,
            }
        ],
    }
    return rest_api_resource(
        config, team_id, job_id, None, resume_hook=resume_hook, initial_paginator_state=initial_state
    )


def validate_credentials(api_key: str, team_id: int, schema_name: str | None) -> tuple[bool, str | None]:
    try:
        next(iter(get_resource(api_key, schema_name or "contacts", team_id, "credential-validation", probe=True)), None)
    except HTTPError as error:
        status = error.response.status_code if error.response is not None else None
        if status == 401:
            return False, AUTH_ERROR
        if status == 403:
            return (True, None) if schema_name is None else (False, PERMISSION_ERROR)
        raise
    return True, None


def lexware_office_source(
    api_key: str,
    endpoint_name: str,
    team_id: int,
    job_id: str,
    manager: ResumableSourceManager[LexwareOfficeResumeConfig],
) -> SourceResponse:
    endpoint = schema_for_resource(ENDPOINTS, endpoint_name)

    def items() -> Iterator[list[dict[str, Any]]]:
        resume = manager.load_state() if manager.can_resume() else None
        if resume and resume.completed:
            return

        def save_checkpoint(state: dict[str, Any] | None) -> None:
            manager.save_state(LexwareOfficeResumeConfig(paginator_state=state))

        initial_state = resume.paginator_state if resume else None
        resource = get_resource(api_key, endpoint_name, team_id, job_id, save_checkpoint, initial_state)
        yield from resource
        manager.save_state(LexwareOfficeResumeConfig(completed=True))

    return SourceResponse(
        name=endpoint_name,
        items=items,
        primary_keys=[endpoint.primary_key],
        partition_keys=[endpoint.partition_key] if endpoint.partition_key else None,
        partition_mode="datetime" if endpoint.partition_key else None,
        partition_format="month" if endpoint.partition_key else None,
        sort_mode=None,
    )
