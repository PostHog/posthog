from typing import Any

from products.warehouse_sources.sources.klarna._config import KlarnaSourceConfig
from products.warehouse_sources.sources.klarna.settings import BASE_URLS, ENDPOINTS, PAGE_SIZE, KlarnaEndpoint
from products.warehouse_sources.sources.sdk import (
    APIKeyAuth,
    AuthConfigBase,
    HttpBasicAuth,
    PaginatorConfig,
    RESTAPIConfig,
    ResumableSourceManager,
    SourceResponse,
    format_datetime,
    frozen,
    make_tracked_session,
    rest_api_resource,
    schema_for_resource,
)


@frozen
class KlarnaResumeConfig:
    offset: int = 0
    starting_after: str | None = None


def klarna_auth(config: KlarnaSourceConfig) -> AuthConfigBase:
    if config.username:
        return HttpBasicAuth(username=config.username, password=config.api_key)
    return APIKeyAuth(api_key=f"Basic {config.api_key}")


def klarna_base_url(config: KlarnaSourceConfig) -> str:
    return f"{BASE_URLS[config.environment][config.region]}/"


def endpoint_path(endpoint_config: KlarnaEndpoint, api_version: str) -> str:
    return endpoint_config.path.format(api_version=api_version)


def probe_params(endpoint_config: KlarnaEndpoint) -> dict[str, Any]:
    if endpoint_config.pagination == "cursor":
        return {"size": 1}
    return {"size": 1, "offset": 0}


def paginator_config(endpoint_config: KlarnaEndpoint) -> PaginatorConfig:
    if endpoint_config.pagination == "cursor":
        return {
            "type": "cursor",
            "cursor_path": "pagination.last_item",
            "cursor_param": "starting_after",
            "raise_on_repeated_cursor": True,
        }
    return {
        "type": "offset",
        "limit": PAGE_SIZE,
        "limit_param": "size",
        "offset_param": "offset",
        "total_path": "pagination.total",
    }


def initial_paginator_state(
    endpoint_config: KlarnaEndpoint, resume: KlarnaResumeConfig | None
) -> dict[str, Any] | None:
    if resume is None:
        return None
    if endpoint_config.pagination == "cursor":
        return {"cursor": resume.starting_after} if resume.starting_after else None
    return {"offset": resume.offset}


def to_resume_config(endpoint_config: KlarnaEndpoint, state: dict[str, Any] | None) -> KlarnaResumeConfig | None:
    if state is None:
        return None
    if endpoint_config.pagination == "cursor":
        return KlarnaResumeConfig(starting_after=str(state["cursor"])) if state.get("cursor") else None
    return KlarnaResumeConfig(offset=int(state["offset"])) if state.get("offset") is not None else None


def probe_credentials(config: KlarnaSourceConfig, endpoint: str, api_version: str) -> None:
    endpoint_config = schema_for_resource(ENDPOINTS, endpoint)
    auth = klarna_auth(config)
    with make_tracked_session(redact_values=(*auth.secret_values(), config.api_key)) as session:
        response = session.get(
            f"{klarna_base_url(config)}{endpoint_path(endpoint_config, api_version)}",
            auth=auth,
            params=probe_params(endpoint_config),
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
    should_use_incremental_field: bool = False,
    incremental_field: str | None = None,
    db_incremental_field_last_value: Any = None,
) -> SourceResponse:
    endpoint_config = schema_for_resource(ENDPOINTS, endpoint)
    params: dict[str, Any] = {}
    if endpoint_config.pagination == "cursor":
        params["sort_by"] = "created_at"
    if should_use_incremental_field and incremental_field and db_incremental_field_last_value is not None:
        params[f"{incremental_field}_start"] = format_datetime(db_incremental_field_last_value, "iso_z")
    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": klarna_base_url(config),
            "auth": klarna_auth(config),
            "headers": {"Accept": "application/json"},
            "allowed_hosts": [],
            "allow_redirects": False,
            "paginator": paginator_config(endpoint_config),
        },
        "resources": [
            {
                "name": endpoint,
                "table_name": endpoint,
                "primary_key": endpoint_config.primary_keys,
                "write_disposition": {"disposition": "merge", "strategy": "upsert"}
                if should_use_incremental_field
                else "replace",
                "table_format": "delta",
                "endpoint": {
                    "path": endpoint_path(endpoint_config, api_version),
                    "params": params,
                    "data_selector": endpoint_config.data_selector,
                    "data_selector_required": True,
                },
            }
        ],
    }
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        resume_config = to_resume_config(endpoint_config, state)
        if resume_config is not None:
            resumable_source_manager.save_state(resume_config)

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state(endpoint_config, resume),
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
