from typing import Any
from uuid import UUID

from requests import Response
from requests.exceptions import HTTPError, RequestException

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import APIKeyAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClient,
    RESTClientNonRetryableError,
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.onesignal.settings import (
    BASE_URL,
    INITIAL_TIME_OFFSET,
    ONESIGNAL_ENDPOINTS,
)


@frozen
class OneSignalResumeConfig:
    next_cursor: str | None = None
    next_offset: int | None = None


class OneSignalMessagePaginator(JSONResponseCursorPaginator):
    def __init__(self) -> None:
        super().__init__(cursor_path="next_time_offset", cursor_param="time_offset", raise_on_repeated_cursor=True)

    def update_state(self, response: Response, data: list[Any] | None = None) -> None:
        # OneSignal can keep a cursor on an empty page for polling. A snapshot must stop there.
        if not data:
            self._has_next_page = False
            return
        super().update_state(response, data)


def get_resource(name: str, app_id: str) -> EndpointResource:
    endpoint = schema_for_resource(ONESIGNAL_ENDPOINTS, name)
    app_id = str(UUID(app_id))
    params: dict[str, Any] = {"limit": endpoint.page_size}
    endpoint_config: Endpoint = {
        "path": endpoint.path.format(app_id=app_id),
        "data_selector": endpoint.data_selector,
        "data_selector_required": True,
        "params": params,
    }
    if endpoint.pagination == "cursor":
        params.update(app_id=app_id, time_offset=INITIAL_TIME_OFFSET)
        endpoint_config["paginator"] = OneSignalMessagePaginator()
    else:
        endpoint_config["paginator"] = {
            "type": "offset",
            "limit": endpoint.page_size,
            "total_path": "total_count",
        }
    return {
        "name": name,
        "table_name": name,
        "table_format": "delta",
        "write_disposition": "replace",
        "endpoint": endpoint_config,
    }


def validate_credentials(api_key: str, app_id: str, endpoint: str) -> tuple[bool, str | None]:
    endpoint_config = schema_for_resource(ONESIGNAL_ENDPOINTS, endpoint)
    app_id = str(UUID(app_id))
    params: dict[str, Any] = {"limit": 1}
    if endpoint_config.pagination == "cursor":
        params["app_id"] = app_id
    client = RESTClient(
        base_url=BASE_URL,
        auth=APIKeyAuth(api_key=f"Key {api_key}"),
        request_timeout=(10, 30),
        retry_budget_seconds=120,
        retry_after_max_seconds=60,
    )
    try:
        next(
            client.paginate(
                path=endpoint_config.path.format(app_id=app_id),
                params=params,
                paginator=SinglePagePaginator(),
                data_selector=endpoint_config.data_selector,
                data_selector_required=True,
            )
        )
    except HTTPError as error:
        status = error.response.status_code if error.response is not None else None
        if status in (400, 401, 403):
            return False, "OneSignal rejected these credentials. Check the App ID, App API key, and key permissions."
        return False, "OneSignal could not validate this connection. Try again later."
    except (RequestException, RESTClientRetryableError, RESTClientNonRetryableError, ValueError):
        return False, "OneSignal could not validate this connection. Try again later."
    return True, None


def onesignal_source(
    api_key: str,
    app_id: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[OneSignalResumeConfig],
) -> SourceResponse:
    endpoint_config = schema_for_resource(ONESIGNAL_ENDPOINTS, endpoint)
    config: RESTAPIConfig = {
        "client": {
            "base_url": BASE_URL,
            "auth": {"type": "api_key", "name": "Authorization", "api_key": f"Key {api_key}", "location": "header"},
            "request_timeout": (10, 30),
            "retry_budget_seconds": 120,
            "retry_after_max_seconds": 60,
        },
        "resources": [get_resource(endpoint, app_id)],
    }
    initial_state: dict[str, Any] | None = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            if resume.next_cursor is not None:
                initial_state = {"cursor": resume.next_cursor}
            elif resume.next_offset is not None:
                initial_state = {"offset": resume.next_offset}

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state is not None:
            resumable_source_manager.save_state(
                OneSignalResumeConfig(next_cursor=state.get("cursor"), next_offset=state.get("offset"))
            )

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
        primary_keys=list(endpoint_config.primary_keys),
        partition_keys=[endpoint_config.partition_key],
        partition_mode="datetime",
        partition_format="month",
        partition_size=1,
        partition_count=1,
        sort_mode="asc",
    )
