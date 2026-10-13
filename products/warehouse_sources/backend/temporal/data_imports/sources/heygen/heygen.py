from typing import Any

from requests.exceptions import HTTPError

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    RESTClient,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import APIKeyAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.heygen.settings import BASE_URL, ENDPOINTS

INVALID_API_KEY = "Your HeyGen API key is invalid or expired. Update the key and reconnect."


@frozen
class HeyGenResumeConfig:
    cursor: str


def get_resource(endpoint: str, api_version: str) -> EndpointResource:
    settings = schema_for_resource(ENDPOINTS, endpoint)
    return {
        "name": endpoint,
        "table_name": endpoint,
        "write_disposition": "replace",
        "endpoint": {
            "path": f"/{api_version}/{settings.path}",
            "data_selector": "data",
            "data_selector_required": True,
            "params": {"limit": settings.page_size, **settings.params} if settings.paginated else {},
            "paginator": {"type": "cursor", "cursor_path": "next_token", "cursor_param": "token"}
            if settings.paginated
            else "single_page",
        },
    }


def heygen_source(
    api_key: str,
    endpoint: str,
    api_version: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[HeyGenResumeConfig],
) -> SourceResponse:
    settings = schema_for_resource(ENDPOINTS, endpoint)
    config: RESTAPIConfig = {
        "client": {
            "base_url": BASE_URL,
            "auth": {"type": "api_key", "name": "x-api-key", "api_key": api_key, "location": "header"},
            "allowed_hosts": [],
            "allow_redirects": False,
            "request_timeout": 60,
        },
        "resources": [get_resource(endpoint, api_version)],
    }
    resume = (
        resumable_source_manager.load_state() if settings.paginated and resumable_source_manager.can_resume() else None
    )

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state and state.get("cursor"):
            resumable_source_manager.save_state(HeyGenResumeConfig(cursor=str(state["cursor"])))
        else:
            resumable_source_manager.clear_state()

    resource = rest_api_resource(
        config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint if settings.paginated else None,
        initial_paginator_state={"cursor": resume.cursor} if resume else None,
    )
    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=[settings.primary_key],
        partition_keys=[settings.partition_key or settings.primary_key],
        partition_mode="datetime" if settings.partition_key else "md5",
        partition_format="month" if settings.partition_key else None,
        partition_count=None if settings.partition_key else 1,
        supports_resume=settings.paginated,
        sort_mode=settings.sort_mode,
    )


def probe_endpoint(api_key: str, endpoint: str, api_version: str) -> int:
    settings = schema_for_resource(ENDPOINTS, endpoint)
    client = RESTClient(
        base_url=BASE_URL,
        auth=APIKeyAuth(api_key=api_key, name="x-api-key", location="header"),
        allowed_hosts=[],
        allow_redirects=False,
        request_timeout=60,
    )
    try:
        pages = client.paginate(
            path=f"/{api_version}/{settings.path}",
            params={"limit": 1, **settings.params} if settings.paginated else {},
            paginator=SinglePagePaginator(),
            data_selector="data",
            data_selector_required=True,
        )
        next(pages)
    except HTTPError as error:
        if error.response is not None and error.response.status_code in (401, 403):
            return error.response.status_code
        raise
    return 200


def permission_error(endpoint: str) -> str:
    settings = schema_for_resource(ENDPOINTS, endpoint)
    return f"Your HeyGen API key needs the `{settings.scope}` scope to sync this table. Update the key permissions."
