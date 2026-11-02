from typing import Any

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import APIKeyAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponsePaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.statsig.settings import (
    BASE_URL,
    ENDPOINTS,
    PAGE_SIZE,
)


@frozen
class StatsigResumeConfig:
    next_url: str


class StatsigPaginator(JSONResponsePaginator):
    def __init__(self) -> None:
        super().__init__(next_url_path="pagination.nextPage")

    def _advance_to(self, next_url: str | None, base_url: str | None = None) -> None:
        # The audit log examples omit the scheme. A relative URL would repeat the host in the request path.
        # https://api.statsig.com/openapi/20240601.json
        if next_url and next_url.startswith("statsigapi.net/"):
            next_url = f"https://{next_url}"
        super()._advance_to(next_url, base_url)


def probe_credentials(api_key: str, path: str, api_version: str) -> None:
    client = RESTClient(
        base_url=BASE_URL,
        auth=APIKeyAuth(api_key=api_key, name="STATSIG-API-KEY", location="header"),
        headers={"STATSIG-API-VERSION": api_version},
        allowed_hosts=[],
        allow_redirects=False,
        request_timeout=(10, 30),
    )
    try:
        next(
            client.paginate(
                path,
                params={"page": 1, "limit": 1},
                paginator=SinglePagePaginator(),
                data_selector="data",
                data_selector_required=True,
                data_selector_empty_ok=True,
            )
        )
    finally:
        client.session.close()


def statsig_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    api_version: str,
    resumable_source_manager: ResumableSourceManager[StatsigResumeConfig],
) -> SourceResponse:
    settings = schema_for_resource(ENDPOINTS, endpoint)
    config: RESTAPIConfig = {
        "client": {
            "base_url": BASE_URL,
            "auth": {"type": "api_key", "api_key": api_key, "name": "STATSIG-API-KEY", "location": "header"},
            "headers": {"STATSIG-API-VERSION": api_version},
            "allowed_hosts": [],
            "allow_redirects": False,
            "request_timeout": (10, 60),
        },
        "resources": [
            {
                "name": endpoint,
                "primary_key": settings.primary_key,
                "write_disposition": "replace",
                "endpoint": {
                    "path": settings.path,
                    "params": {"page": 1, "limit": PAGE_SIZE},
                    "data_selector": "data",
                    "data_selector_required": True,
                    "data_selector_empty_ok": True,
                    "paginator": StatsigPaginator(),
                },
            }
        ],
    }
    initial_paginator_state: dict[str, Any] | None = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"next_url": resume.next_url}

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state and state.get("next_url"):
            resumable_source_manager.save_state(StatsigResumeConfig(next_url=state["next_url"]))

    resource = rest_api_resource(
        config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=[settings.primary_key],
        partition_keys=[settings.partition_key],
        partition_mode="md5",
        partition_count=1,
        sort_mode=None,
    )
