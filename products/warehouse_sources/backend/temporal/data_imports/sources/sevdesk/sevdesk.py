from collections.abc import Iterator
from typing import Any

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    EndpointResource,
    RESTAPIConfig,
    RESTClient,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import APIKeyAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.sevdesk.settings import (
    BASE_URL,
    ENDPOINTS,
    PAGE_SIZE,
    REQUEST_TIMEOUT_SECONDS,
)


@frozen
class SevdeskResumeConfig:
    offset: int = 0
    completed: bool = False


def validate_credentials(api_token: str, endpoint: str, api_version: str) -> None:
    endpoint_config = schema_for_resource(ENDPOINTS, endpoint)
    client = RESTClient(
        base_url=f"{BASE_URL}/{api_version}",
        auth=APIKeyAuth(api_key=api_token, name="Authorization", location="header"),
        headers={"Accept": "application/json", "User-Agent": "PostHog warehouse source"},
        request_timeout=REQUEST_TIMEOUT_SECONDS,
    )
    try:
        next(
            client.paginate(
                path=endpoint_config.path,
                params={**endpoint_config.params, "limit": 1, "offset": 0},
                paginator=SinglePagePaginator(),
                data_selector="objects",
                data_selector_malformed_retryable=True,
            )
        )
    finally:
        client.session.close()


def sevdesk_source(
    api_token: str,
    endpoint: str,
    api_version: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[SevdeskResumeConfig],
) -> SourceResponse:
    endpoint_config = schema_for_resource(ENDPOINTS, endpoint)
    resource: EndpointResource = {
        "name": endpoint,
        "table_name": endpoint,
        "primary_key": list(endpoint_config.primary_keys),
        "write_disposition": "replace",
        "table_format": "delta",
        "endpoint": {
            "path": endpoint_config.path,
            "params": endpoint_config.params,
            "data_selector": "objects",
            "data_selector_malformed_retryable": True,
            "paginator": {"type": "offset", "limit": PAGE_SIZE, "total_path": None},
        },
    }
    config: RESTAPIConfig = {
        "client": {
            "base_url": f"{BASE_URL}/{api_version}",
            "auth": {"type": "api_key", "api_key": api_token, "name": "Authorization", "location": "header"},
            "headers": {"Accept": "application/json", "User-Agent": "PostHog warehouse source"},
            "request_timeout": REQUEST_TIMEOUT_SECONDS,
        },
        "resources": [resource],
    }

    def save_page_state(state: dict[str, Any] | None) -> None:
        resumable_source_manager.save_state(
            SevdeskResumeConfig(offset=state["offset"]) if state is not None else SevdeskResumeConfig(completed=True)
        )

    def get_rows() -> Iterator[list[dict[str, Any]]]:
        state = resumable_source_manager.load_state()
        if state is not None and state.completed:
            return
        resource = rest_api_resource(
            config,
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=None,
            resume_hook=save_page_state,
            initial_paginator_state={"offset": state.offset} if state is not None else None,
        )
        yield from resource

    return SourceResponse(
        name=endpoint,
        items=get_rows,
        primary_keys=list(endpoint_config.primary_keys),
        partition_keys=[endpoint_config.partition_key],
        partition_mode="datetime",
        partition_format="month",
        # The list API does not document a stable timestamp sort for every resource.
        sort_mode=None,
    )
