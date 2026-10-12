from typing import TYPE_CHECKING, Any

from requests.exceptions import HTTPError

from sources.harness.settings import AUTH_ERROR, ENDPOINTS, PERMISSION_ERROR, REGION_ERROR, REGIONS
from sources.sdk import (
    APIKeyAuth,
    Endpoint,
    RESTAPIConfig,
    RESTClient,
    SinglePagePaginator,
    SourceResponse,
    frozen,
    rest_api_resource,
    schema_for_resource,
)

if TYPE_CHECKING:
    from sources.harness._config import HarnessSourceConfig
    from sources.sdk import ResumableSourceManager


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
