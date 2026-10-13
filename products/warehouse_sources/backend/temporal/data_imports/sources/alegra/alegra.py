from typing import Any

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.alegra.settings import (
    API_BASE_URL,
    ENDPOINTS,
    PAGE_SIZE,
    PARTITION_COUNT,
    PARTITION_MODE,
    REQUEST_TIMEOUT,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    RESTClient,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import HttpBasicAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ClientConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.alegra import AlegraSourceConfig


@frozen
class AlegraResumeConfig:
    offset: int


def client_config(config: AlegraSourceConfig, api_version: str) -> ClientConfig:
    return {
        "base_url": API_BASE_URL.format(version=api_version),
        "auth": {"type": "http_basic", "username": config.email, "password": config.api_token},
        "headers": {"Accept": "application/json"},
        "allowed_hosts": [],
        "allow_redirects": False,
        "request_timeout": REQUEST_TIMEOUT,
        # Eight attempts let exponential backoff outlast Alegra's minute-long rate-limit window.
        "max_retries": 8,
    }


def validate_credentials(config: AlegraSourceConfig, api_version: str) -> None:
    client = RESTClient(
        base_url=API_BASE_URL.format(version=api_version),
        auth=HttpBasicAuth(username=config.email, password=config.api_token),
        headers={"Accept": "application/json"},
        allowed_hosts=[],
        allow_redirects=False,
        request_timeout=REQUEST_TIMEOUT,
        max_retry_attempts=8,
    )
    next(client.paginate(path="company", paginator=SinglePagePaginator()))


def alegra_source(
    config: AlegraSourceConfig,
    inputs: SourceInputs,
    resumable_source_manager: ResumableSourceManager[AlegraResumeConfig],
    api_version: str,
) -> SourceResponse:
    endpoint = schema_for_resource(ENDPOINTS, inputs.schema_name)
    api_config: RESTAPIConfig = {
        "client": client_config(config, api_version),
        "resources": [
            {
                "name": inputs.schema_name,
                "primary_key": list(endpoint.primary_keys),
                "write_disposition": "replace",
                "endpoint": {
                    "path": endpoint.path,
                    "params": dict(endpoint.params),
                    "data_selector_required": True,
                    "paginator": {
                        "type": "offset",
                        "limit": PAGE_SIZE,
                        "offset_param": "start",
                        "total_path": None,
                    },
                },
            }
        ],
    }
    initial_state: dict[str, Any] | None = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_state = {"offset": resume.offset}

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state is not None:
            resumable_source_manager.save_state(AlegraResumeConfig(offset=int(state["offset"])))

    resource = rest_api_resource(
        api_config,
        inputs.team_id,
        inputs.job_id,
        db_incremental_field_last_value=None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_state,
    )
    return SourceResponse(
        name=inputs.schema_name,
        items=lambda: resource,
        primary_keys=list(endpoint.primary_keys),
        partition_keys=list(endpoint.partition_keys),
        partition_mode=PARTITION_MODE,
        partition_count=PARTITION_COUNT,
        sort_mode=None,
    )
