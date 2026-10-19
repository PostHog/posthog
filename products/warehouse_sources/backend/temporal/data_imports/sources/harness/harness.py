from typing import TYPE_CHECKING, Any

from requests.exceptions import HTTPError

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import APIKeyAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import Endpoint
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.harness.settings import (
    AUTH_ERROR,
    ENDPOINTS,
    PERMISSION_ERROR,
    REGION_ERROR,
    REGIONS,
)

if TYPE_CHECKING:
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
    from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.harness import (
        HarnessSourceConfig,
    )


@frozen
class HarnessResumeConfig:
    page: int


def base_url(config: "HarnessSourceConfig") -> str:
    if config.region not in REGIONS:
        raise ValueError(REGION_ERROR)
    return REGIONS[config.region]


def endpoint_config(config: "HarnessSourceConfig", name: str, size: int = 100) -> Endpoint:
    endpoint = schema_for_resource(ENDPOINTS, name)
    request: Endpoint = {
        "path": endpoint.path,
        "method": endpoint.method,
        "params": {
            "accountIdentifier": config.account_id,
            "orgIdentifier": config.organization_id,
            "projectIdentifier": config.project_id,
            "size": size,
        },
        "data_selector": "data.content",
        "data_selector_required": True,
    }
    if endpoint.filter_type is not None:
        request["json"] = {"filterType": endpoint.filter_type}
    return request


def validate_credentials(config: "HarnessSourceConfig", schema_name: str | None = None) -> tuple[bool, str | None]:
    try:
        url = base_url(config)
    except ValueError as error:
        return False, str(error)

    endpoint = endpoint_config(config, schema_name or "pipelines", size=1)
    client = RESTClient(
        base_url=url,
        auth=APIKeyAuth(api_key=config.api_key, name="x-api-key"),
        paginator=SinglePagePaginator(),
        allowed_hosts=[],
        allow_redirects=False,
        request_timeout=60,
    )
    try:
        next(
            client.paginate(
                path=endpoint["path"] or "",
                method=endpoint["method"] or "GET",
                params={**(endpoint["params"] or {}), "page": 0},
                json=endpoint.get("json"),
                data_selector="data.content",
                data_selector_required=True,
            ),
            None,
        )
    except HTTPError as error:
        status = error.response.status_code if error.response is not None else None
        if status == 401:
            return False, AUTH_ERROR
        if status == 403:
            return (True, None) if schema_name is None else (False, PERMISSION_ERROR)
        if status in (400, 404):
            return False, "Check your Harness account, organization, project, and region."
        raise
    return True, None


def harness_source(
    config: "HarnessSourceConfig",
    name: str,
    team_id: int,
    job_id: str,
    manager: "ResumableSourceManager[HarnessResumeConfig]",
) -> SourceResponse:
    endpoint = schema_for_resource(ENDPOINTS, name)
    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": base_url(config),
            "auth": {"type": "api_key", "name": "x-api-key", "api_key": config.api_key, "location": "header"},
            "paginator": {"type": "page_number", "page_param": "page", "total_path": "data.totalPages"},
            "allowed_hosts": [],
            "allow_redirects": False,
            "request_timeout": 60,
        },
        "resources": [{"name": name, "endpoint": endpoint_config(config, name), "write_disposition": "replace"}],
    }
    state = manager.load_state() if manager.can_resume() else None

    def save_checkpoint(paginator_state: dict[str, Any] | None) -> None:
        if paginator_state is not None:
            manager.save_state(HarnessResumeConfig(page=int(paginator_state["page"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state={"page": state.page} if state is not None else None,
    )

    def normalize_row(row: dict[str, Any]) -> dict[str, Any]:
        if endpoint.wrapper is not None:
            details = row.get(endpoint.wrapper)
            if not isinstance(details, dict) or not details.get(endpoint.primary_key):
                raise ValueError(f"Harness returned a {name} row without an identifier.")
            return {**details, **{key: value for key, value in row.items() if key != endpoint.wrapper}}
        if not row.get(endpoint.primary_key):
            raise ValueError(f"Harness returned a {name} row without an identifier.")
        return row

    resource.add_map(normalize_row)
    return SourceResponse(
        name=name,
        items=lambda: resource,
        primary_keys=[endpoint.primary_key],
        sort_mode=None,
        on_complete=manager.clear_state,
    )
