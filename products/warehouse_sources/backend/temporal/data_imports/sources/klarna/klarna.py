from typing import Any

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import (
    APIKeyAuth,
    AuthConfigBase,
    HttpBasicAuth,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.klarna import KlarnaSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.klarna.settings import (
    BASE_URLS,
    ENDPOINTS,
    PAGE_SIZE,
)


@frozen
class KlarnaResumeConfig:
    offset: int


def klarna_auth(config: KlarnaSourceConfig) -> AuthConfigBase:
    if config.username:
        return HttpBasicAuth(username=config.username, password=config.api_key)
    return APIKeyAuth(api_key=f"Basic {config.api_key}")


def klarna_base_url(config: KlarnaSourceConfig, api_version: str) -> str:
    return f"{BASE_URLS[config.environment][config.region]}/settlements/{api_version}/"


def probe_credentials(config: KlarnaSourceConfig, endpoint: str, api_version: str) -> None:
    endpoint_config = schema_for_resource(ENDPOINTS, endpoint)
    auth = klarna_auth(config)
    with make_tracked_session(redact_values=(*auth.secret_values(), config.api_key)) as session:
        response = session.get(
            f"{klarna_base_url(config, api_version)}{endpoint_config.path}",
            auth=auth,
            params={"size": 1, "offset": 0},
            headers={"Accept": "application/json"},
            timeout=30,
            allow_redirects=False,
        )
        response.raise_for_status()
        if response.status_code != 200:
            raise ValueError("Klarna returned an unexpected response. Check the region and environment.")


def klarna_source(
    config: KlarnaSourceConfig,
    endpoint: str,
    team_id: int,
    job_id: str,
    api_version: str,
    resumable_source_manager: ResumableSourceManager[KlarnaResumeConfig],
) -> SourceResponse:
    endpoint_config = schema_for_resource(ENDPOINTS, endpoint)
    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": klarna_base_url(config, api_version),
            "auth": klarna_auth(config),
            "headers": {"Accept": "application/json"},
            "allowed_hosts": [],
            "allow_redirects": False,
            "paginator": {
                "type": "offset",
                "limit": PAGE_SIZE,
                "limit_param": "size",
                "offset_param": "offset",
                "total_path": "pagination.total",
            },
        },
        "resources": [
            {
                "name": endpoint,
                "table_name": endpoint,
                "primary_key": endpoint_config.primary_keys,
                "write_disposition": "replace",
                "table_format": "delta",
                "endpoint": {
                    "path": endpoint_config.path,
                    "data_selector": endpoint_config.data_selector,
                    "data_selector_required": True,
                },
            }
        ],
    }
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state is not None and state.get("offset") is not None:
            resumable_source_manager.save_state(KlarnaResumeConfig(offset=int(state["offset"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state={"offset": resume.offset} if resume else None,
    )
    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=endpoint_config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_keys=[endpoint_config.partition_key],
        partition_mode="datetime",
        partition_format="month",
        sort_mode=None,
    )
