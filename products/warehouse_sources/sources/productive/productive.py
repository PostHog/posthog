from collections.abc import Iterator
from typing import Any

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import APIKeyAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ClientConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.productive import (
    ProductiveSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.productive.settings import ENDPOINTS, PAGE_SIZE


@frozen
class ProductiveResumeConfig:
    next_page: int | None


def _client_config(config: ProductiveSourceConfig, api_version: str) -> ClientConfig:
    return {
        "base_url": f"https://api.productive.io/api/{api_version}/",
        "auth": APIKeyAuth(name="X-Auth-Token", api_key=config.api_token, location="header"),
        "headers": {
            "X-Organization-Id": config.organization_id,
            "Content-Type": "application/vnd.api+json",
            "Accept": "application/vnd.api+json",
        },
        "allowed_hosts": ["api.productive.io"],
        "allow_redirects": False,
        "request_timeout": 60,
    }


def probe_credentials(config: ProductiveSourceConfig, endpoint: str, team_id: int, api_version: str) -> None:
    endpoint_config = schema_for_resource(ENDPOINTS, endpoint)
    api_config: RESTAPIConfig = {
        "client": _client_config(config, api_version),
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": endpoint_config.path,
                    "params": {"page[size]": 1, "page[number]": 1},
                    "data_selector": "data",
                    "data_selector_required": True,
                    "paginator": "single_page",
                },
            }
        ],
    }
    next(iter(rest_api_resource(api_config, team_id, "", None)), None)


def _flatten_attributes(item: dict[str, Any]) -> dict[str, Any]:
    return {**item.get("attributes", {}), **{key: value for key, value in item.items() if key != "attributes"}}


def productive_source(
    config: ProductiveSourceConfig,
    inputs: SourceInputs,
    resumable_source_manager: ResumableSourceManager[ProductiveResumeConfig],
    api_version: str,
) -> SourceResponse:
    endpoint = schema_for_resource(ENDPOINTS, inputs.schema_name)
    api_config: RESTAPIConfig = {
        "client": _client_config(config, api_version),
        "resources": [
            {
                "name": inputs.schema_name,
                "write_disposition": "replace",
                "endpoint": {
                    "path": endpoint.path,
                    "params": {"page[size]": PAGE_SIZE},
                    "data_selector": "data",
                    "data_selector_required": True,
                    "paginator": PageNumberPaginator(
                        base_page=1, page_param="page[number]", total_path="meta.total_pages"
                    ),
                },
            }
        ],
    }

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        resumable_source_manager.save_state(ProductiveResumeConfig(next_page=int(state["page"]) if state else None))

    def get_rows() -> Iterator[list[dict[str, Any]]]:
        resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
        if resume is not None and resume.next_page is None:
            return
        resource = rest_api_resource(
            api_config,
            inputs.team_id,
            inputs.job_id,
            None,
            resume_hook=save_checkpoint,
            initial_paginator_state={"page": resume.next_page} if resume is not None else None,
        ).add_map(_flatten_attributes)
        yield from resource

    return SourceResponse(
        name=inputs.schema_name,
        items=get_rows,
        primary_keys=list(endpoint.primary_keys),
        partition_keys=[endpoint.partition_key],
        partition_mode=endpoint.partition_mode,
        partition_format="month" if endpoint.partition_mode == "datetime" else None,
        partition_count=16 if endpoint.partition_mode == "md5" else None,
        sort_mode=None,
    )
