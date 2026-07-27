import dataclasses
from collections.abc import Callable
from typing import Any, Optional, cast

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.census.settings import (
    CENSUS_ENDPOINTS,
    CENSUS_HOSTS,
    CensusEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe


@dataclasses.dataclass
class CensusResumeConfig:
    # Opaque framework checkpoint: `{"page": N}` for top-level endpoints, or the fan-out
    # manager's `{"completed": [...], "current": ..., "child_state": {"page": N}}` for
    # sync_runs — round-tripped into `initial_paginator_state` on resume.
    paginator_state: dict[str, Any]


def _host(region: str) -> str:
    return CENSUS_HOSTS.get(region, CENSUS_HOSTS["us"])


def _paginator() -> PageNumberPaginator:
    # Census pages are 1-indexed and the response echoes `pagination.last_page`, so the
    # paginator can stop precisely instead of paying one extra empty-page request.
    return PageNumberPaginator(base_page=1, page_param="page", total_path="pagination.last_page")


def _client_config(api_key: str, region: str) -> ClientConfig:
    return {
        "base_url": _host(region),
        "headers": {"Accept": "application/json"},
        "auth": {"type": "bearer", "token": api_key},
        # Census responses echo `connection_details` (warehouse account, user, and warehouse
        # identifiers) which `_drop_fields` strips per-row — but HTTP sample capture records the
        # raw body before the mapper runs, so `capture=False` keeps that metadata out of samples.
        "session": make_tracked_session(capture=False, redact_values=(api_key,)),
    }


def _drop_fields(fields: tuple[str, ...]) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def _mapper(row: dict[str, Any]) -> dict[str, Any]:
        for field_name in fields:
            row.pop(field_name, None)
        return row

    return _mapper


def validate_credentials(api_key: str, region: str, schema_name: Optional[str] = None) -> tuple[bool, str | None]:
    # A missing scope on a workspace token would 403 rather than 401; accept that at source-create
    # (schema_name is None) since the user may only want to sync a subset of resources.
    ok_statuses = (200, 403) if schema_name is None else (200,)
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,), capture=False),
        f"{_host(region)}/api/v1/syncs",
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        ok_statuses=ok_statuses,
        allow_redirects=False,
    )
    if ok:
        return True, None
    if status == 401:
        return False, "Census rejected the API token. Generate a new workspace access token and reconnect."
    if status == 403:
        return False, "Your Census API token does not have access to this resource."
    if status is None:
        return False, "Could not reach Census. Please check your network and selected region, then retry."
    return False, f"Census API returned an unexpected status: {status}"


def get_resource(endpoint: str) -> EndpointResource:
    config = CENSUS_ENDPOINTS[endpoint]
    if config.fanout:
        raise ValueError(f"Fan-out endpoint '{endpoint}' must use the fan-out path")

    endpoint_config: Endpoint = {
        "path": config.path,
        # `order=asc` (oldest-created-first) keeps offset-style page-number pagination stable:
        # new rows created mid-sync are appended past the last page instead of shifting rows
        # already fetched (Census's implicit default is newest-first).
        "params": {"per_page": config.page_size, "order": "asc"},
        "data_selector": "data",
        "paginator": _paginator(),
    }

    resource: EndpointResource = {
        "name": config.name,
        "table_name": config.name,
        "write_disposition": "replace",
        "endpoint": endpoint_config,
        "table_format": "delta",
    }
    if config.strip_fields:
        resource["data_map"] = _drop_fields(config.strip_fields)
    return resource


def _make_source_response(endpoint_config: CensusEndpointConfig, items_fn: Any) -> SourceResponse:
    return SourceResponse(
        name=endpoint_config.name,
        items=items_fn,
        primary_keys=endpoint_config.primary_key
        if isinstance(endpoint_config.primary_key, list)
        else [endpoint_config.primary_key],
        sort_mode=endpoint_config.sort_mode,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )


def census_source(
    api_key: str,
    region: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[CensusResumeConfig],
) -> SourceResponse:
    endpoint_config = CENSUS_ENDPOINTS[endpoint]

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = resume_config.paginator_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Only persist when there's somewhere to resume to; the Redis TTL handles cleanup.
        if state:
            resumable_source_manager.save_state(CensusResumeConfig(paginator_state=dict(state)))

    if endpoint_config.fanout:
        dependent_resource = build_dependent_resource(
            endpoint_configs=cast(Any, CENSUS_ENDPOINTS),
            child_endpoint=endpoint,
            fanout=endpoint_config.fanout,
            client_config=_client_config(api_key, region),
            path_format_values={},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=None,
            page_size_param="per_page",
            parent_endpoint_extra={
                "paginator": _paginator(),
                "data_selector": "data",
            },
            child_endpoint_extra={
                "paginator": _paginator(),
                "data_selector": "data",
            },
            child_params_extra={"order": "asc"},
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_paginator_state,
        )
        return _make_source_response(endpoint_config, lambda: dependent_resource)

    config: RESTAPIConfig = {
        "client": _client_config(api_key, region),
        "resource_defaults": {"write_disposition": "replace"},
        "resources": [get_resource(endpoint=endpoint)],
    }

    resource = rest_api_resource(
        config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    return _make_source_response(endpoint_config, lambda: resource)
