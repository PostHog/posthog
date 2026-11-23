import re
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, cast
from uuid import UUID

from requests import Request, Response
from requests.exceptions import HTTPError

from products.warehouse_sources.sources.sdk import (
    APIKeyAuth,
    BasePaginator,
    ClientConfig,
    Endpoint,
    EndpointResource,
    JSONResponseCursorPaginator,
    PageNumberPaginator,
    Resource,
    RESTAPIConfig,
    RESTClient,
    ResumableSourceManager,
    SinglePagePaginator,
    SourceInputs,
    SourceResponse,
    build_dependent_resource,
    frozen,
    parse_datetime_value,
    rest_api_resource,
    schema_for_resource,
)
from products.warehouse_sources.sources.semaphore._config import SemaphoreSourceConfig
from products.warehouse_sources.sources.semaphore.settings import (
    AUTH_ERROR,
    ENDPOINTS,
    NOT_FOUND_ERROR,
    PERMISSION_ERROR,
    SemaphoreEndpoint,
)


@frozen
class SemaphoreResumeConfig:
    next_url: str | None = None
    completed: bool = False
    paginator_state: dict[str, Any] | None = None


class DeploymentHistoryPaginator(JSONResponseCursorPaginator):
    """Walks a target's history from the newest deployment back with `cursor_type=BEFORE`."""

    def __init__(self) -> None:
        super().__init__(cursor_path="cursor_before", cursor_param="cursor_value", raise_on_repeated_cursor=True)

    def init_request(self, request: Request) -> None:
        super().init_request(request)
        self._set_cursor_type(request)

    def update_request(self, request: Request) -> None:
        super().update_request(request)
        self._set_cursor_type(request)

    def update_state(self, response: Response, data: list[Any] | None = None) -> None:
        if not data:
            self._has_next_page = False
            return
        super().update_state(response, data)

    def _set_cursor_type(self, request: Request) -> None:
        if self._cursor_value is not None:
            request.params = {**(request.params or {}), "cursor_type": "BEFORE"}


def client_config(config: SemaphoreSourceConfig, api_version: str) -> ClientConfig:
    if not re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?", config.organization):
        raise ValueError("Enter the Semaphore organization subdomain, such as 'example', without a URL.")
    try:
        UUID(config.project_id)
    except ValueError:
        raise ValueError("Enter a valid Semaphore project ID (UUID).") from None
    return {
        "base_url": f"https://{config.organization}.semaphoreci.com/api/{api_version}/",
        "auth": APIKeyAuth(api_key=f"Token {config.api_token}", name="Authorization", location="header"),
        "headers": {"User-Agent": "SemaphoreCI v2.0 Client"},
        "paginator": "header_link",
        "allowed_hosts": [],
        "allow_redirects": False,
        "request_timeout": (10, 60),
    }


def validate_credentials(config: SemaphoreSourceConfig, api_version: str) -> tuple[bool, str | None]:
    settings = client_config(config, api_version)
    client = RESTClient(
        base_url=settings["base_url"],
        auth=APIKeyAuth(api_key=f"Token {config.api_token}"),
        headers=settings["headers"],
        allowed_hosts=[],
        allow_redirects=False,
        request_timeout=(10, 30),
    )
    try:
        next(
            client.paginate(
                "plumber-workflows",
                params={"project_id": config.project_id},
                paginator=SinglePagePaginator(),
                data_selector_required=True,
            )
        )
    except HTTPError as error:
        status = error.response.status_code if error.response is not None else None
        if status in (401, 403, 404):
            return False, {401: AUTH_ERROR, 403: PERMISSION_ERROR, 404: NOT_FOUND_ERROR}[status]
        raise
    return True, None


def normalize_created_at(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("created_at")
    if isinstance(value, dict):
        row["created_at"] = datetime.fromtimestamp(int(value["seconds"]), UTC) + timedelta(
            microseconds=int(value.get("nanos", 0)) // 1000
        )
    elif value is not None:
        parsed = parse_datetime_value(value)
        if parsed is None:
            raise ValueError("Semaphore returned an invalid creation time.")
        row["created_at"] = parsed
    return row


def _paginator(endpoint: SemaphoreEndpoint) -> BasePaginator | Literal["header_link"]:
    if endpoint.paginator == "page_number":
        return PageNumberPaginator(base_page=0, page_param="page_no", total_path="total_pages")
    if endpoint.paginator == "deployment_history":
        return DeploymentHistoryPaginator()
    return "header_link"


def _endpoint_extra(endpoint: SemaphoreEndpoint) -> Endpoint:
    extra: Endpoint = {"paginator": _paginator(endpoint), "data_selector_required": True}
    if endpoint.data_selector:
        extra["data_selector"] = endpoint.data_selector
    return extra


def semaphore_source(
    config: SemaphoreSourceConfig,
    inputs: SourceInputs,
    manager: ResumableSourceManager[SemaphoreResumeConfig],
    api_version: str,
) -> SourceResponse:
    endpoint = schema_for_resource(ENDPOINTS, inputs.schema_name)
    client = client_config(config, api_version)
    primary_keys = list(endpoint.primary_keys)
    resume = manager.load_state() if manager.can_resume() else None
    if resume is not None and resume.completed:
        return SourceResponse(
            name=inputs.schema_name, items=list, primary_keys=primary_keys, sort_mode=endpoint.sort_mode
        )

    params: dict[str, Any] = {"project_id": config.project_id} if endpoint.project_param else {}
    incremental = inputs.schema_name == "workflows" and inputs.should_use_incremental_field
    if incremental and inputs.db_incremental_field_last_value is not None:
        watermark = parse_datetime_value(inputs.db_incremental_field_last_value)
        if watermark is None:
            raise ValueError("The Semaphore workflow sync position is invalid. Reset this table and try again.")
        # The API uses exclusive whole seconds; overlap one second to preserve records at the boundary.
        params["created_after"] = int(watermark.timestamp()) - 1

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state is None:
            manager.save_state(SemaphoreResumeConfig(completed=True))
        elif set(state) == {"next_url"}:
            manager.save_state(SemaphoreResumeConfig(next_url=state["next_url"]))
        else:
            manager.save_state(SemaphoreResumeConfig(paginator_state=state))

    initial_state: dict[str, Any] | None = None
    if resume is not None:
        initial_state = resume.paginator_state or ({"next_url": resume.next_url} if resume.next_url else None)

    path_values = {"project_id": config.project_id}
    if endpoint.fanout is not None:
        parent = ENDPOINTS[endpoint.fanout.parent_name]
        fanout = (
            replace(endpoint.fanout, parent_params={"project_id": config.project_id})
            if parent.project_param
            else endpoint.fanout
        )
        resource = cast(
            Resource,
            build_dependent_resource(
                endpoint_configs=ENDPOINTS,
                child_endpoint=endpoint.name,
                fanout=fanout,
                client_config=client,
                path_format_values=path_values,
                team_id=inputs.team_id,
                job_id=inputs.job_id,
                db_incremental_field_last_value=None,
                parent_endpoint_extra=_endpoint_extra(parent),
                child_endpoint_extra=_endpoint_extra(endpoint),
                page_size_param=None,
                resume_hook=save_checkpoint,
                initial_paginator_state=initial_state,
            ),
        ).add_map(normalize_created_at)
    else:
        path = endpoint.path
        for key, value in path_values.items():
            path = path.replace(f"{{{key}}}", value)
        endpoint_config: Endpoint = cast(Endpoint, {"path": path, "params": params, **_endpoint_extra(endpoint)})
        resource_config: EndpointResource = {
            "name": inputs.schema_name,
            "endpoint": endpoint_config,
            "data_map": normalize_created_at,
        }
        rest_config: RESTAPIConfig = {"client": client, "resources": [resource_config]}
        resource = rest_api_resource(
            rest_config,
            inputs.team_id,
            inputs.job_id,
            None,
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_state,
        )
    return SourceResponse(
        name=inputs.schema_name,
        items=lambda: resource,
        primary_keys=primary_keys,
        sort_mode=endpoint.sort_mode,
    )
