from typing import Any

from requests import HTTPError

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import BearerTokenAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.vimeo.settings import (
    AUTH_ERROR,
    BASE_URL,
    ENDPOINTS,
    PAGE_SIZE,
    PERMISSION_ERROR,
    PRIMARY_KEYS,
)


@frozen
class VimeoResumeConfig:
    next_url: str


def vimeo_headers(api_version: str) -> dict[str, str]:
    return {"Accept": f"application/vnd.vimeo.*+json;version={api_version}"}


def validate_credentials(access_token: str, api_version: str, schema_name: str | None) -> tuple[bool, str | None]:
    path = schema_for_resource(ENDPOINTS, schema_name) if schema_name else "/me"
    params: dict[str, str | int] = {"per_page": 1} if schema_name else {"fields": "uri"}
    with make_tracked_session() as session:
        response = session.get(
            f"{BASE_URL}{path}",
            auth=BearerTokenAuth(access_token),
            headers=vimeo_headers(api_version),
            params=params,
            timeout=30,
        )
    try:
        response.raise_for_status()
    except HTTPError:
        if response.status_code == 401:
            return False, AUTH_ERROR
        if response.status_code == 403:
            return (False, PERMISSION_ERROR) if schema_name else (True, None)
        raise
    return True, None


def vimeo_source(
    access_token: str,
    endpoint: str,
    api_version: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[VimeoResumeConfig],
) -> SourceResponse:
    path = schema_for_resource(ENDPOINTS, endpoint)
    config: RESTAPIConfig = {
        "client": {
            "base_url": BASE_URL,
            "auth": {"type": "bearer", "token": access_token},
            "headers": vimeo_headers(api_version),
            "paginator": {"type": "json_response", "next_url_path": "paging.next"},
            "allowed_hosts": ["api.vimeo.com"],
            "allow_redirects": False,
            "request_timeout": 30,
        },
        "resources": [
            {
                "name": endpoint,
                "primary_key": PRIMARY_KEYS,
                "write_disposition": "replace",
                "endpoint": {
                    "path": path,
                    "params": {"page": 1, "per_page": PAGE_SIZE, "sort": "date", "direction": "asc"},
                    "data_selector": "data",
                    "data_selector_required": True,
                },
            }
        ],
    }
    initial_state = None
    if resumable_source_manager.can_resume():
        state = resumable_source_manager.load_state()
        if state is not None:
            initial_state = {"next_url": state.next_url}

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state and state.get("next_url"):
            resumable_source_manager.save_state(VimeoResumeConfig(next_url=state["next_url"]))

    resource: Resource = rest_api_resource(
        config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_state,
    )
    return SourceResponse(name=endpoint, items=lambda: resource, primary_keys=PRIMARY_KEYS)
