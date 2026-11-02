from typing import Any

from requests import Response
from requests.exceptions import RequestException

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import APIKeyAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.lokalise.settings import (
    LOKALISE_ENDPOINTS,
    LokaliseEndpointConfig,
)

INVALID_TOKEN_MESSAGE = "Your Lokalise API token is invalid or expired. Create a new token and reconnect."
PERMISSION_MESSAGE = "Your Lokalise API token cannot read this resource. Check your project permissions."


@frozen
class LokaliseResumeConfig:
    paginator_state: dict[str, Any]


class LokaliseCursorPaginator(JSONResponseCursorPaginator):
    def __init__(self) -> None:
        super().__init__(raise_on_repeated_cursor=True)

    def update_state(self, response: Response, data: list[Any] | None = None) -> None:
        # Lokalise puts the cursor in a header instead of the JSON response.
        cursor = response.headers.get("X-Pagination-Next-Cursor")
        self._has_next_page = bool(cursor)
        if not cursor:
            return
        if cursor == self._previous_cursor_value:
            raise ValueError("Lokalise cursor pagination is not advancing")
        self._previous_cursor_value = cursor
        self._cursor_value = cursor


class LokalisePagePaginator(PageNumberPaginator):
    def __init__(self) -> None:
        super().__init__(base_page=1)

    def update_state(self, response: Response, data: list[Any] | None = None) -> None:
        page_count = response.headers.get("X-Pagination-Page-Count")
        if page_count is not None:
            self.maximum_page = int(page_count)
        super().update_state(response, data)


def _endpoint_config(config: LokaliseEndpointConfig) -> Endpoint:
    params: dict[str, Any] = {"limit": config.page_size}
    if config.pagination == "cursor":
        params["pagination"] = "cursor"
    return {
        "path": config.path,
        "data_selector": config.name,
        "data_selector_required": True,
        "params": params,
        "paginator": LokaliseCursorPaginator() if config.pagination == "cursor" else LokalisePagePaginator(),
    }


def validate_lokalise_credentials(api_token: str, api_version: str, schema_name: str | None) -> tuple[bool, str | None]:
    if schema_name is not None and schema_name not in LOKALISE_ENDPOINTS:
        return False, "This Lokalise table is not available. Select another table."
    base_url = f"https://api.lokalise.com/{api_version}"
    session = make_tracked_session(redact_values=(api_token,))
    auth = APIKeyAuth(api_key=api_token, name="X-Api-Token")
    try:
        response = session.get(f"{base_url}/projects", params={"limit": 1}, auth=auth, timeout=30)
        if response.status_code == 403 and schema_name is None:
            return True, None
        response.raise_for_status()
        if schema_name and schema_name != "projects":
            projects = response.json()["projects"]
            if projects:
                project_id = projects[0]["project_id"]
                path = LOKALISE_ENDPOINTS[schema_name].path.format(project_id=project_id)
                response = session.get(f"{base_url}{path}", params={"limit": 1}, auth=auth, timeout=30)
                response.raise_for_status()
    except RequestException as error:
        status = error.response.status_code if error.response is not None else None
        if status == 401:
            return False, INVALID_TOKEN_MESSAGE
        if status == 403:
            return False, PERMISSION_MESSAGE
        return False, "Could not connect to Lokalise. Try again."
    return True, None


def lokalise_source(
    api_token: str,
    api_version: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[LokaliseResumeConfig],
) -> SourceResponse:
    endpoint_config = schema_for_resource(LOKALISE_ENDPOINTS, endpoint)
    client: ClientConfig = {
        "base_url": f"https://api.lokalise.com/{api_version}",
        "auth": {"type": "api_key", "api_key": api_token, "name": "X-Api-Token", "location": "header"},
        "request_timeout": (10, 30),
        "retry_budget_seconds": 120,
        "retry_after_max_seconds": 60,
    }
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state is not None:
            resumable_source_manager.save_state(LokaliseResumeConfig(paginator_state=state))

    initial_state = resume.paginator_state if resume else None
    if endpoint_config.fanout is not None:
        child_extra = _endpoint_config(endpoint_config)
        child_extra.pop("params")
        resource = build_dependent_resource(
            endpoint_configs=LOKALISE_ENDPOINTS,
            child_endpoint=endpoint,
            fanout=endpoint_config.fanout,
            client_config=client,
            path_format_values={},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=None,
            parent_endpoint_extra={
                "data_selector": "projects",
                "data_selector_required": True,
                "paginator": LokalisePagePaginator(),
            },
            child_endpoint_extra=child_extra,
            child_params_extra={"pagination": "cursor"} if endpoint_config.pagination == "cursor" else None,
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_state,
        )
    else:
        config: RESTAPIConfig = {
            "client": client,
            "resources": [
                {"name": endpoint, "endpoint": _endpoint_config(endpoint_config), "write_disposition": "replace"}
            ],
        }
        resource = rest_api_resource(
            config,
            team_id,
            job_id,
            None,
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_state,
        )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=endpoint_config.primary_keys,
        # IDs stay stable, while several tables have no creation timestamp suitable for partitioning.
        partition_keys=endpoint_config.primary_keys,
        partition_mode="md5",
        partition_count=16,
        sort_mode=None,
    )
