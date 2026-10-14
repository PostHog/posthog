from collections.abc import Generator
from typing import TYPE_CHECKING, cast

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.config_setup import create_auth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.pinecone.settings import BASE_URL, ENDPOINTS

if TYPE_CHECKING:
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
        ClientConfig,
        Endpoint,
        EndpointResource,
    )
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager


@frozen
class PineconeResumeConfig:
    cursor: str


def get_client_config(api_key: str, api_version: str) -> "ClientConfig":
    return {
        "base_url": BASE_URL,
        "auth": {"type": "api_key", "api_key": api_key, "name": "Api-Key", "location": "header"},
        "headers": {"X-Pinecone-Api-Version": api_version},
        "request_timeout": (10, 60),
        "allowed_hosts": [],
        "allow_redirects": False,
    }


def get_resource(endpoint: str) -> "EndpointResource":
    settings = schema_for_resource(ENDPOINTS, endpoint)
    endpoint_config: Endpoint = {
        "path": settings.path,
        "data_selector": settings.data_selector,
        "data_selector_required": True,
        "paginator": {
            "type": "cursor",
            "cursor_path": "pagination.next",
            "cursor_param": "paginationToken",
        }
        if settings.paginated
        else "single_page",
    }
    if settings.paginated:
        endpoint_config["params"] = {"limit": 100}
    return {
        "name": endpoint,
        "table_name": endpoint,
        "primary_key": settings.primary_key,
        "write_disposition": "replace",
        "endpoint": endpoint_config,
    }


def validate_credentials(api_key: str, api_version: str, endpoint: str) -> None:
    settings = schema_for_resource(ENDPOINTS, endpoint)
    config = get_client_config(api_key, api_version)
    client = RESTClient(
        base_url=config["base_url"],
        auth=create_auth(config["auth"]),
        headers=config["headers"],
        request_timeout=config["request_timeout"],
        allowed_hosts=config["allowed_hosts"],
        allow_redirects=False,
    )
    pages = cast(
        "Generator[list[object]]",
        client.paginate(
            path=settings.path,
            params={"limit": 1} if settings.paginated else {},
            data_selector=settings.data_selector,
            data_selector_required=True,
        ),
    )
    try:
        next(pages, None)
    finally:
        pages.close()
        client.session.close()


def pinecone_source(
    api_key: str,
    api_version: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: "ResumableSourceManager[PineconeResumeConfig]",
) -> SourceResponse:
    settings = schema_for_resource(ENDPOINTS, endpoint)
    config: RESTAPIConfig = {
        "client": get_client_config(api_key, api_version),
        "resources": [get_resource(endpoint)],
    }
    initial_state: dict[str, str] | None = None
    if settings.paginated and resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_state = {"cursor": resume.cursor}

    def save_checkpoint(state: dict[str, object] | None) -> None:
        if state and isinstance(state.get("cursor"), str):
            resumable_source_manager.save_state(PineconeResumeConfig(cursor=str(state["cursor"])))

    resource = rest_api_resource(
        config,
        team_id,
        job_id,
        db_incremental_field_last_value=None,
        initial_paginator_state=initial_state,
        resume_hook=save_checkpoint if settings.paginated else None,
    )
    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=[settings.primary_key],
        partition_count=1 if settings.partition_mode == "md5" else None,
        partition_keys=[settings.partition_key],
        partition_mode=settings.partition_mode,
        partition_format="month" if settings.partition_mode == "datetime" else None,
        sort_mode=None,
        supports_resume=settings.paginated,
    )
