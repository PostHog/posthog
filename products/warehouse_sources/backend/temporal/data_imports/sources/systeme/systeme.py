from datetime import datetime
from typing import Any

from requests import HTTPError, Response

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    Endpoint,
    EndpointResource,
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import APIKeyAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.systeme.settings import (
    AUTH_ERROR,
    BASE_URL,
    ENDPOINTS,
    PAGE_SIZE,
    PARTITION_KEYS,
    PERMISSION_ERROR,
)


@frozen
class SystemeResumeConfig:
    cursor: int | None = None
    completed: bool = False


class SystemePaginator(JSONResponseCursorPaginator):
    def __init__(self) -> None:
        super().__init__(cursor_path="items[-1].id", cursor_param="startingAfter", raise_on_repeated_cursor=True)

    def update_state(self, response: Response, data: list[Any] | None = None) -> None:
        body = response.json()
        if body.get("hasMore") is False:
            self._has_next_page = False
            return
        if body.get("hasMore") is not True or not data:
            raise ValueError("Systeme.io returned invalid pagination data. Retry the sync or contact support.")
        cursor = data[-1].get("id")
        if type(cursor) is not int or cursor <= 0:
            raise ValueError("Systeme.io returned an invalid record ID. Retry the sync or contact support.")
        super().update_state(response, data)


def validate_credentials(api_key: str, schema_name: str | None = None) -> tuple[bool, str | None]:
    path = schema_for_resource(ENDPOINTS, schema_name or "contacts")
    client = RESTClient(
        base_url=BASE_URL,
        auth=APIKeyAuth(api_key=api_key, name="X-API-Key"),
        paginator=SinglePagePaginator(),
        request_timeout=30,
    )
    try:
        next(client.paginate(path, params={"limit": 10}, data_selector="items", data_selector_required=True))
    except HTTPError as error:
        if error.response is not None:
            if error.response.status_code == 401:
                return False, AUTH_ERROR
            if error.response.status_code == 403:
                return False, PERMISSION_ERROR
        raise
    return True, None


def systeme_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[SystemeResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: datetime | str | None = None,
) -> SourceResponse:
    path = schema_for_resource(ENDPOINTS, endpoint)
    params: dict[str, Any] = {"limit": PAGE_SIZE, "order": "desc"}
    if endpoint == "contacts" and should_use_incremental_field and db_incremental_field_last_value is not None:
        params["registeredAfter"] = (
            db_incremental_field_last_value.isoformat()
            if isinstance(db_incremental_field_last_value, datetime)
            else db_incremental_field_last_value
        )

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        resumable_source_manager.save_state(
            SystemeResumeConfig(cursor=int(state["cursor"])) if state else SystemeResumeConfig(completed=True)
        )

    endpoint_config: Endpoint = {
        "path": path,
        "params": params,
        "data_selector": "items",
        "data_selector_required": True,
    }
    resource_config: EndpointResource = {"name": endpoint, "endpoint": endpoint_config}
    config: RESTAPIConfig = {
        "client": {
            "base_url": BASE_URL,
            "auth": {"type": "api_key", "name": "X-API-Key", "api_key": api_key, "location": "header"},
            "paginator": SystemePaginator(),
            "request_timeout": 30,
        },
        "resources": [resource_config],
    }
    resource = rest_api_resource(
        config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state={"cursor": resume.cursor} if resume and resume.cursor is not None else None,
    )
    partition_key = PARTITION_KEYS.get(endpoint)
    return SourceResponse(
        name=endpoint,
        items=(lambda: []) if resume and resume.completed else (lambda: resource),
        primary_keys=["id"],
        sort_mode="desc",
        partition_keys=[partition_key] if partition_key else None,
        partition_mode="datetime" if partition_key else None,
        partition_format="month" if partition_key else None,
    )
