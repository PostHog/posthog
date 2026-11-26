from typing import Any
from uuid import UUID

from requests import Response
from requests.exceptions import HTTPError, RequestException

from products.warehouse_sources.sources.onesignal.settings import (
    BASE_URL,
    INITIAL_TIME_OFFSET,
    ONESIGNAL_ENDPOINTS,
    OneSignalEndpoint,
)
from products.warehouse_sources.sources.sdk import (
    APIKeyAuth,
    BasePaginator,
    ClientConfig,
    Endpoint,
    EndpointResource,
    JSONResponseCursorPaginator,
    OffsetPaginator,
    RESTAPIConfig,
    RESTClient,
    RESTClientNonRetryableError,
    RESTClientRetryableError,
    ResumableSourceManager,
    SinglePagePaginator,
    SourceResponse,
    frozen,
    rest_api_resource,
    rest_api_resources,
    schema_for_resource,
)


@frozen
class OneSignalResumeConfig:
    next_cursor: str | None = None
    next_offset: int | None = None
    fanout_state: dict[str, Any] | None = None


class OneSignalMessagePaginator(JSONResponseCursorPaginator):
    def __init__(self) -> None:
        super().__init__(cursor_path="next_time_offset", cursor_param="time_offset", raise_on_repeated_cursor=True)

    def update_state(self, response: Response, data: list[Any] | None = None) -> None:
        # OneSignal can keep a cursor on an empty page for polling. A snapshot must stop there.
        if not data:
            self._has_next_page = False
            return
        super().update_state(response, data)


def _paginator(endpoint: OneSignalEndpoint) -> BasePaginator:
    if endpoint.pagination == "time_offset":
        return OneSignalMessagePaginator()
    if endpoint.pagination == "next_cursor":
        return JSONResponseCursorPaginator(cursor_path="next_cursor", cursor_param="cursor")
    if endpoint.pagination == "offset":
        return OffsetPaginator(limit=endpoint.page_size, total_path="total_count")
    return SinglePagePaginator()


def _endpoint_config(endpoint: OneSignalEndpoint, app_id: str) -> Endpoint:
    params: dict[str, Any] = {}
    if endpoint.pagination != "single":
        params["limit"] = endpoint.page_size
    if endpoint.app_id_in_query:
        params["app_id"] = app_id
    if endpoint.pagination == "time_offset":
        params["time_offset"] = INITIAL_TIME_OFFSET
    return {
        "path": endpoint.path.replace("{app_id}", app_id),
        "data_selector": endpoint.data_selector,
        "data_selector_required": True,
        "params": params,
        "paginator": _paginator(endpoint),
    }


def get_resource(name: str, app_id: str) -> EndpointResource:
    endpoint = schema_for_resource(ONESIGNAL_ENDPOINTS, name)
    return {
        "name": name,
        "table_name": name,
        "table_format": "delta",
        "write_disposition": "replace",
        "endpoint": _endpoint_config(endpoint, str(UUID(app_id))),
    }


def get_fanout_resources(name: str, app_id: str) -> list[str | EndpointResource]:
    endpoint = schema_for_resource(ONESIGNAL_ENDPOINTS, name)
    assert endpoint.fanout is not None
    app_id = str(UUID(app_id))
    child = _endpoint_config(endpoint, app_id)
    child["params"] = {
        endpoint.fanout.resolve_param: {
            "type": "resolve",
            "resource": endpoint.fanout.parent,
            "field": endpoint.fanout.resolve_field,
        }
    }
    # A journey deleted between the list call and its stats call returns 404. Skip it.
    child["response_actions"] = [{"status_code": 404, "action": "ignore"}]
    return [
        get_resource(endpoint.fanout.parent, app_id),
        {
            "name": name,
            "table_name": name,
            "table_format": "delta",
            "write_disposition": "replace",
            "endpoint": child,
        },
    ]


def validate_credentials(api_key: str, app_id: str, endpoint: str) -> tuple[bool, str | None]:
    endpoint_config = schema_for_resource(ONESIGNAL_ENDPOINTS, endpoint)
    if endpoint_config.fanout is not None:
        endpoint_config = schema_for_resource(ONESIGNAL_ENDPOINTS, endpoint_config.fanout.parent)
    app_id = str(UUID(app_id))
    params: dict[str, Any] = {"limit": 1}
    if endpoint_config.app_id_in_query:
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
                path=endpoint_config.path.replace("{app_id}", app_id),
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
    client: ClientConfig = {
        "base_url": BASE_URL,
        "auth": {"type": "api_key", "name": "Authorization", "api_key": f"Key {api_key}", "location": "header"},
        "request_timeout": (10, 30),
        "retry_budget_seconds": 120,
        "retry_after_max_seconds": 60,
    }
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    if endpoint_config.fanout is not None:

        def save_fanout_checkpoint(state: dict[str, Any] | None) -> None:
            if state is not None:
                resumable_source_manager.save_state(OneSignalResumeConfig(fanout_state=state))

        resources = rest_api_resources(
            {"client": client, "resources": get_fanout_resources(endpoint, app_id)},
            team_id,
            job_id,
            None,
            resume_hook=save_fanout_checkpoint,
            initial_paginator_state=resume.fanout_state if resume is not None else None,
        )
        resource = next(r for r in resources if getattr(r, "name", None) == endpoint)
    else:
        initial_state: dict[str, Any] | None = None
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

        config: RESTAPIConfig = {"client": client, "resources": [get_resource(endpoint, app_id)]}
        resource = rest_api_resource(
            config,
            team_id,
            job_id,
            None,
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_state,
        )

    if endpoint_config.partition_key is None:
        return SourceResponse(
            name=endpoint, items=lambda: resource, primary_keys=list(endpoint_config.primary_keys), sort_mode="asc"
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
